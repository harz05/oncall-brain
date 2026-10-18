"""The agent loop: observe the board (from the graph), decide (planner or LLM), call a tool, record the step.

Every step is returned in the trace AND persisted as an AgentStep node on the incident, so the next
decision (by this role or the next one) sees it. Handoffs between roles are steps too.
"""

from collections.abc import Callable

from pydantic import ValidationError

from oncall_brain.agents import registry
from oncall_brain.agents.registry import ToolContext
from oncall_brain.domain.models import Decision, TraceStep
from oncall_brain.domain.planner import next_decision
from oncall_brain.ports import GraphRepository, LLMProvider
from oncall_brain.services.board import load_board

MAX_STEPS_PER_ROLE = 40
NEXT_ROLE = {"triage": "investigator", "investigator": "comms", "comms": None}

OnStep = Callable[[TraceStep], None]  # called with each step as soon as it is recorded (the UI's live stream)


def _target(args: dict) -> str:
    return str(args.get("service") or args.get("hypothesis_id") or args.get("incident_id") or "")


def record(repo: GraphRepository, incident_id: str, trace: list[TraceStep], step: TraceStep, target: str,
           on_step: OnStep | None = None) -> None:
    trace.append(step)
    repo.write("log_step", incident_id=incident_id, role=step.role, tool=step.tool, target=target,
               reason=step.reason, summary=step.summary, rows=sum(q.row_count for q in step.queries),
               ms=round(sum(q.ms for q in step.queries), 2), writes=step.writes, by=step.by)
    if on_step:
        on_step(step)


def run_role(role: str, repo: GraphRepository, incident_id: str, llm: LLMProvider,
             trace: list[TraceStep], on_step: OnStep | None = None) -> str | None:
    """Run one role until it is done. Returns the role it hands off to (or None)."""
    ctx = ToolContext(repo)
    specs = registry.specs(agents_only=True)
    for _ in range(MAX_STEPS_PER_ROLE):
        board, board_q = load_board(repo, incident_id)
        d = llm.decide(role, board, specs)
        if d.action == "done":
            return _handoff(repo, incident_id, trace, role, d.handoff_to, d.reason, board_q, on_step, d.by)
        try:
            out, tool, args = _call(ctx, d, incident_id)
        except (KeyError, ValueError, ValidationError) as e:
            # A bad tool choice (e.g. an id the LLM made up) must not abort the incident: let the
            # deterministic planner pick this step instead, and say so in the trace.
            d = next_decision(role, board)
            if d.action == "done":
                return _handoff(repo, incident_id, trace, role, d.handoff_to, d.reason, board_q, on_step)
            d = d.model_copy(update={"reason": f"fallback after tool error ({e}): {d.reason}"})
            out, tool, args = _call(ctx, d, incident_id)
        record(repo, incident_id, trace,
               TraceStep(seq=len(trace) + 1, role=role, tool=d.tool, reason=d.reason, by=d.by, summary=out.summary,
                         writes=tool.writes, queries=[board_q, *out.queries], highlight=out.highlight,
                         data=out.data), _target(args), on_step)
    # Out of budget: hand the board on rather than fail the incident; the next role works with what exists.
    board, board_q = load_board(repo, incident_id)
    return _handoff(repo, incident_id, trace, role, NEXT_ROLE[role],
                    f"step budget ({MAX_STEPS_PER_ROLE}) used up; handing on what the board has", board_q, on_step)


def _call(ctx: ToolContext, d: Decision, incident_id: str):
    tool = registry.REGISTRY[d.tool]
    if not tool.agent:  # confirming fixes and recording facts belong to humans, whatever the planner proposes
        raise ValueError(f"{d.tool} is not an agent tool")
    # Agents have no asker: a model-chosen user/session would reach someone's conversation memory (a Slack user's
    # included) past the identity checks the HTTP and MCP surfaces apply. Claude Security scan of b7b3746, F1.
    args = {k: v for k, v in d.args.items() if k not in ("user", "session")}
    if "incident_id" in tool.args_model.model_fields:
        args["incident_id"] = incident_id  # agents only ever act on the incident they were given
    return registry.call(d.tool, ctx, args), tool, args


def _handoff(repo, incident_id, trace, role, nxt, reason, board_q, on_step=None, by="rules") -> str | None:
    record(repo, incident_id, trace,
           TraceStep(seq=len(trace) + 1, role=role, tool="handoff", reason=reason, by=by,
                     summary=f"{role} hands off to {nxt or 'human'}", writes=True, queries=[board_q]),
           nxt or "human", on_step)
    return nxt
