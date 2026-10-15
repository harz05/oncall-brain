"""Deterministic planner: picks each role's next tool from the incident board read out of the graph.

The board is rebuilt from FalkorDB before every decision (incident_board.cypher), so the plan lives in
the graph: which tools already ran (AgentStep nodes), which hypotheses are still open, what memory was
recalled. Swap this for an LLM (adapters/llm) and the loop, tools and trace stay the same.
"""

from typing import Any

from oncall_brain.domain.models import Decision

RECALL_MIN_SCORE = 3  # cause service still on the live dependency path (2) + same symptom (1)
WINDOW = 2 * 3600  # a change counts as a suspect if it landed this many seconds before the alert
STORM_WINDOW = 15 * 60  # alerts this close together are correlated before anyone investigates


def _ran(board: dict[str, Any], tool: str, target: str | None = None) -> bool:
    return any(s["tool"] == tool and (target is None or s["target"] == target) for s in board["steps"])


def _call(tool: str, reason: str, **args: Any) -> Decision:
    return Decision(action="call", tool=tool, args=args, reason=reason)


def check_order(h: dict[str, Any], shared: list[str] = ()) -> tuple:
    """Memory-derived suspects first, then (in an alert storm) suspects on the shared upstream in convergence
    order, then the closest on the dependency path, then the most recent."""
    hops = h["hops"] if h["hops"] is not None else 99
    rank = shared.index(h["service"]) if h["service"] in shared else len(shared)
    return (h["source"] != "memory", rank, hops, -h["at"])


def triage(board: dict[str, Any]) -> Decision:
    svc = board["incident"]["service"]
    if board.get("storm") and not _ran(board, "correlate_alerts"):
        return _call("correlate_alerts", f"{board['storm']} other alert(s) fired in the last "
                     f"{STORM_WINDOW // 60} min; find what they share before investigating each one.")
    if not _ran(board, "blast_radius", svc):
        return _call("blast_radius", f"Who is hurt? Walk DEPENDS_ON backwards from {svc}.", service=svc)
    if not _ran(board, "page_on_call", svc):
        return _call("page_on_call", f"Find and page whoever is on call for {svc} right now.", service=svc)
    return Decision(action="done", reason="Impact and owner known; hand the board to the investigator.",
                    handoff_to="investigator")


def investigator(board: dict[str, Any]) -> Decision:
    hyps = board["hypotheses"]
    if not _ran(board, "recall_similar"):
        return _call("recall_similar", "Have we seen this before? Recall resolved incidents with the same shape.")
    best = max((r["score"] for r in board["recalls"]), default=0)
    if best >= RECALL_MIN_SCORE and not _ran(board, "hypothesize_from_memory"):
        return _call("hypothesize_from_memory",
                     "A past incident matches structurally; test its root cause pattern first.")
    shared = board.get("shared_upstream", [])
    open_ = sorted((h for h in hyps if h["status"] == "open"), key=lambda h: check_order(h, shared))
    if open_:
        h = open_[0]
        return _call("check_hypothesis", f"Test suspect {h['change_id']} on {h['service']} against the graph.",
                     hypothesis_id=h["id"])
    supported = [h for h in hyps if h["status"] in ("supported", "confirmed")]
    storm = board.get("correlated") or []
    if (supported and storm and not _ran(board, "propose_hypotheses")
            and max(len(h.get("explained") or []) for h in supported) < len(storm)):
        return _call("propose_hypotheses", "Memory explains only part of the alert storm; list every suspect on the "
                     "dependency paths too.")
    if len(supported) > 1 and not _ran(board, "conclude"):
        return _call("conclude", f"{len(supported)} suspects are supported; keep the one that explains the most "
                     "and record why the others lost.")
    if supported:
        h = supported[0]
        return Decision(action="done", handoff_to="comms",
                        reason=f"Root cause supported: {h['change_id']} on {h['service']}; others ruled out.")
    if not _ran(board, "propose_hypotheses"):
        why = "Memory did not explain it" if _ran(board, "hypothesize_from_memory") else "No matching memory"
        return _call("propose_hypotheses",
                     f"{why}; list changes on services the alert depends on, plus the flat-log baseline.")
    return Decision(action="done", handoff_to="comms",
                    reason="Every change-based suspect was refuted; escalate as a non-change cause.")


def comms(board: dict[str, Any]) -> Decision:
    cause = board.get("cause_service")
    if cause and not _ran(board, "page_on_call", cause):
        return _call("page_on_call", f"The culprit lives in {cause}; page its owning team too.", service=cause)
    for co in board.get("co_cause_services", []):
        if not _ran(board, "page_on_call", co):
            return _call("page_on_call", f"{co} is a co-cause; page its owning team as well.", service=co)
    if cause and not _ran(board, "who_knows", cause):
        return _call("who_knows", f"Who knows {cause} best? Name them in the update.", service=cause)
    if cause and not _ran(board, "blast_radius", cause):
        return _call("blast_radius", f"Who else depends on {cause}? Warn them before they page us.",
                     service=cause)
    if cause and not _ran(board, "warn_owners"):
        return _call("warn_owners", "Of the teams hurt, tell the ones the rest of the company relies on first.")
    if not _ran(board, "post_update"):
        return _call("post_update", "Write the status update with owners, cause and sources.")
    return Decision(action="done", reason="Update written; waiting for a human to confirm the fix.")


ROLES = {"triage": triage, "investigator": investigator, "comms": comms}


def next_decision(role: str, board: dict[str, Any]) -> Decision:
    return ROLES[role](board)
