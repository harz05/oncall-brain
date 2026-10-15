"""Use cases: respond to an alert (triage -> investigator -> comms, handing off through the graph) and
resolve an incident (the human-confirmed fix that becomes memory)."""

from typing import Any

from oncall_brain.agents import registry
from oncall_brain.agents.loop import OnStep, record, run_role
from oncall_brain.agents.registry import ToolContext
from oncall_brain.domain.models import Decision, ToolOutput, TraceStep
from oncall_brain.domain.planner import RECALL_MIN_SCORE, WINDOW, next_decision
from oncall_brain.domain.verdict import confidence
from oncall_brain.ports import GraphRepository, GraphStore, LLMProvider

# Importing the module registers the tools.
from oncall_brain.services import tools as _tools  # noqa: F401


class RunBudget:
    """Caps what one incident run may spend on the model: input + output tokens, as the provider reports them in
    `last_usage`. Past the cap every remaining decision is the deterministic planner's, and the trace says so, so a
    model that dithers cannot run up a bill or stall an incident."""

    def __init__(self, llm: LLMProvider, cap: int):
        self.llm, self.cap, self.used, self.name = llm, cap, 0, llm.name

    def decide(self, role: str, board: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        if self.used >= self.cap:
            d = next_decision(role, board)
            return d.model_copy(update={"reason": f"LLM fallback: token cap for this run ({self.cap:,}) reached. "
                                                  f"{d.reason}"})
        if hasattr(self.llm, "last_usage"):
            self.llm.last_usage = 0  # a decision that never reached the API must not re-count the previous one
        d = self.llm.decide(role, board, tools)
        self.used += int(getattr(self.llm, "last_usage", 0) or 0)
        return d


def respond(repo: GraphRepository, alert_id: str, llm: LLMProvider, on_step: OnStep | None = None) -> dict[str, Any]:
    """on_step is called with each step as it is recorded, so a caller can stream the run while it happens.
    A provider with `run_token_cap` (set by wiring from LLM_RUN_TOKEN_CAP) is budgeted per run (RunBudget)."""
    cap = int(getattr(llm, "run_token_cap", 0) or 0)
    budget = RunBudget(llm, cap) if cap else None
    with repo.lock():  # one agent run per tenant at a time (see FalkorRepository.lock)
        run = _respond(repo, alert_id, budget or llm, on_step)
    run["llm_tokens"] = budget.used if budget else 0
    return run


def _respond(repo: GraphRepository, alert_id: str, llm: LLMProvider, on_step: OnStep | None) -> dict[str, Any]:
    trace: list[TraceStep] = []
    # Another responder may already have folded this alert into its incident (an alert storm): join that incident.
    joined = (repo.read("open_incident_for_alert", alert_id=alert_id).rows or [None])[0]
    asked = alert_id
    if joined:
        alert_id = joined["trigger"]
    out = registry.call("open_incident", ToolContext(repo), {"alert_id": alert_id})
    incident_id = out.data["incident"]
    record(repo, incident_id, trace,
           TraceStep(seq=1, role="triage", tool="open_incident", reason="An alert fired; open the shared board.",
                     summary=out.summary, writes=True, queries=out.queries, highlight=out.highlight,
                     data=out.data), alert_id, on_step)
    role: str | None = "triage"
    while role:
        role = run_role(role, repo, incident_id, llm, trace, on_step)
    return {"incident_id": incident_id, "alert": out.data, "planner": llm.name, "steps": trace,
            "joined": {"alert": asked, "incident": incident_id} if joined else None,
            "outcome": outcome(repo, incident_id, trace)}


def without_memory(store: GraphStore, tenant: str, alert_id: str, llm: LLMProvider) -> dict[str, Any] | None:
    """The same incident replayed on a copy of the tenant's pristine graph, i.e. without anything the agents learned
    since seeding: the fair way to show what memory saved (same incident, same planner, memory removed)."""
    scratch = f"{tenant[:32]}_nomem"
    if not store.clone_pristine(tenant, scratch):
        return None
    try:
        o = respond(store.tenant(scratch), alert_id, llm)["outcome"]
    finally:
        store.drop(scratch)
    return {"investigator_calls": o["investigator_calls"], "hypotheses_checked": o["hypotheses_checked"],
            "checks_to_culprit": o["checks_to_culprit"], "root_cause": (o["root_cause"] or {}).get("change")}


def run_tool(repo: GraphRepository, name: str, args: dict[str, Any]) -> ToolOutput:
    """One tool call from outside an agent run (HTTP /tools, MCP). Write tools take the tenant lock so they
    cannot race an agent run; inside respond() the lock is already held, so the loop calls the registry directly."""
    tool = registry.REGISTRY.get(name)
    # Tools that write only when given an incident (blast_radius, page_on_call, who_knows) are plain reads without one.
    writes = tool and tool.writes and ("incident_id" not in tool.args_model.model_fields or args.get("incident_id"))
    if writes:
        with repo.lock():
            return registry.call(name, ToolContext(repo), args)
    return registry.call(name, ToolContext(repo), args)


def resolve(repo: GraphRepository, incident_id: str, change_id: str) -> dict[str, Any]:
    """The human's call: record the confirmed cause, learn the runbook and re-post the update (resolve_incident)."""
    with repo.lock():
        out = registry.call("resolve_incident", ToolContext(repo),
                            {"incident_id": incident_id, "change_id": change_id})
    return out.model_dump()


def _data(trace: list[TraceStep], tool: str, role: str | None = None) -> list[Any]:
    return [s.data for s in trace if s.tool == tool and (role is None or s.role == role) and s.data]


def outcome(repo: GraphRepository, incident_id: str, trace: list[TraceStep]) -> dict[str, Any]:
    """The result card. Cause, ruled-out suspects, pages, sources and the update come from the graph (so a finished
    incident shows them again after a reload, with an empty trace); counters and memory come from this run's trace."""
    # respond() always opens the incident first; a stored incident (no trace) reads the same facts from the graph.
    opened = trace[0].data if trace else repo.read("incident_head", incident_id=incident_id).rows[0]
    at = opened["at"]
    checks = _data(trace, "check_hypothesis")
    cause = (repo.read("cause_facts", incident_id=incident_id).rows or [None])[0]
    if cause:
        checked = next((c for c in reversed(checks) if c["change"] == cause["change"]), {})
        cause = {**cause, "verdict": "supports", "retired_path": [], **checked}
    refuted = [{**r, "live_path": [], "retired_path": []} for r in
               repo.read("refuted_hypotheses", incident_id=incident_id).rows]
    window = {"since": at - WINDOW, "until": at}
    flat = (repo.read("recent_changes", **window).rows or [None])[0]
    smart = (repo.read("anomaly_baseline", **window).rows or [None])[0]
    investigator = [s for s in trace if s.role == "investigator" and s.tool != "handoff"]
    recalls = (_data(trace, "recall_similar") or [[]])[0]
    memory = _data(trace, "hypothesize_from_memory")
    # Impact, pages and the storm come from the graph too (IMPACTS, PAGED, CORRELATED_WITH, SHARED_UPSTREAM).
    st = repo.read("incident_storm", incident_id=incident_id).rows[0]
    storm_alerts = [x for x in st["alerts"] if x["alert"]]
    storm = {"alerts": storm_alerts, "shared": [x for x in st["shared"] if x["service"]]} if storm_alerts else None
    alerting = {opened["service"], *(x["service"] for x in storm_alerts)}
    impacts = [x for x in repo.read("update_facts", incident_id=incident_id).rows[0]["impacts"] if x["service"]]
    direct = {x["service"] for x in impacts if x["via"] in (None, opened["service"])} | alerting
    update = (repo.read("incident_update", incident_id=incident_id).rows or [{"text": None}])[0]["text"]
    posted = _data(trace, "post_update")
    co = repo.read("co_causes", incident_id=incident_id).rows
    return {
        "root_cause": cause,
        "confidence": confidence(cause, len(alerting), len(co)),
        "refuted": refuted,
        "baseline_pick": flat,
        "baseline_correct": bool(cause and flat and flat["change"] == cause["change"]),
        "anomaly_baseline_pick": smart,
        "anomaly_baseline_correct": bool(cause and smart and smart["change"] == cause["change"]),
        "memory": {"recalled": [r for r in recalls if r["score"] >= RECALL_MIN_SCORE],
                   "suspects": memory[0] if memory else [],
                   "solved_by_memory": bool(cause and memory and any(
                       m["change"] == cause["change"] for m in memory[0]))},
        "paged": repo.read("incident_paged", incident_id=incident_id).rows,
        "blast_radius": sorted(direct),
        "at_risk": sorted({x["service"] for x in impacts} - direct - set((cause or {}).get("live_path") or [])),
        "co_causes": co,
        "update_text": update,
        "sources": repo.read("incident_sources", incident_id=incident_id).rows,
        "investigator_calls": len(investigator),
        "hypotheses_checked": len(checks),
        "checks_to_culprit": next((i + 1 for i, c in enumerate(checks) if cause and c["change"] == cause["change"]),
                                  None),
        "runbook": posted[0]["runbook"] if posted else None,
        "expert": posted[0]["expert"] if posted else None,
        "storm": storm,
    }
