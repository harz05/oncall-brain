# Scorecard: On-call Brain against the Graph Hacks brief

Written by the cloud helper from snapshot `f98571a` (2026-10-16, 04:20 IST), run from a clean checkout on Ubuntu 24.04
with `falkordblite` 0.10 (`make setup` 18 s, `make seed` 0.7 s, `make demo` DEMO OK in 2.2 s, `make test` 167 passed in
52 s, `make lint` clean). One row per item the judges' pages name. Every row points at code a judge can open.

Scores: **0** absent. **1** present but thin, or not something the agents decide with. **2** real and tested, with a gap
a judge would notice. **3** strong, with evidence in a tool, a `.cypher` statement, a test and the UI.

Paths: tools are in `src/oncall_brain/services/tools.py` (`ask` in `services/brain.py`), queries in
`src/oncall_brain/adapters/falkordb/queries/<file>.cypher` (named by `// name:`), tests in `tests/`. "UI" means
`web/index.html` + `web/app.js`: the Incidents view (inbox, Answer card, "Show me why" graph + steps + Cypher), the
Ask the brain chat and the Connect page.

## The challenge: work the graph has to do

| # | Item | Score | Evidence in our code | Gap |
|---|---|---|---|---|
| C1 | Follow connections across data | 3 | `blast_radius`, `propose_hypotheses`, `check_hypothesis`, `correlate_alerts`; `triage.cypher: blast_radius, storm_upstream` (breadth-first, 6 hops, edges live at alert time), `investigate.cypher: path_suspects, live_paths, any_path, depends_among`; `test_act1_finds_the_planted_cause_and_refutes_every_decoy`, `test_act3_alert_storm_is_correlated_and_only_then_solved`; UI "Show me why" lights the path per step | Traversals stop at 6 hops (documented). |
| C2 | Remember across sessions | 3 | `resolve_incident` (`comms_memory.cypher: resolve_incident` writes `CAUSED_BY`, `FIXED_WITH`, `Runbook.uses/successes`), `recall_similar`, `hypothesize_from_memory` (`investigate.cypher: recall_similar, memory_suspects`); memory lives in the graph, so it survives processes and `make db-stop` (`shutdown save`); `test_act2_is_solved_from_act1_memory_and_slower_without_it`, `test_confirmed_cause_survives_a_recheck_and_update_rewrite`; UI act 2 memory card with the `?compare=memory` ablation | Memory is per tenant only: nothing is remembered per engineer (see T2-7). |
| C3 | Share state between agents | 3 | The incident board is read from the graph before every decision (`board.cypher: incident_board`), every step is an `AgentStep` node (`log_step`), handoffs are steps (`agents/loop.py: _handoff`); `test_agent_steps_persist_in_the_graph_and_respond_is_idempotent`, `test_concurrent_responders_do_not_duplicate_work_or_edges`; UI progress tiles per role + step list | Runs on one tenant are serialised by a lock (see T2-6), so sharing is sequential, never two agents writing one board at once. |
| C4 | Connect people, projects and decisions | 2 | `OWNS`, `MEMBER_OF`, `ON_CALL {start,end}`, `AUTHORED_BY`, `REQUESTED`, `DECIDES`, `SUPERSEDES`, `CITES`, `CONSULTED`; `who_knows`, `change_story`, `ask` ("why" route: `knowledge.cypher: decisions_about`); `test_ask_why_names_the_decision_of_record_and_flags_what_it_superseded`, `test_who_knows_counts_doc_authorship_and_change_story_cites_docs` | No project or initiative node: tickets link to one change, never to the initiative, team goal or deadline behind it, so "what is the Q4 cost review changing and who is on it" has no graph answer. Ownership has no history (see T2-2). |
| C5 | Show the path behind an answer | 3 | Every `TraceStep` carries `reason`, each `QueryRun` (name, Cypher, params, rows, ms, read-only flag) and a `Highlight` of node and edge ids; `Evidence.path`/`reason`/`tag` nodes; the status update's "Ruled out:" line; MCP results return `queries[].cypher`; UI step cards with Cypher and the lit path, `make demo --cypher` | `ask` answers cite sources but do not return the hop-by-hop path for each fact (the `Highlight` edges exist, the answer text does not name them). |

## Track 01: agents that act on connected data

