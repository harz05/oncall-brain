# ADR-004: Memory model (structural recall, runbooks as procedural memory, temporal facts)

- Status: accepted, 2026-10-15
- Deciders: autonomous build agent (Claude Code), following the council's "structural, not vector" ruling in ADR-001; reviewed by Harsh

## Context
- Track 02 asks for episodic, semantic and procedural memory that persists across sessions and is separate per tenant. Track 03 asks for knowledge that stays current and answers with sources.
- Recall must work with no API key, offline, and deterministically, so the demo and eval are repeatable.
- The recall has to be explainable: "why did you think of that old incident?" needs a concrete answer.
- Incident titles in real life are short and look alike ("X p99 latency above 2s"). What makes two incidents similar is where the cause sat in the system, not the words.

## Decision
All memory lives in the tenant's graph. There are three kinds:

| Kind | What it is in the graph | Written by |
|---|---|---|
| Episodic: what happened | `Incident` nodes: `TRIGGERED_BY` an `Alert`, `IMPACTS` services, `PAGED` people, `HAS_HYPOTHESIS` -> `Hypothesis` -`SUSPECTS`-> `Change`, `Evidence` that `SUPPORTS` / `REFUTES` it, `LOGGED` -> `AgentStep` history, `HAS_UPDATE` -> `Message`. Once resolved: `CAUSED_BY` -> `Change`. | the agents during a run; `resolve_incident` for the cause |
| Semantic: facts about the company | `Team -OWNS-> Service`, `Person -MEMBER_OF-> Team`, `Service -DEPENDS_ON {valid_from, valid_to}-> Service`, `Person -ON_CALL {start, end}-> Team`, `Change -CHANGED-> Service`, `-AUTHORED_BY->`, `Ticket -REQUESTED->`, `Message -MENTIONS->` | ingest (`ingest_*` queries) |
| Procedural: what worked | `Runbook {kind, steps, uses, successes} -FOR_SERVICE-> Service`, and `Incident -FIXED_WITH-> Runbook` | `resolve_incident` learns or reinforces `rb:<service>:<change kind>` |

**Temporal facts keep knowledge current.** Dependencies and on-call shifts carry validity times. Every traversal filters edges to the ones valid at the alert time (`r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)`). A retired dependency stays in the graph as history, but it no longer counts as a path. That is how the `legacy-billing` decoy is refuted with "dependency retired before the alert", which is a different reason from "never connected".

**Recall is structural, not vector** (`recall_similar` query):
- Candidates: resolved past incidents whose root-cause service is reachable from the new alert's service along `DEPENDS_ON` edges valid at the new alert's time (0 to 6 hops).
- Score: 2 for being on the live path, plus 1 for the same symptom (for example `latency`). The planner trusts a recall only at score >= 3 (`RECALL_MIN_SCORE`).
- The recall is written back as `(:Incident)-[:RECALLS {score, cause_service}]->(:Incident)`, so the planner reads it from the board and the UI can draw it.

**Memory proposes. Evidence still decides.** `hypothesize_from_memory` (`memory_suspects` query) turns a strong recall into suspects: changes in the alert window on the recalled cause service, still on the live path. These become ordinary `Hypothesis` nodes with `source = "memory"`. They are checked first, but by the same `check_hypothesis` rules as any other suspect. If memory finds nothing, the investigator falls back to full traversal (this happens in act 1 with `inc:0911`).

**Only humans write cause and runbook.** `CAUSED_BY` and runbook successes are written only by `resolve_incident`, which a human triggers after confirming the fix. Agents can recall memory, but cannot reinforce their own guesses.

## Consequences
- Act 2 after act 1 needs 3 investigator calls and 1 check, against 5 and 3 without memory. The `make demo` ablation shows both runs against the same graph.
- Every recall has an explanation you can draw: the new alert's service, the live dependency path, the old incident's cause service, and the runbook that fixed it.
- Recall respects time. A past incident whose cause service is no longer upstream of the alerting service is not recalled.
- Recall needs no model, no key and no network. It runs in a few milliseconds in the same database as everything else.
- Memory persists across processes and sessions, and is per tenant for free (one graph per tenant).
- Limitations:
  - Recall needs a known cause service, so an incident resolved without a `CAUSED_BY` change is not recalled by this rule.
  - Symptom match is exact string equality.
  - Depth is bounded at 6 hops.
  - `uses` and `successes` only grow today, because only confirmed fixes are recorded. Recording failed attempts and decaying confidence is on the backlog.
- The brief's `EmbeddingProvider` port was deliberately not built (nothing would use it yet).

## Alternatives considered
- **Vector similarity over incident text (embeddings).** It would match every "p99 latency" incident regardless of where the cause was, ignore whether the old cause is still upstream, need a model (or a weak offline hash), and give a score with no explanation. It could be useful later as a tie-breaker between structurally equal candidates. FalkorDB has a vector index (`db.idx.vector.queryNodes`), so it would stay in the same database and query.
- **Keyword or full-text match on titles.** Same problem as vectors with less recall. FalkorDB full-text indexes remain an option for the company-brain Q&A, not for causal recall.
- **An external memory layer (Graphiti, Mem0, Cognee).** Extra infrastructure, usually needs an LLM for extraction, and it would move memory away from the dependency graph that makes recall structural. Past entries in this space already cover it (see ADR-001).
- **Untimed facts (no `valid_from` / `valid_to`) with deletes for changes.** Simpler, but the graph would forget what was true at the alert time, so it could not tell "retired dependency" from "never connected", and replaying an old incident would give a different answer.
- **Letting agents write `CAUSED_BY` themselves when a check supports a hypothesis.** Faster learning, but a wrong verdict would become memory and then bias the next incident. A human confirmation is one click in the UI.
