"""The graph tools. Each one runs named Cypher through the GraphRepository port and returns a ToolOutput
(summary, data, the queries it ran, and the graph ids to highlight). Registered once in agents.registry."""

import time
from typing import Literal

from pydantic import BaseModel, Field

from oncall_brain.agents.registry import ToolContext, tool
from oncall_brain.domain import update
from oncall_brain.domain.models import Highlight, ToolOutput
from oncall_brain.domain.planner import RECALL_MIN_SCORE, STORM_WINDOW, WINDOW
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
def correlate_alerts(ctx: ToolContext, a: IncidentArgs) -> ToolOutput:
    """Alert storm: fold other alerts from the last 15 minutes into this incident, find the services every
    alerting service depends on (shared upstream), and rank them with betweenness centrality (algo.betweenness:
    where dependency paths converge). Investigators then check suspects there first, and a suspect that cannot
    reach every alerting service is refuted."""
    head, qs = _head(ctx, a.incident_id)
    storm = ctx.repo.read("storm_alerts", incident_id=a.incident_id, window=STORM_WINDOW)
    qs.append(storm)
    if not storm.rows:
        return ToolOutput(summary="No other alerts in the storm window", data={"alerts": [], "shared": []},
                          queries=qs)
    services = sorted({head["service"], *(r["service"] for r in storm.rows)})
    shared_q = ctx.repo.read("shared_upstream", services=services, at=head["at"])
    qs.append(shared_q)
    shared_ids = [r["service"] for r in shared_q.rows]
    ranked: list[dict] = []
    if shared_ids:
        cq = ctx.repo.read("chokepoints", services=shared_ids)
        qs.append(cq)
        ranked = [{"service": r["service"], "score": r["score"], "rank": i + 1} for i, r in enumerate(cq.rows)]
    qs.append(ctx.repo.write("record_correlation", incident_id=a.incident_id, origin=head["service"],
                             alerts=[{"alert": r["alert"], "service": r["service"]} for r in storm.rows],
                             shared=ranked))
    names = ", ".join(r["service"].removeprefix("svc:") for r in storm.rows)
    top = ranked[0]["service"].removeprefix("svc:") if ranked else None
    summary = (f"{len(storm.rows) + 1} alerts ({names} too) share {len(ranked)} upstream services; "
               f"paths converge on {top}" if ranked else f"{len(storm.rows) + 1} alerts share no upstream service")
    hl = Highlight(nodes=services + [r["service"] for r in ranked],
                   edges=[(a.incident_id, r["alert"], "CORRELATED_WITH") for r in storm.rows])
    return ToolOutput(summary=summary, data={"alerts": storm.rows, "shared": ranked}, queries=qs, highlight=hl)


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
    hl = Highlight(nodes=[r["incident"] for r in strong] + [r["cause_service"] for r in strong],
                   edges=[(a.incident_id, r["incident"], "RECALLS") for r in strong])
    return ToolOutput(summary=summary, data=q.rows, queries=qs, highlight=hl)


def _add(ctx: ToolContext, incident_id: str, rows: list[dict], at: int):
    """Put suspects on the board; each row carries its source (and, for memory, the runbook behind it)."""
    hyp = [{"id": f"hyp:{incident_id.removeprefix('inc:')}:{r['change'].removeprefix('chg:')}",
            "change": r["change"], "source": r["source"], "hops": r.get("hops"), "runbook": r.get("runbook")}
           for r in rows]
    return ctx.repo.write("add_hypotheses", incident_id=incident_id, rows=hyp, at=at)


def _window(at: int) -> dict[str, int]:
    return {"since": at - WINDOW, "until": at}


@tool(writes=True)
def hypothesize_from_memory(ctx: ToolContext, a: IncidentArgs) -> ToolOutput:
    """Procedural memory: the runbooks that fixed the recalled incidents name a service and a change kind;
    suspect in-window changes of that kind there, most trusted runbook first."""
    head, qs = _head(ctx, a.incident_id)
    q = ctx.repo.read("memory_suspects", incident_id=a.incident_id, window=WINDOW, min_score=RECALL_MIN_SCORE)
    qs.append(q)
    rows = [dict(r, source="memory") for r in q.rows]
    if rows:
        qs.append(_add(ctx, a.incident_id, rows, head["at"]))
    hl = Highlight(nodes=[r["change"] for r in rows] + [r["service"] for r in rows],
                   edges=[(r["change"], r["service"], "CHANGED") for r in rows])
    summary = ("Runbook " + "; ".join(f"'{r['runbook_title']}' (worked {r['successes']}/{r['uses']}) points at "
                                      f"{r['change']}" for r in rows) if rows
               else "The recalled runbooks' services had no change of their kind in this window")
    return ToolOutput(summary=summary, data=q.rows, queries=qs, highlight=hl)


