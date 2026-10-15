"""Use cases: respond to an alert (triage -> investigator -> comms, handing off through the graph) and
resolve an incident (the human-confirmed fix that becomes memory)."""

from typing import Any

from oncall_brain.agents import registry
from oncall_brain.agents.loop import record, run_role
from oncall_brain.agents.registry import ToolContext
from oncall_brain.domain.models import ToolOutput, TraceStep
from oncall_brain.domain.planner import RECALL_MIN_SCORE, WINDOW
from oncall_brain.ports import GraphRepository, LLMProvider

# Importing the module registers the tools.
from oncall_brain.services import tools as _tools  # noqa: F401


def respond(repo: GraphRepository, alert_id: str, llm: LLMProvider) -> dict[str, Any]:
    with repo.lock():  # one agent run per tenant at a time (see FalkorRepository.lock)
        return _respond(repo, alert_id, llm)


def _respond(repo: GraphRepository, alert_id: str, llm: LLMProvider) -> dict[str, Any]:
    trace: list[TraceStep] = []
    out = registry.call("open_incident", ToolContext(repo), {"alert_id": alert_id})
    incident_id = out.data["incident"]
    record(repo, incident_id, trace,
           TraceStep(seq=1, role="triage", tool="open_incident", reason="An alert fired; open the shared board.",
                     summary=out.summary, writes=True, queries=out.queries, highlight=out.highlight,
                     data=out.data), alert_id)
    role: str | None = "triage"
    while role:
        role = run_role(role, repo, incident_id, llm, trace)
    return {"incident_id": incident_id, "alert": out.data, "planner": llm.name, "steps": trace,
            "outcome": outcome(repo, incident_id, trace)}


def run_tool(repo: GraphRepository, name: str, args: dict[str, Any]) -> ToolOutput:
    """One tool call from outside an agent run (HTTP /tools, MCP). Write tools take the tenant lock so they
    cannot race an agent run; inside respond() the lock is already held, so the loop calls the registry directly."""
    if name in registry.REGISTRY and registry.REGISTRY[name].writes:
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
    """The result card. Cause, ruled-out suspects and the update come from the graph (so a re-run of a finished
    incident still shows them); counters and memory come from this run's trace."""
    opened = trace[0].data  # respond() always opens the incident first
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
    return {
        "root_cause": cause,
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
        "at_risk": sorted({x["service"] for x in impacts} - direct),
        "co_causes": repo.read("co_causes", incident_id=incident_id).rows,
        "update_text": update,
        "investigator_calls": len(investigator),
        "hypotheses_checked": len(checks),
        "checks_to_culprit": next((i + 1 for i, c in enumerate(checks) if cause and c["change"] == cause["change"]),
                                  None),
        "runbook": posted[0]["runbook"] if posted else None,
        "expert": posted[0]["expert"] if posted else None,
        "storm": storm,
    }
