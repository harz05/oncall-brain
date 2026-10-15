"""The graph tools. Each one runs named Cypher through the GraphRepository port and returns a ToolOutput
(summary, data, the queries it ran, and the graph ids to highlight). Registered once in agents.registry."""

import time

from pydantic import BaseModel, Field

from oncall_brain.agents.registry import ToolContext, tool
from oncall_brain.domain import update
from oncall_brain.domain.models import Highlight, ToolOutput
from oncall_brain.domain.planner import RECALL_MIN_SCORE, WINDOW
from oncall_brain.domain.verdict import CheckFacts, judge


def _path_edges(path: list[str], rel: str = "DEPENDS_ON") -> list[tuple[str, str, str]]:
    return [(a, b, rel) for a, b in zip(path, path[1:], strict=False)]


def _head(ctx: ToolContext, incident_id: str) -> tuple[dict, list]:
    q = ctx.repo.read("incident_head", incident_id=incident_id)
    if not q.rows:
        raise ValueError(f"unknown incident {incident_id!r}")
    return q.rows[0], [q]


class AlertArgs(BaseModel):
    alert_id: str = Field(description="Alert id, e.g. alert:checkout-latency")


class IncidentArgs(BaseModel):
    incident_id: str = Field(description="Incident id, e.g. inc:checkout-latency")


class ServiceArgs(BaseModel):
    service: str = Field(description="Service id, e.g. svc:checkout")
    incident_id: str | None = Field(None, description="If set: use the incident's alert time and write to it")
    at: int | None = Field(None, description="Epoch seconds; defaults to the incident's alert time, else now")


class HypothesisArgs(BaseModel):
    hypothesis_id: str


class PathArgs(BaseModel):
    from_service: str
    to_service: str
    at: int | None = Field(None, description="Epoch seconds; defaults to now")


class ResolveArgs(BaseModel):
    incident_id: str
    change_id: str = Field(description="The change a human confirmed as root cause")


class AtArgs(BaseModel):
    at: int | None = Field(None, description="Epoch seconds; defaults to now")


def incident_id_for(alert_id: str) -> str:
    return "inc:" + alert_id.split(":", 1)[-1]


@tool(writes=True)
def open_incident(ctx: ToolContext, a: AlertArgs) -> ToolOutput:
    """Open the incident for an alert (idempotent). The incident node is the board all agents share."""
    q = ctx.repo.write("open_incident", alert_id=a.alert_id, incident_id=incident_id_for(a.alert_id))
    if not q.rows:
        raise ValueError(f"unknown alert {a.alert_id!r}")
    r = q.rows[0]
    return ToolOutput(summary=f"Opened {r['incident']} for '{r['alert']}' on {r['service']}", data=r,
                      queries=[q], highlight=Highlight(nodes=[r["service"]]))


def _resolve_time(ctx: ToolContext, incident_id: str | None, at: int | None) -> tuple[int, dict | None, list]:
    if incident_id:
        head, qs = _head(ctx, incident_id)
        return head["at"], head, qs
    return at or int(time.time()), None, []


@tool(writes=True)
def blast_radius(ctx: ToolContext, a: ServiceArgs) -> ToolOutput:
    """Every service that depends on `service`, directly or transitively, via dependencies live at that time.
    With an incident, records them on the board as impacted."""
    at, head, qs = _resolve_time(ctx, a.incident_id, a.at)
    q = ctx.repo.read("blast_radius", service=a.service, at=at)
    qs.append(q)
    rows = q.rows
    if head:
        qs.append(ctx.repo.write("record_impacts", incident_id=a.incident_id, via=a.service,
                                 rows=[{"service": r["service"], "hops": r["hops"]} for r in rows]))
    hl = Highlight(nodes=[a.service] + [r["service"] for r in rows])
    for r in rows:
        hl.edges += _path_edges(r["path"])
    tier1 = [r["service"] for r in rows if r["tier"] == 1]
    return ToolOutput(summary=f"{len(rows)} services depend on {a.service} ({len(tier1)} tier-1)",
                      data=rows, queries=qs, highlight=hl)