@tool(writes=True)
def propose_hypotheses(ctx: ToolContext, a: IncidentArgs) -> ToolOutput:
    """Multi-hop suspects: changes in the alert window on every service the alerting service depends on,
    plus the newest changes anywhere (the flat-log baseline) so the graph can refute them."""
    head, qs = _head(ctx, a.incident_id)
    on_path = ctx.repo.read("path_suspects", incident_id=a.incident_id, window=WINDOW)
    flat = ctx.repo.read("recent_changes", **_window(head["at"]))
    seen = {r["change"] for r in on_path.rows}
    baseline = [r for r in flat.rows if r["change"] not in seen]
    rows = [dict(r, source="dependency-path") for r in on_path.rows] + [dict(r, source="recent-anywhere", hops=None)
                                                                       for r in baseline]
    qs += [on_path, flat]
    if rows:
        qs.append(_add(ctx, a.incident_id, rows, head["at"]))
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
    if paths:  # anomalies only matter when a live path exists; otherwise the verdict is already a refutation
        on_paths = sorted({s for p in paths for s in p}) or [f["service"]]
        an = ctx.repo.read("anomalies_between", services=on_paths, since=f["change_at"], until=f["at"])
        qs.append(an)
        anomalous = {r["service"] for r in an.rows}
    # The symptom may have travelled any live path; judge the one it lit up most (shortest on ties).
    live_path = min(paths, key=lambda p: (sum(s not in anomalous for s in p[1:-1]), len(p))) if paths else []
    unexplained: list[str] = []
    others = [x for x in f["storm_services"] if x != f["origin"]]
    if paths and others:  # alert storm: one cause has to explain every correlated alert
        sq = ctx.repo.read("storm_unexplained", services=others, target=f["service"], at=f["at"])
        qs.append(sq)
        unexplained = [r["service"] for r in sq.rows]
    facts = CheckFacts(
        change_service=f["service"], alert_service=f["origin"],
        rolled_back_before_alert=bool(f["rolled_back_at"]) and f["rolled_back_at"] <= f["at"],
        live_path=live_path, any_path=any_path, anomalous=anomalous, storm_unexplained=tuple(unexplained))
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
    experts = [x for x in facts["experts"] if x.get("id")]
    runbooks = [r for r in facts["runbooks"] if r.get("id")]
    cites = [c for c in [facts["change"], *facts["sources"], *(r["id"] for r in runbooks),
                         *(x["id"] for x in experts)] if c]
    qs.append(ctx.repo.write("post_update", incident_id=a.incident_id, message_id=f"msg:update:{a.incident_id}",
                             text=text, at=head["at"], cites=cites))
    return ToolOutput(summary="Posted status update to #incidents",
                      data={"text": text, "cites": cites, "runbook": runbooks[0] if runbooks else None,
                            "expert": experts[0] if experts else None},
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
    q = ctx.repo.read("live_paths", origin=a.from_service, target=a.to_service, at=at)
    path = q.rows[0]["path"] if q.rows else []  # shortest first
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


class ExpertArgs(BaseModel):
    service: str = Field(description="Service id, e.g. svc:payments-gw")
    incident_id: str | None = Field(None, description="If set: record the top expert as CONSULTED on the incident")


@tool()
def who_knows(ctx: ToolContext, a: ExpertArgs) -> ToolOutput:
    """Company brain: who knows this service, ranked by evidence in the graph (owning team, changes they
    authored, incidents they were paged for), with the evidence counts as the explanation. With an incident,
    the top person is recorded as CONSULTED so the status update can say who to ask."""
    q = ctx.repo.read("who_knows", service=a.service)
    qs = [q]
    hl = Highlight(nodes=[a.service] + [r["person"] for r in q.rows])
    top = q.rows[0] if q.rows else None
    if top and a.incident_id:
        qs.append(ctx.repo.write("record_consult", incident_id=a.incident_id, person=top["person"],
                                 service=a.service, score=top["score"]))
    summary = (f"{top['name']} ({top['team']}): {top['changes']} changes, {top['incidents']} incidents"
               + (", on the owning team" if top["on_owning_team"] else "")) if top else "nobody on record"
    return ToolOutput(summary=summary, data=q.rows, queries=qs, highlight=hl)


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
    edges = [(a.change_id, r["service"], "CHANGED"),
             *((s["id"], a.change_id, "REQUESTED" if s["kind"] == "Ticket" else "MENTIONS") for s in r["sources"]),
             *((i, a.change_id, "CAUSED_BY") for i in r["incidents"])]
    return ToolOutput(summary=f"{r['summary']} by {r['author']} ({r['team']}); {len(r['sources'])} sources, "
                      f"caused {len(r['incidents'])} incident(s)", data=r, queries=[q],
                      highlight=Highlight(nodes=nodes, edges=edges))


@tool()
def service_map(ctx: ToolContext, a: AtArgs) -> ToolOutput:
    """All services with owners and dependency edges (live or retired at `at`)."""
    q = ctx.repo.read("service_map", at=a.at or int(time.time()))
    return ToolOutput(summary=f"{len(q.rows)} services", data=q.rows, queries=[q])


# --- Keeping knowledge current: events any client (MCP, HTTP) can push into the graph -------------------

SVC = r"^svc:[a-z0-9-]{1,60}$"
SYMPTOM = Literal["latency", "errors", "saturation"]


class ChangeEvent(BaseModel):
    service: str = Field(pattern=SVC)
    kind: Literal["deploy", "config"]
    summary: str = Field(max_length=300)
    at: int | None = Field(None, description="Epoch seconds; defaults to now")
    author: str | None = Field(None, pattern=r"^person:[a-z0-9.-]{1,80}$")
    rolled_back_at: int | None = None
    id: str | None = Field(None, pattern=r"^chg:[\w.-]{1,80}$")


class AnomalyEvent(BaseModel):
    service: str = Field(pattern=SVC)
    kind: SYMPTOM
    summary: str = Field(max_length=300)
    at: int | None = None


class AlertEvent(BaseModel):
    service: str = Field(pattern=SVC)
    symptom: SYMPTOM
    name: str = Field(max_length=200)
    at: int | None = None


class DependencyEvent(BaseModel):
    caller: str = Field(pattern=SVC)
    callee: str = Field(pattern=SVC)
    at: int | None = None


def _name(service: str) -> str:
    return service.removeprefix("svc:")


@tool(writes=True)
def record_change(ctx: ToolContext, a: ChangeEvent) -> ToolOutput:
    """Record a deploy or config change on a service (from CI/CD or a human). Investigations see it at once."""
    at = a.at or int(time.time())
    cid = a.id or f"chg:{_name(a.service)}-{at}"
    q = ctx.repo.write("record_change", id=cid, service=a.service, kind=a.kind, summary=a.summary, at=at,
                       rolled_back_at=a.rolled_back_at, author=a.author)
    if not q.rows:
        raise ValueError(f"unknown service {a.service!r}")
    return ToolOutput(summary=f"Recorded {a.kind} {cid} on {a.service}", data={"change": cid, "at": at}, queries=[q],
                      highlight=Highlight(nodes=[cid, a.service], edges=[(cid, a.service, "CHANGED")]))


@tool(writes=True)
def record_anomaly(ctx: ToolContext, a: AnomalyEvent) -> ToolOutput:
    """Record a monitoring anomaly (latency, errors, saturation) on a service."""
    at = a.at or int(time.time())
    aid = f"anom:{_name(a.service)}-{a.kind}-{at}"
    q = ctx.repo.write("record_anomaly", id=aid, service=a.service, kind=a.kind, summary=a.summary, at=at)
    if not q.rows:
        raise ValueError(f"unknown service {a.service!r}")
    return ToolOutput(summary=f"Recorded {a.kind} anomaly on {a.service}", data={"anomaly": aid, "at": at},
                      queries=[q], highlight=Highlight(nodes=[a.service]))


@tool(writes=True)
def raise_alert(ctx: ToolContext, a: AlertEvent) -> ToolOutput:
    """Record an alert on a service. Respond to it with respond_to_alert (MCP) or POST .../alerts/{id}/respond."""
    at = a.at or int(time.time())
    aid = f"alert:{_name(a.service)}-{a.symptom}-{at}"
    q = ctx.repo.write("raise_alert", id=aid, service=a.service, alert_name=a.name, symptom=a.symptom, at=at)
    if not q.rows:
        raise ValueError(f"unknown service {a.service!r}")
    data = {"alert": aid, "incident": incident_id_for(aid), "at": at}
    return ToolOutput(summary=f"Alert {aid} raised on {a.service}", data=data, queries=[q],
                      highlight=Highlight(nodes=[a.service]))


@tool(writes=True)
def add_dependency(ctx: ToolContext, a: DependencyEvent) -> ToolOutput:
    """Record that `caller` starts depending on `callee` (a new DEPENDS_ON edge valid from `at`)."""
    at = a.at or int(time.time())
    q = ctx.repo.write("add_dependency", caller=a.caller, callee=a.callee, at=at)
    if not q.rows:
        raise ValueError(f"unknown service {a.caller!r} or {a.callee!r}")
    return ToolOutput(summary=f"{a.caller} depends on {a.callee} from {at}", data=q.rows[0], queries=[q],
                      highlight=Highlight(nodes=[a.caller, a.callee], edges=[(a.caller, a.callee, "DEPENDS_ON")]))


@tool(writes=True)
def retire_dependency(ctx: ToolContext, a: DependencyEvent) -> ToolOutput:
    """Record that `caller` stopped depending on `callee` at `at`. History stays; later investigations
    no longer follow that edge (and say so when they refute a suspect behind it)."""
    at = a.at or int(time.time())
    q = ctx.repo.write("retire_dependency", caller=a.caller, callee=a.callee, at=at)
    n = q.rows[0]["retired"] if q.rows else 0
    return ToolOutput(summary=f"Retired {n} live dependency {a.caller} -> {a.callee} at {at}", data={"retired": n},
                      queries=[q], highlight=Highlight(nodes=[a.caller, a.callee]))