| # | Item | Score | Evidence | Gap |
|---|---|---|---|---|
| T1-1 | Multi-hop reasoning | 3 | `path_suspects` (0..6 hops, `valid_from`/`valid_to` per edge), `check_hypothesis` (live path + anomaly propagation along it, `verdict.judge`), cascade rule in `verdict.leading`; eval 186/200 vs 134 (anomaly-aware log), 57 (keyword), 0 (newest change), `docs/EVAL.md`; `tests/integration/test_causality.py` | None that a judge would miss. |
| T1-2 | Graph queries and algorithms as agent tools | 1 | Queries: yes, 82 named statements, `shortestPath` in `WITH` (`live_paths`, `any_path`, `recall_similar`), breadth-first closures with `CALL {}`. Algorithms: none in the product. `algo.betweenness` was tried and dropped (README: sampled scores reorder with the seed, and it cannot filter `DEPENDS_ON` by validity). `reference.cypher` keeps pre-rewrite forms for equivalence tests only | The track names algorithms explicitly. This build exposes `algo.pageRank`, `algo.WCC`, `algo.labelPropagation`, `algo.betweenness`, `algo.BFS`, `algo.SPpaths`, `algo.SSpaths`, `algo.MSF` (`CALL dbms.procedures()`); all but betweenness are deterministic. None drives a decision today. Candidates that would: PageRank over `DEPENDS_ON` (reversed) as a criticality score to order who triage pages and warns first when a blast radius spans several teams; WCC / label propagation over the alerting services and their red upstreams to split an alert storm into independent incidents in one call (today `correlate_alerts` does that pairwise in Python); `algo.SPpaths` with anomaly onset as weight to pick the propagation path a check judges. Each must then be checked against the temporal edges, since the procedures see every `DEPENDS_ON` edge, retired or not. |
| T1-3 | Tool selection through MCP | 2 | 24 MCP tools generated from the registry (`mcp_server/__init__.py: catalogue`): docstring, pydantic JSON schema, `readOnlyHint`, a required `tenant`; stdio and Streamable HTTP (`--http`), Host/Origin checks; `test_mcp_exposes_every_registry_tool_and_runs_them_on_a_tenant`, `test_mcp_over_http_refuses_foreign_host_and_origin`; `docs/MCP.md` with `claude mcp add`; the UI Connect page. Inside the product, Claude Opus 5.5 and Sonnet 5.5 chose all 60 decisions from the same tool specs with 0 fallbacks (`docs/LLM_RUN.md`) | No test where an outside agent, given a plain question over MCP, picks the right tool (the in-product LLM run is the nearest thing, and it is prompted with a playbook). Several args have no description (`HypothesisArgs.hypothesis_id`, `PathArgs.*`, `ResolveArgs.incident_id`), the server has no MCP prompts or resources, no Claude Code plugin, and the HTTP transport has no token. |
| T1-4 | Actions based on what the graph shows | 3 | Writes caused by graph results: `PAGED` (`record_page`), `IMPACTS` (`record_impacts`), `CONSULTED` (`record_consult`), `Hypothesis`/`Evidence` (`add_hypotheses`, `record_evidence`), `CORRELATED_WITH`/`SHARED_UPSTREAM`, the status `Message` that `CITES` its sources (`post_update`), memory on confirm (`resolve_incident`), optional Slack post (`adapters/slack.py`); the planner branches on the board (`domain/planner.py`); `test_live_events_drive_a_new_investigation` | Pages and warnings are graph writes and an optional Slack text; there is no outbound pager integration (fine for the demo, say so in the README). |
| T1-5 | Explainable results | 3 | Reason per step, verdict reason and short tag per suspect, `conclude` records why each loser lost (`record_outranked`), both no-graph baselines and the memory and correlation ablations are printed by `make demo` and shown in the UI; `tests/unit/test_verdict.py` | None. |

## Track 02: agent memory and coordination