@tool(writes=True)
def page_on_call(ctx: ToolContext, a: ServiceArgs) -> ToolOutput:
    """Find who is on call for the team owning `service` (rotation in the graph) and, with an incident, page them."""
    at, head, qs = _resolve_time(ctx, a.incident_id, a.at)
    q = ctx.repo.read("on_call_for", service=a.service, at=at)
    qs.append(q)
    if not q.rows:
        return ToolOutput(summary=f"Nobody on call for {a.service}", data=[], queries=qs)
    r = q.rows[0]
    summary = f"Paged {r['name']} ({r['handle']}, {r['team_name']}) for {a.service}"
    if head:
        pq = ctx.repo.write("record_page", incident_id=a.incident_id, person=r["person"], at=at, service=a.service)
        qs.append(pq)
        if pq.rows and pq.rows[0]["first_for"] != a.service:  # same person already engaged for another service
            summary = f"{r['name']} ({r['handle']}, {r['team_name']}) owns {a.service} too; already engaged"
    return ToolOutput(summary=summary, data=r,
                      queries=qs, highlight=Highlight(nodes=[a.service, r["team"], r["person"]],
                                                      edges=[(r["team"], a.service, "OWNS"),
                                                             (r["person"], r["team"], "ON_CALL")]))


@tool(writes=True)
def recall_similar(ctx: ToolContext, a: IncidentArgs) -> ToolOutput:
    """Episodic memory: resolved incidents whose root-cause service sits on this alert's live dependency path."""
    q = ctx.repo.read("recall_similar", incident_id=a.incident_id)
    qs = [q]
    if q.rows:
        qs.append(ctx.repo.write("record_recalls", incident_id=a.incident_id, rows=q.rows))
    strong = [r for r in q.rows if r["score"] >= RECALL_MIN_SCORE]
    summary = (f"Recalled {strong[0]['incident']} '{strong[0]['title']}' (cause on {strong[0]['cause_service']})"
               if strong else f"{len(q.rows)} past incidents touch this path, none with the same symptom")
    hl = Highlight(nodes=[r["incident"] for r in q.rows] + [r["cause_service"] for r in q.rows],
                   edges=[(a.incident_id, r["incident"], "RECALLS") for r in q.rows])
    return ToolOutput(summary=summary, data=q.rows, queries=qs, highlight=hl)


def _add(ctx: ToolContext, incident_id: str, rows: list[dict], source: str, at: int):
    hyp = [{"id": f"hyp:{incident_id.removeprefix('inc:')}:{r['change'].removeprefix('chg:')}",
            "change": r["change"], "source": source, "hops": r.get("hops")} for r in rows]
    return ctx.repo.write("add_hypotheses", incident_id=incident_id, rows=hyp, at=at)


@tool(writes=True)
def hypothesize_from_memory(ctx: ToolContext, a: IncidentArgs) -> ToolOutput:
    """Procedural memory: suspect recent changes on the services that caused the recalled incidents."""
    head, qs = _head(ctx, a.incident_id)
    q = ctx.repo.read("memory_suspects", incident_id=a.incident_id, window=WINDOW, min_score=RECALL_MIN_SCORE)
    qs.append(q)
    if q.rows:
        qs.append(_add(ctx, a.incident_id, q.rows, "memory", head["at"]))
    hl = Highlight(nodes=[r["change"] for r in q.rows] + [r["service"] for r in q.rows],
                   edges=[(r["change"], r["service"], "CHANGED") for r in q.rows])
    summary = (f"Memory points at {', '.join(r['change'] for r in q.rows)}" if q.rows
               else "Memory's culprit services had no change in this window")
    return ToolOutput(summary=summary, data=q.rows, queries=qs, highlight=hl)


@tool(writes=True)
def propose_hypotheses(ctx: ToolContext, a: IncidentArgs) -> ToolOutput:
    """Multi-hop suspects: changes in the alert window on every service the alerting service depends on,
    plus the newest changes anywhere (the flat-log baseline) so the graph can refute them."""
    head, qs = _head(ctx, a.incident_id)
    on_path = ctx.repo.read("path_suspects", incident_id=a.incident_id, window=WINDOW)
    flat = ctx.repo.read("recent_changes", incident_id=a.incident_id, window=WINDOW)
    seen = {r["change"] for r in on_path.rows}
    baseline = [r for r in flat.rows if r["change"] not in seen]
    rows = [dict(r, source="dependency-path") for r in on_path.rows] + [dict(r, source="recent-anywhere", hops=None)
                                                                       for r in baseline]
    qs += [on_path, flat]
    added = [_add(ctx, a.incident_id, [r for r in rows if r["source"] == s], s, head["at"])
             for s in ("dependency-path", "recent-anywhere") if any(r["source"] == s for r in rows)]
    qs += added
    hl = Highlight(nodes=[r["change"] for r in rows] + [r["service"] for r in rows],
                   edges=[(r["change"], r["service"], "CHANGED") for r in rows])
    return ToolOutput(summary=f"{len(on_path.rows)} changes on the dependency path, {len(baseline)} more from the "
                      f"flat change log (newest anywhere: {flat.rows[0]['change'] if flat.rows else 'none'})",
                      data={"suspects": rows, "baseline_pick": flat.rows[0] if flat.rows else None},
                      queries=qs, highlight=hl)


