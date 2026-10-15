"""The agent loop: observe the board (from the graph), decide (planner or LLM), call a tool, record the step.

Every step is returned in the trace AND persisted as an AgentStep node on the incident, so the next
decision (by this role or the next one) sees it. Handoffs between roles are steps too.
"""

from oncall_brain.agents import registry
from oncall_brain.agents.registry import ToolContext
from oncall_brain.domain.models import TraceStep
from oncall_brain.ports import GraphRepository, LLMProvider
from oncall_brain.services.board import load_board

MAX_STEPS_PER_ROLE = 15


def _target(args: dict) -> str:
    return str(args.get("service") or args.get("hypothesis_id") or args.get("incident_id") or "")


def record(repo: GraphRepository, incident_id: str, trace: list[TraceStep], step: TraceStep, target: str) -> None:
    trace.append(step)
    repo.write("log_step", incident_id=incident_id, role=step.role, tool=step.tool, target=target,
               reason=step.reason, summary=step.summary, rows=sum(q.row_count for q in step.queries),
               ms=round(sum(q.ms for q in step.queries), 2), writes=step.writes)


def run_role(role: str, repo: GraphRepository, incident_id: str, llm: LLMProvider,
             trace: list[TraceStep]) -> str | None:
    """Run one role until it is done. Returns the role it hands off to (or None)."""
    ctx = ToolContext(repo)
    specs = registry.specs()
    for _ in range(MAX_STEPS_PER_ROLE):
        board, board_q = load_board(repo, incident_id)
        d = llm.decide(role, board, specs)
        if d.action == "done":
            nxt = d.handoff_to or "human"
            record(repo, incident_id, trace,
                   TraceStep(seq=len(trace) + 1, role=role, tool="handoff", reason=d.reason,
                             summary=f"{role} hands off to {nxt}", writes=True, queries=[board_q]), nxt)
            return d.handoff_to
        tool = registry.REGISTRY[d.tool]
        args = dict(d.args)
        if "incident_id" in tool.args_model.model_fields:
            args.setdefault("incident_id", incident_id)
        out = registry.call(d.tool, ctx, args)
        record(repo, incident_id, trace,
               TraceStep(seq=len(trace) + 1, role=role, tool=d.tool, reason=d.reason, summary=out.summary,
                         writes=tool.writes, queries=[board_q, *out.queries], highlight=out.highlight,
                         data=out.data), _target(args))
    raise RuntimeError(f"{role} did not finish within {MAX_STEPS_PER_ROLE} steps")