| # | Item | Score | Evidence | Gap |
|---|---|---|---|---|
| T2-1 | Episodic memory | 3 | `Incident` + `AgentStep` history + `CAUSED_BY` + `RECALLS {score}`; recall is structural (cause service on the live dependency path, same symptom scores higher: `recall_similar`), not text similarity; `docs/decisions/ADR-004-memory-model.md` | Recall scores are coarse (2 or 3); no recency weighting. |
| T2-2 | Semantic memory (facts that stay current) | 2 | `DEPENDS_ON {valid_from, valid_to}` used by every traversal at alert time, `ON_CALL {start, end}`, `Doc SUPERSEDES Doc`; `retire_dependency` / `add_dependency` event tools; `test_a_dependency_that_starts_after_the_alert_is_not_called_retired`, `test_ask_puts_current_docs_first_and_flags_superseded_ones` | Only dependencies and docs have validity. `OWNS` and `MEMBER_OF` are timeless, so an ownership change cannot be recorded and "who owned payments-gw at the time of inc:0911" is unanswerable; a runbook or decision cannot be marked superseded by the agents. |
| T2-3 | Procedural memory | 3 | `Runbook {uses, successes}` learned on confirm, reinforced on reuse, loses confidence when its suggestion is refuted (`record_evidence` adds a use); `memory_suspects` orders by `successes/uses`; the update's "Next action: ... (worked N of M times)" line; `test_memory_refuted_falls_back_to_traversal_then_gives_up` | No decay with time; a runbook that last worked a year ago ranks like one from yesterday. |
| T2-4 | Persistent conversation history | 1 | Agent conversations persist: every step of every incident is an `AgentStep` node, replayable by `incident_steps` (`GET .../incidents/{id}/steps`). Human conversations do not: the Ask chat lives in the browser tab, nothing records who asked what, and a follow-up ("and who is on call for it?") cannot resolve "it" | Record each question as a `Question` node in a per-engineer `Session` (`ASKED`, `ABOUT` the linked entities, `ANSWERED_WITH` the sources), let `ask` resolve pronouns from the session's last entities, and expose "what did I ask about payments-gw" as a tool. This also gives T2-7 its per-user memory. |
| T2-5 | Shared state and handoffs | 3 | Board + `handoff` steps (C3); three roles, each only reads the board and calls tools; a second responder joins an open storm incident instead of opening a duplicate (`triage.cypher: open_incident_for_alert`, `test_concurrent_responders_to_one_storm_make_one_incident`) | None. |
| T2-6 | High-concurrency reads and writes | 2 | Unique constraints on `id` for every label (`FalkorRepository._ensure_unique_ids`, created at `ensure_schema`, carried by `GRAPH.COPY`, re-applied by `reset`): the database refuses a duplicate node even from a raw `CREATE`; reads use `GRAPH.RO_QUERY` and never take the lock; writes on one tenant serialise at a per-tenant Redis lock (10 ms poll); a reset swaps the graph in with `GRAPH.COPY` + `RENAME`, so reads never fail mid-reset; different tenants run in parallel. Measured by `scripts/concurrency.py` into `docs/PERF.md` (Concurrency): 8 tenants at once 0.85 s wall against 1.9 s sequential, 8 readers during 3 locked agent runs 1,236 reads / 0 errors / p50 24 ms, 8 writers x 75 events 0 duplicates / p50 2 ms / p99 about 200 ms, and the raw races (12 clients: 10 duplicate ids without constraints, 0 with; `MERGE` on one edge still duplicates). `tests/integration/test_concurrency.py` (5 tests) | Writes on one tenant still serialise: two incidents on the same tenant cannot be investigated at once, and the slowest contended write waits 0.3 to 0.5 s. A per-incident lock (plus the tenant lock only for `reset`) would let independent incidents proceed in parallel; FalkorDB has no edge constraint, so the lock cannot go away entirely. |
| T2-7 | Separate memory per user or tenant | 2 | One graph per tenant (`tenant_<name>` + `pristine_<name>`, `FalkorGraphStore`), `MAX_TENANTS`, `test_tenants_are_isolated`, `test_reset_keeps_a_tenants_own_seed`; UI shows the tenant chip | Per tenant only. No per-user memory (T2-4 fixes that) and no per-user identity on any surface (documented: "no per-user auth"). |

## Track 03: company brain