@tool(writes=True)
def check_hypothesis(ctx: ToolContext, a: HypothesisArgs) -> ToolOutput:
    """Test one suspect against the graph: live dependency path from the alerting service (temporal edges),
    rollback before the alert, and whether the anomaly propagated along that path. Records SUPPORTS/REFUTES."""
    fq = ctx.repo.read("hypothesis_facts", hypothesis_id=a.hypothesis_id)
    if not fq.rows:
        raise ValueError(f"unknown hypothesis {a.hypothesis_id!r}")
    f = fq.rows[0]
    qs = [fq]
    live = ctx.repo.read("live_paths", origin=f["origin"], target=f["service"], at=f["at"])
    qs.append(live)
    paths = [r["path"] for r in live.rows]
    any_path: list[str] = []
    if not paths:
        anyq = ctx.repo.read("any_path", origin=f["origin"], target=f["service"])
        qs.append(anyq)
        any_path = anyq.rows[0]["path"] if anyq.rows else []
    anomalous: set[str] = set()
    if paths or any_path:
        on_paths = sorted({s for p in paths for s in p}) or [f["service"]]
        an = ctx.repo.read("anomalies_between", services=on_paths, since=f["change_at"], until=f["at"])
        qs.append(an)
        anomalous = {r["service"] for r in an.rows}
    # The symptom may have travelled any live path; judge the one it lit up most (shortest on ties).
    live_path = min(paths, key=lambda p: (sum(s not in anomalous for s in p[1:-1]), len(p))) if paths else []
    facts = CheckFacts(
        change_service=f["service"], alert_service=f["origin"],
        rolled_back_before_alert=bool(f["rolled_back_at"]) and f["rolled_back_at"] <= f["at"],
        live_path=live_path, any_path=any_path, anomalous=anomalous)
    v = judge(facts)
    qs.append(ctx.repo.write("record_evidence", hypothesis_id=a.hypothesis_id,
                             evidence_id="ev:" + a.hypothesis_id.removeprefix("hyp:"), verdict=v.verdict,
                             reason=v.reason, path=live_path or any_path, at=f["at"]))
    shown = live_path or any_path
    hl = Highlight(nodes=shown + [f["change"]], edges=_path_edges(shown) + [(f["change"], f["service"], "CHANGED")])
    return ToolOutput(summary=f"{v.verdict.upper()} {f['change']}: {v.reason}",
                      data={"change": f["change"], "service": f["service"], "summary": f["summary"],
                            "verdict": v.verdict, "reason": v.reason, "live_path": live_path,
                            "retired_path": any_path},
                      queries=qs, highlight=hl)


@tool(writes=True)
def post_update(ctx: ToolContext, a: IncidentArgs) -> ToolOutput:
    """Write the status update (impact, cause, ruled-out suspects, who was paged, runbook, sources) and
    link it to every node it cites."""
    head, qs = _head(ctx, a.incident_id)
    facts_q = ctx.repo.read("update_facts", incident_id=a.incident_id)
    ref_q = ctx.repo.read("refuted_hypotheses", incident_id=a.incident_id)
    qs += [facts_q, ref_q]
    facts = facts_q.rows[0]
    text = update.status_update(facts, ref_q.rows, head["service"])
    cites = [c for c in [facts["change"], *facts["sources"], *(r["id"] for r in facts["runbooks"])] if c]
    qs.append(ctx.repo.write("post_update", incident_id=a.incident_id, message_id=f"msg:update:{a.incident_id}",
                             text=text, at=head["at"], cites=cites))
    return ToolOutput(summary="Posted status update to #incidents", data={"text": text, "cites": cites},
                      queries=qs, highlight=Highlight(nodes=cites))


