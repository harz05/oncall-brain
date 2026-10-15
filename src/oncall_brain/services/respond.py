"""Use cases: respond to an alert (triage -> investigator -> comms, handing off through the graph) and
resolve an incident (the human-confirmed fix that becomes memory)."""

from typing import Any

from oncall_brain.agents import registry
from oncall_brain.agents.loop import record, run_role
from oncall_brain.agents.registry import ToolContext
from oncall_brain.domain.models import Highlight, TraceStep
from oncall_brain.domain.planner import WINDOW
from oncall_brain.ports import GraphRepository, LLMProvider

# Importing the module registers the tools.
from oncall_brain.services import tools as _tools  # noqa: F401


def respond(repo: GraphRepository, alert_id: str, llm: LLMProvider) -> dict[str, Any]:
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


def resolve(repo: GraphRepository, incident_id: str, change_id: str) -> dict[str, Any]:
    out = registry.call("resolve_incident", ToolContext(repo),
                        {"incident_id": incident_id, "change_id": change_id})
    return out.model_dump()


def _data(trace: list[TraceStep], tool: str, role: str | None = None) -> list[Any]:
    return [s.data for s in trace if s.tool == tool and (role is None or s.role == role) and s.data]


def outcome(repo: GraphRepository, incident_id: str, trace: list[TraceStep]) -> dict[str, Any]:
    checks = _data(trace, "check_hypothesis")
    supported = [c for c in checks if c["verdict"] == "supports"]
    baseline = repo.read("recent_changes", incident_id=incident_id, window=WINDOW).rows
    investigator = [s for s in trace if s.role == "investigator" and s.tool != "handoff"]
    recalls = (_data(trace, "recall_similar") or [[]])[0]
    memory = _data(trace, "hypothesize_from_memory")
    blast = (_data(trace, "blast_radius", "triage") or [[]])[0]
    at_risk_rows = (_data(trace, "blast_radius", "comms") or [[]])[0]
    direct = {r["service"] for r in blast}
    updates = _data(trace, "post_update")
    highlight = Highlight()
    for s in trace:
        if s.tool in ("check_hypothesis",) and s.data and s.data["verdict"] == "supports":
            highlight = highlight.merge(s.highlight)
    return {
        "root_cause": supported[0] if supported else None,
        "refuted": [c for c in checks if c["verdict"] != "supports"],
        "baseline_pick": baseline[0] if baseline else None,
        "baseline_correct": bool(supported and baseline and baseline[0]["change"] == supported[0]["change"]),
        "memory": {"recalled": [r for r in recalls if r["score"] >= 3],
                   "suspects": memory[0] if memory else [],
                   "solved_by_memory": bool(supported and memory and any(
                       m["change"] == supported[0]["change"] for m in memory[0]))},
        "paged": _data(trace, "page_on_call"),
        "blast_radius": sorted(direct),
        "at_risk": sorted({r["service"] for r in at_risk_rows} - direct),
        "update_text": updates[0]["text"] if updates else None,
        "investigator_calls": len(investigator),
        "hypotheses_checked": len(checks),
        "highlight": highlight,
    }