| # | Item | Score | Evidence | Gap |
|---|---|---|---|---|
| T3-1 | Docs, tickets and chats in one graph | 3 | 35 `Doc`, 21 `Ticket`, 41 `Message` nodes next to services, changes and incidents, linked by `MENTIONS`, `AUTHORED_BY`, `DECIDES`, `SUPERSEDES`, `REQUESTED`; full-text indexes on `Doc`, `Ticket`, `Message` (`repository.py: FULLTEXT`); `datagen._corpus`; `test_brain_corpus_is_linked_dated_outside_the_acts_and_plants_its_facts` | The corpus is seed-only: there is no tool to add a doc, ticket or message after seeding, so a judge cannot "bring their own knowledge" the way they can bring changes and alerts. |
| T3-2 | Who owns / who knows what | 3 | `OWNS`, `ON_CALL` at a time, `who_knows` with its scoring spelled out (owning team 3, change 2, incident paged 1, docs up to 3); `ask` "who owns" / "who knows" routes (`knowledge.cypher: ownership, who_knows`); `test_ask_who_owns_kafka_answers_from_owns_and_the_rotation`; the update's "Ask:" line | Ownership has no history (T2-2). |
| T3-3 | Tracing decisions to their source | 3 | `DECIDES` + `decisions_about` ("why" route names the decision of record, its author, and what it supersedes), `change_story` (ticket, chat, docs, author, incidents), `cause_context` cites decision records in the status update; `test_ask_traces_why_the_payments_gateway_pool_was_lowered`, `test_the_update_cites_the_decision_history_behind_the_cause` | None. |
| T3-4 | Keeping knowledge current as things change | 2 | Event tools `record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency` (`events.cypher`), idempotent on ids; `SUPERSEDES` between docs; `test_live_events_drive_a_new_investigation` shows the investigation's answer change after a retirement; `test_event_tools_correct_rather_than_duplicate` | Nothing updates ownership, team membership, on-call, docs or decisions after seeding, and no test shows an `ask` answer flipping after a knowledge event (only an investigation flips). Nothing flags stale knowledge (a runbook page that mentions a retired dependency). |
| T3-5 | Answers with clear sources | 3 | `ask` returns `sources`, `hits` with snippets and `superseded_by`, and leads with the graph fact; status updates are `Message` nodes with `CITES` edges to every change, ticket, doc, runbook and person they name; `test_ask_puts_current_docs_first_and_flags_superseded_ones` | None. |

## Rule 3: would anything still work with FalkorDB removed?

| # | Item | Score | Evidence | Gap |
|---|---|---|---|---|
| R1 | Nothing works without the graph | 3 | Every tool is a named Cypher statement run through `GraphRepository` (`read` = `GRAPH.RO_QUERY`, `write` = `GRAPH.QUERY`); the planner's only input is the board read from the graph; memory, handoffs, the company brain and the status update are graph nodes; `GET /api/health` reports `falkordb: false` and every route answers 503 (`test_nul_input_and_falkordb_errors_are_not_500`) | The only non-graph path is the UI's recorded replay (`?offline=1`, GitHub Pages), which is labelled "recorded replay" and plays fixtures captured from real runs. Keep that label prominent so a judge never mistakes it for the product running without a database. |

## Totals

| Group | Score |
|---|---|
| Challenge (C1-C5) | 14 / 15 |
| Track 01 (T1-1..5) | 12 / 15 |
| Track 02 (T2-1..7) | 16 / 21 |
| Track 03 (T3-1..5) | 14 / 15 |
| Rule 3 | 3 / 3 |
| **All** | **59 / 69** |

## Weakest rows, in the order to close them

1. **T2-6 concurrency (1, now 2).** Done: unique constraints on `id` for every label, `scripts/concurrency.py` with
   p50/p95/p99 and duplicate counts in `docs/PERF.md`, an atomic reset, 5 tests. Left: a per-incident lock so two
   incidents on one tenant can be investigated at once.
2. **T1-2 algorithms (1).** One or two procedures that change a decision, each verified against the temporal edges and
   shown in the trace: PageRank criticality for who to page and warn first; WCC or label propagation to split a storm.
3. **T2-4 conversation history (1) + T2-7 per-user memory (2).** `Session` and `Question` nodes per engineer, pronoun
   resolution in `ask`, "what did I ask" as a tool.
4. **T2-2 / T3-4 keeping knowledge current (2).** Validity on `OWNS`, a `transfer_ownership` event, `record_doc` with
   `supersedes`, and a test where an `ask` answer flips after the event.
5. **T1-3 MCP (2).** Describe every argument, add server prompts, test an outside agent picking the right tool for plain
   questions, package as a Claude Code plugin, put a token on the HTTP transport.
6. **C4 projects (2).** An `Initiative` node (tickets `PART_OF` it, teams `DRIVES` it) so decisions, changes and people
   connect through the work that caused them.

Not planned: a vector index for `ask`. This build supports it (verified: `CREATE VECTOR INDEX`, `vecf32`,
`db.idx.vector.queryNodes`), but without an embedding model the vectors would be hashes of words, which is full-text
search in disguise, and the only key on hand is Anthropic's, which has no embeddings endpoint. Revisit if an
embedding key appears; otherwise it would be decoration, which rule 2 forbids.