@tool(writes=True)
def resolve_incident(ctx: ToolContext, a: ResolveArgs) -> ToolOutput:
    """Human-confirmed fix: mark the cause, resolve the incident and learn (or reinforce) a runbook for that
    service and change kind. This is what the next incident will recall."""
    head, qs = _head(ctx, a.incident_id)
    cq = ctx.repo.read("change_info", change_id=a.change_id)
    qs.append(cq)
    if not cq.rows:
        raise ValueError(f"unknown change {a.change_id!r}")
    c = cq.rows[0]
    rb_id, title, steps = update.learned_runbook(c["service_name"], c["kind"], c["summary"], head["service"])
    q = ctx.repo.write("resolve_incident", incident_id=a.incident_id, change_id=a.change_id, at=head["at"] + 3600,
                       runbook_id=rb_id, title=title, steps=steps)
    qs.append(q)
    if not q.rows:
        return ToolOutput(summary=f"{a.incident_id} was already resolved", data=None, queries=qs)
    r = q.rows[0]
    return ToolOutput(summary=f"Resolved {a.incident_id}; runbook '{r['title']}' now has {r['successes']} success(es)",
                      data=r, queries=qs,
                      highlight=Highlight(nodes=[a.incident_id, a.change_id, r["runbook"]],
                                          edges=[(a.incident_id, a.change_id, "CAUSED_BY"),
                                                 (a.incident_id, r["runbook"], "FIXED_WITH")]))


@tool()
def dependency_path(ctx: ToolContext, a: PathArgs) -> ToolOutput:
    """Shortest dependency path between two services using only edges valid at time `at`."""
    at = a.at or int(time.time())
    q = ctx.repo.read("live_path", origin=a.from_service, target=a.to_service, at=at)
    path = q.rows[0]["path"] if q.rows else []
    return ToolOutput(summary=" -> ".join(path) if path else f"no live path {a.from_service} -> {a.to_service}",
                      data=path, queries=[q], highlight=Highlight(nodes=path, edges=_path_edges(path)))


@tool()
def incident_board(ctx: ToolContext, a: IncidentArgs) -> ToolOutput:
    """The incident's shared state: steps taken by each agent, hypotheses and their status, recalled memory."""
    from oncall_brain.services.board import load_board

    board, q = load_board(ctx.repo, a.incident_id)
    return ToolOutput(summary=f"{len(board['steps'])} steps, {len(board['hypotheses'])} hypotheses", data=board,
                      queries=[q])


class ChangeArgs(BaseModel):
    change_id: str = Field(description="Change id, e.g. chg:pgw-pool-1")


class ServiceIdArgs(BaseModel):
    service: str = Field(description="Service id, e.g. svc:payments-gw")


@tool()
def who_knows(ctx: ToolContext, a: ServiceIdArgs) -> ToolOutput:
    """Company brain: who knows this service, ranked by evidence in the graph (owning team, changes they
    authored, incidents they were paged for), with the evidence counts as the explanation."""
    q = ctx.repo.read("who_knows", service=a.service)
    hl = Highlight(nodes=[a.service] + [r["person"] for r in q.rows])
    top = q.rows[0] if q.rows else None
    summary = (f"{top['name']} ({top['team']}): {top['changes']} changes, {top['incidents']} incidents"
               + (", on the owning team" if top["on_owning_team"] else "")) if top else "nobody on record"
    return ToolOutput(summary=summary, data=q.rows, queries=[q], highlight=hl)


@tool()
def change_story(ctx: ToolContext, a: ChangeArgs) -> ToolOutput:
    """Company brain: trace a change to its sources (ticket, chat), its author and team, and the incidents
    it caused."""
    q = ctx.repo.read("change_story", change_id=a.change_id)
    if not q.rows:
        raise ValueError(f"unknown change {a.change_id!r}")
    r = dict(q.rows[0])
    r["sources"] = [s for s in r["sources"] if s.get("id")]
    nodes = [a.change_id, r["service"], *(s["id"] for s in r["sources"]), *r["incidents"]]
    edges = [(a.change_id, r["service"], "CHANGED"), *((s["id"], a.change_id, "SOURCE") for s in r["sources"]),
             *((i, a.change_id, "CAUSED_BY") for i in r["incidents"])]
    return ToolOutput(summary=f"{r['summary']} by {r['author']} ({r['team']}); {len(r['sources'])} sources, "
                      f"caused {len(r['incidents'])} incident(s)", data=r, queries=[q],
                      highlight=Highlight(nodes=nodes, edges=edges))


@tool()
def service_map(ctx: ToolContext, a: AtArgs) -> ToolOutput:
    """All services with owners and dependency edges (live or retired at `at`)."""
    q = ctx.repo.read("service_map", at=a.at or int(time.time()))
    return ToolOutput(summary=f"{len(q.rows)} services", data=q.rows, queries=[q])
