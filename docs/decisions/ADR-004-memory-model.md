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
| Episodic: what happened | `Incident` nodes: `TRIGGERED_BY` an `Alert`, `IMPACTS` services, `PAGED` and `CONSULTED` people, `HAS_HYPOTHESIS` -> `Hypothesis` -`SUSPECTS`-> `Change`, `Evidence` that `SUPPORTS` / `REFUTES` it, `LOGGED` -> `AgentStep` history, `HAS_UPDATE` -> `Message`. Once resolved: `CAUSED_BY` -> `Change`. | the agents during a run; `resolve_incident` for the cause |
| Semantic: facts about the company | `Team -OWNS-> Service`, `Person -MEMBER_OF-> Team`, `Service -DEPENDS_ON {valid_from, valid_to}-> Service`, `Person -ON_CALL {start, end}-> Team`, `Change -CHANGED-> Service`, `-AUTHORED_BY->`, `Ticket -REQUESTED->`, and the docs, tickets and chat about all of it: `Doc` / `Ticket` / `Message -MENTIONS->`, `Doc -DECIDES-> Service`, `Doc -SUPERSEDES-> Doc` | ingest (`ingest_*` queries), then the event tools (`record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency`); docs, tickets and chat are seeded only |
| Procedural: what worked | `Runbook {kind, steps, uses, successes} -FOR_SERVICE-> Service`, and `Incident -FIXED_WITH-> Runbook` | `resolve_incident` learns or reinforces `rb:<service>:<change kind>`; `record_evidence` adds a use when a check refutes the runbook's suggestion |

**Temporal facts keep knowledge current.** Dependencies and on-call shifts carry validity times. Every traversal filters edges to the ones valid at the alert time (`r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)`). A retired dependency stays in the graph as history, but it no longer counts as a path. That is how the `legacy-billing` decoy is refuted with "dependency retired before the alert", which is a different reason from "never connected".

**Recall is structural, not vector** (`recall_similar` query):
- Candidates: resolved past incidents whose root-cause service is reachable from the new alert's service along `DEPENDS_ON` edges valid at the new alert's time (0 to 6 hops).
- Score: 2 for being on the live path, plus 1 for the same symptom (for example `latency`). The planner trusts a recall only at score >= 3 (`RECALL_MIN_SCORE`).
- The recall is written back as `(:Incident)-[:RECALLS {score, cause_service}]->(:Incident)`, so the planner reads it from the board and the UI can draw it.

**The runbook decides what memory suspects. Evidence still decides the cause.** `hypothesize_from_memory` (`memory_suspects` query) follows `RECALLS` -> past incident -> `FIXED_WITH` -> `Runbook` -> `FOR_SERVICE` -> service, and suspects the changes of the runbook's `kind` on that service in the alert window, still on the live path, most trusted runbook first (`successes / uses`). These become ordinary `Hypothesis` nodes with `source = "memory"` and `runbook = <id>`. They are checked first, but by the same `check_hypothesis` rules as any other suspect (a silent middle hop on their path is a weak support with the gap named, as for anyone else). If a check refutes one, its runbook gets one more use and no success (once per hypothesis), so its confidence drops. If a memory suspect and another suspect are both supported, memory leads unless the other explains more of the alerting services or has a complete anomaly chain where the memory suspect has a monitoring gap (`domain/verdict.py::leading`), and the cascade rule applies to memory too: a supported suspect upstream of the memory suspect's service that was already red when the memory suspect's change landed takes over. A suspect that explains an alerting service the memory suspect cannot is kept as a co-cause, not ruled out. In an alert storm, a memory suspect that explains only some of the alerting services does not end the search: the investigator also lists the dependency-path suspects (`propose_hypotheses`). If memory finds nothing, the investigator falls back to full traversal (this happens in act 1: `inc:0911`'s runbook is for inventory deploys, and there is none in the window). When memory found the cause, the status update gives the runbook's first step as "Next action: <step> (this runbook worked N of M times)". Learned runbooks keep their steps short ("Revert the config change on payments-gw", "Watch checkout p99 recover within 10 minutes", "Last time the culprit was: <summary>", "Add a guard: ..."), so the first step reads as an action.

**Only humans write cause and success.** `CAUSED_BY` and runbook successes are written only by `resolve_incident`, which a human triggers after confirming the fix. The human's call overrides the agents: the confirmed change becomes the incident's `confirmed` hypothesis (created with source `human` if no agent suspected it), and any other supported suspect or co-cause is outranked (its evidence tagged "a human confirmed another cause", which is what the update's "Ruled out:" line shows). Agents can lower a runbook's confidence when its suggestion is refuted, but they cannot raise it.

## Consequences
- Act 2 after act 1 needs 3 investigator calls and 1 check (culprit on check 1), against 6 calls and 4 checks (culprit on check 2) without memory. That is the same incident both times, the only fair before/after for memory: `make demo` prints the pair, and `POST .../alerts/{id}/respond?compare=memory` returns it as `ablation.without_memory` by replaying the alert on a copy of the tenant's pristine graph (`GraphStore.clone_pristine` into a scratch tenant, dropped afterwards). The UI's act 2 card shows that pair. An earlier UI compared act 2 with act 1 (8 calls then), two different incidents; that comparison was removed.
- Every recall has an explanation you can draw: the new alert's service, the live dependency path, the old incident's cause service, and the runbook that fixed it.
- Recall respects time. A past incident whose cause service is no longer upstream of the alerting service is not recalled.
- Recall needs no model, no key and no network. It runs in a few milliseconds in the same database as everything else.
- Memory persists across processes and sessions, and is per tenant for free (one graph per tenant).
- Limitations:
  - Recall needs a known cause service, so an incident resolved without a `CAUSED_BY` change is not recalled by this rule.
  - Symptom match is exact string equality.
  - Depth is bounded at 6 hops.
  - Confidence drops when a suggestion is refuted, but it does not decay with age.
- The brief's `EmbeddingProvider` port was deliberately not built (nothing would use it yet).

## Alternatives considered
- **Vector similarity over incident text (embeddings).** It would match every "p99 latency" incident regardless of where the cause was, ignore whether the old cause is still upstream, need a model (or a weak offline hash), and give a score with no explanation. It could be useful later as a tie-breaker between structurally equal candidates. FalkorDB has a vector index (`db.idx.vector.queryNodes`), so it would stay in the same database and query.
- **Keyword or full-text match on titles.** Same problem as vectors with less recall, so not for causal recall. FalkorDB full-text indexes are used where they fit, for the company-brain Q&A: `ask` searches `Doc`, `Ticket` and `Message` text, then the graph decides what the hits mean (which change, whose service, which doc is current via `SUPERSEDES`).
- **An external memory layer (Graphiti, Mem0, Cognee).** Extra infrastructure, usually needs an LLM for extraction, and it would move memory away from the dependency graph that makes recall structural. Past entries in this space already cover it (see ADR-001).
- **Untimed facts (no `valid_from` / `valid_to`) with deletes for changes.** Simpler, but the graph would forget what was true at the alert time, so it could not tell "retired dependency" from "never connected", and replaying an old incident would give a different answer.
- **Letting agents write `CAUSED_BY` themselves when a check supports a hypothesis.** Faster learning, but a wrong verdict would become memory and then bias the next incident. A human confirmation is one click in the UI.
