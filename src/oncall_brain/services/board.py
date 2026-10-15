"""Reads the incident board (the agents' shared state) out of the graph."""

from typing import Any

from oncall_brain.domain.models import QueryRun
from oncall_brain.domain.planner import STORM_WINDOW
from oncall_brain.ports import GraphRepository


def load_board(repo: GraphRepository, incident_id: str) -> tuple[dict[str, Any], QueryRun]:
    q = repo.read("incident_board", incident_id=incident_id, storm_window=STORM_WINDOW)
    if not q.rows:
        raise ValueError(f"unknown incident {incident_id!r}")
    r = q.rows[0]
    # OPTIONAL MATCH + collect() yields maps of nulls when nothing matched; drop those.
    hyps = [h for h in r["hypotheses"] if h["id"]]
    board = {
        "incident": {k: r[k] for k in ("id", "status", "service", "alert", "at", "symptom")},
        "steps": [s for s in r["steps"] if s["tool"]],
        "hypotheses": hyps,
        "recalls": [x for x in r["recalls"] if x["incident"]],
        "cause_service": next((h["service"] for h in hyps if h["status"] in ("confirmed", "supported")), None),
        "storm": r["storm"],  # other alerts in the storm window
        "shared_upstream": r["shared_upstream"],  # set by correlate_alerts, convergence order (fewest total hops first)
    }
    return board, q
