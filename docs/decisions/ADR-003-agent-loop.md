# ADR-003: The agent loop (board-driven planner, hand-written loop, LLM optional)

- Status: accepted, 2026-10-15
- Deciders: autonomous build agent (Claude Code), following the council's refinements in ADR-001; reviewed by Harsh

## Context
- Track 02 asks for shared state and handoffs between agents. Track 01 asks for actions based on what the graph shows, with explainable results.
- The council's biggest risk for this idea was that it looks like "a hardcoded pipeline answering a question you seeded". The planner must visibly branch on query results.
- No LLM key is available, and the demo, tests, cloud reviewer and judges must all run without one.
- Every answer must show its trace: the step, the reason, the Cypher, the rows and the timing.

## Decision
1. **The plan lives in the graph.** Before every decision, the loop reads the incident board from FalkorDB (`incident_board` query, `services/board.py::load_board`). The board holds the steps already taken (`AgentStep` nodes), the hypotheses and their status, and the recalled incidents. The planner gets nothing else: no Python state carries over between steps.
2. **Roles are pure functions of the board.** `domain/planner.py` has `triage(board)`, `investigator(board)` and `comms(board)`, each returning a `Decision`. They have no I/O, so they are unit-tested on plain dicts (`tests/unit/test_planner.py`).
3. **Handoffs are steps in the graph.** A role finishes with `Decision(action="done", handoff_to=...)`. The loop records that as an `AgentStep` with tool `handoff`. The next role starts by reading the same board, so it sees everything the previous role wrote: impacts, pages, hypotheses, evidence.
4. **A small hand-written loop** (`agents/loop.py::run_role`, the file is about 70 lines): observe (board) -> decide -> validate args and call the registered tool -> record the step in the trace and as an `AgentStep` node. `incident_id` is always forced to the current incident. If a tool raises on the chosen args, the deterministic planner picks that step instead. A role that uses up its step budget (`MAX_STEPS_PER_ROLE = 40`) hands off to the next role instead of failing the incident. Every run holds a per-tenant lock (ARCHITECTURE 3.7).
5. **The LLM is optional, behind the `LLMProvider` port.** `decide(role, board, tools) -> Decision`. The default `MockProvider` calls the deterministic planner. The LLM adapters (`adapters/llm/openai_compat.py` for any OpenAI-compatible endpoint, with presets for OpenAI, Gemini, Groq, OpenRouter and Ollama; `adapters/llm/anthropic.py`) send one stateless request per decision: a role prompt plus the board just read from the graph, with the registry's tool specs and a `finish` tool. Guardrails shared by both adapters:
   - anything off-script (HTTP error, timeout, unknown tool, invalid args, a step already on the board, a hypothesis id that is not open on the board, a malformed service or change id) falls back to the deterministic planner's decision for that same board, and the step's reason starts with "LLM fallback: ...";
   - `incident_id` is never the model's: it is set to the current incident;
   - tools registered with `agent=False` are never offered to any agent run (`registry.specs(agents_only=True)`), and a model that names one anyway falls back: `resolve_incident`, because confirming a root cause is a human's call, and the five event tools, because an agent must not invent graph facts;
   - handoffs only go forward (triage -> investigator -> comms), so a model cannot loop the roles.

   `make_llm()` in `wiring.py` picks the provider from `LLM_PROVIDER` and uses the deterministic planner when no key is set (Ollama needs none).
6. **Honest labelling.** Every run reports `planner` (for example "deterministic planner"), and the UI shows it.

## Consequences
- The trace is complete and replayable. Each step's first query is the board read, so you see exactly what the planner saw.
- The branching is real and visible:
  - Act 1 recalls `inc:0911`, but `memory_suspects` returns nothing, so the investigator falls back to traversal.
  - Act 2's strong recall skips traversal entirely.
  - Each refutation changes which hypothesis is checked next.
  - In an alert storm (act 3), triage correlates the related alerts first, and the investigator checks suspects on the shared upstream first.
  - When two or more suspects are supported, the investigator calls `conclude`: one leading cause is kept and each other one is recorded as outranked, with the reason.
  - If everything is refuted, the investigator escalates as a non-change cause.
- Deterministic runs make the demo repeatable and the eval meaningful (graph vs flat baseline over many seeds; see `docs/EVAL.md`).
- Coordination survives the process. Agent history is in the graph (`GET .../incidents/{id}/steps`), and a second `respond()` on the same incident picks up from the board instead of starting over.
- Cost: one extra read-only query per step (about 1 ms on the demo graph; EVAL.md measures a mean of 1.2 ms).
- Limitation: the planner's rules are hand-written heuristics, not learned. We say so plainly. The graph decides which branch is taken, and the rules decide what each branch means.
- Concurrency: "read board, decide, write" is not atomic on its own, and two concurrent `MERGE`s of the same edge can both create it. Every agent run therefore holds a per-tenant Redis lock; a responder that waits finds a finished board and only hands off (ARCHITECTURE 3.7).
- The brief suggested `agents/roles/` (one file per role) and `agents/trace.py`. We did not need them: the roles are three short functions in `domain/planner.py`, and the trace is `list[TraceStep]` plus `log_step`.

## Alternatives considered
- **An agent framework (LangGraph, CrewAI, AutoGen, LlamaIndex agents).** These keep agent state in Python memory or their own checkpointer, so the graph would become a side store and the handoff would not be graph state. They add dependencies and their own trace format, and most assume an LLM is present. The brief allowed frameworks only if they do not hide the trace. Our loop is about 70 lines, so a framework would not save code.
- **A fixed script (always run the same tools in the same order).** That is exactly the "hardcoded pipeline" judges would distrust. It also could not show memory shortening act 2.
- **LLM-first with no fallback.** It would not run without a key and would make tests flaky. It stays available as an adapter.
- **One "god agent" with all the tools.** Simpler, but it loses the Track 02 story (roles handing off through shared state), and the trace is harder to read.
- **Passing the board in memory between roles and writing to the graph only at the end.** Faster by a few ms, but then the graph would not be the coordination layer, and a crash would lose the run.
