# How it meets the brief

How On-call Brain covers each Graph Hacks track, why FalkorDB is doing the work, and where each item of the
hackathon's guides lives in the code. Every row names the code or the test that shows it.

## Why the graph is not decoration

| What the agents do | FalkorDB feature doing the work | Without it |
|---|---|---|
| Blast radius, suspects, recall | Variable-length `DEPENDS_ON` walks that keep only edges live at alert time (`valid_from`/`valid_to`). Two run as FalkorDB user-defined functions in JavaScript (`src/oncall_brain/adapters/falkordb/udf/oncall.js`): `oncall.live_upstream` walks the callers breadth-first for `blast_radius` and drops a dead edge when it meets it; `oncall.live_reach` gives the fewest live hops to each suspect in `path_suspects` and `recall_similar`. The queries match their plain-Cypher reference forms row for row on 20 generated companies and a 100-service graph with cycles (`tests/integration/test_query_equivalence.py`) | no multi-hop suspects; retired dependencies blamed |
| Name resolution | Every service argument, on every surface, is resolved against the graph before a tool runs (`registry.call`, query `resolve_service`): an exact id or name, else the closest services by shared words or by FalkorDB's FLEX `flex.text.jaroWinkler` (`kafak` gets `svc:kafka`). An unknown name is refused with those suggestions | "0 services depend on payment-service", about a service that does not exist |
| Is there a way around a service? | `independent_routes`: `algo.maxFlow` on a projection of the live dependencies, every edge capacity 1, counts the routes that share no dependency edge (checkout reaches payments-gw one way only, through payments) | no answer to "will traffic go around it" |
| Refute "no path" suspects | `shortestPath` in `WITH` | the flat baseline's wrong answer stands |
| Alert storms | each alerting service's upstream closure over live edges; `algo.WCC` over the alerting services and their red upstreams decides which alerts are one incident; the shared upstream ranked by total hops; suspects come from every folded alert, and each records which alerting services it can reach | each alert is investigated alone, and act 3 blames the subscriptions deploy |
| Cascade victim vs cause | `depends_among`: live `DEPENDS_ON*` among the supported suspects' services; an upstream suspect already red when a nearer change landed takes the lead | a deploy on a service already failing from upstream gets blamed because it is nearest |
| Shared state and handoffs | the `Incident` board: `Hypothesis`, `Evidence` (`SUPPORTS`/`REFUTES`), `AgentStep` nodes, re-read before every decision | agents can't coordinate; the planner has nothing to decide from |
| Memory | `RECALLS` -> `FIXED_WITH` -> `Runbook` -`FOR_SERVICE`-> service picks the first suspects; `uses`/`successes` set the runbook's confidence; persisted per tenant | the same incident takes 6 investigator calls instead of 3 |
| Company brain | `ask`: FalkorDB full-text indexes on `Doc`, `Ticket` and `Message` find the sources, then `MENTIONS`, `DECIDES`, `SUPERSEDES`, `AUTHORED_BY`, `CHANGED` and `OWNS` name the services, changes, teams and people, and flag docs a newer one superseded. `who_knows` ranks people; `change_story` traces a change to its ticket, chat, docs, author and incidents. Per-engineer conversation memory (`Session`, `Question`) and `Initiative` nodes that tie people, tickets, changes and decisions together | keyword hits with no owner, no "is this still current?", nobody to ask, no memory of what you asked, no project behind a change |
| Keeping knowledge current | event tools write changes, anomalies, alerts, docs, chat, tickets, ownership and dependency start/end as they happen. Facts carry valid time and `recorded_at` (when the graph learned them), and the outcome lists `learned_late` facts | the next investigation works from stale facts; a late report silently rewrites what the agents knew |
| Locks, throttles, LLM budget | the coordination graph `oncall_brain_coord`: a run lock is a `Lease` node that a UNIQUE constraint makes exclusive (16 racing clients, one winner); a throttle or budget is a `Counter` node one atomic `MERGE ... SET` updates. No Redis key commands, so it runs on FalkorDB Cloud as is | two runs on one incident redo each other's work; no shared limits across the API and MCP |
| Safety, multi-tenancy, repeatable demo | every read is `GRAPH.RO_QUERY` with a 3 s timeout; one graph per tenant; a seed is built on `seeding_<t>` and published under the tenant lock (`GRAPH.COPY` to `pristine_<t>`, then `RENAME` over `tenant_<t>`), and a reset copies the pristine graph back the same way; UNIQUE `id` on every label, a UNIQUE and MANDATORY `key` on `DEPENDS_ON`, and MANDATORY `valid_from` on `DEPENDS_ON` and `OWNS`, so the database refuses a duplicate node, a duplicate dependency or an undated one | duplicates, undated edges, readers seeing a half-built tenant |

All of the cause-finding is Cypher traversal: temporal variable-length paths, `shortestPath`, and intersecting
upstream closures. Two graph algorithms take part in decisions. `algo.WCC` splits an alert storm (see [STORY.md](STORY.md), act 3).
`algo.pageRank` ranks criticality: `blast_radius` orders the impacted services by tier, then PageRank over the
dependencies live at alert time, and comms' `warn_owners` sends a heads-up to the on-call of the most critical impacted
teams nobody paged. FalkorDB's algorithms walk every edge, and the tenant graph keeps retired dependencies as history,
so the live edges are projected into a scratch graph first, the algorithm runs there, and the projection is dropped
(`tests/integration/test_algorithms.py` plants a retired and a future dependency from every service and shows the order
does not move). `algo.betweenness` is not used: its scores are sampled, so changing `samplingSeed` reorders the
services even with `samplingSize` above the node count, and a score that blames a change has to be exact.

## How each track is covered

**01 Agents That Act on Connected Data**
- Multi-hop `DEPENDS_ON*` suspects with temporal edge filters; `shortestPath` refutations; the planner branches on what each query returns.
- Alert storms: `algo.WCC` on a projection of the alerting services and their red upstreams decides which alerts are one incident, chains included (`test_a_chained_storm_is_one_incident_by_wcc_and_the_far_cause_is_a_co_cause`). The shared upstream is ranked by convergence, and `conclude` keeps the cause that explains the most alerting services plus any co-cause (`test_act3_alert_storm_is_correlated_and_only_then_solved`, `tests/integration/test_storms.py`).
- Causality: a deploy on a cascade victim loses to the upstream change that was already red when it landed; a silent middle hop is weaker support, named as a monitoring gap, not a refutation (`tests/integration/test_causality.py`).
- Criticality: `algo.pageRank` on a point-in-time projection of the live dependencies decides which impacted teams get the heads-up first (`warn_owners`, `test_criticality_comes_from_the_dependencies_live_at_alert_time_not_from_history`).
- More graph tools over MCP: `independent_routes` (`algo.maxFlow` on the live projection, `test_independent_routes_counts_live_routes_with_max_flow`), `query_plan` (`GRAPH.PROFILE` for a read, `GRAPH.EXPLAIN` for a write; the UI's Plan button), `list_incidents`.
- Actions written back: incident, impacts, pages, heads-ups, hypotheses, evidence, the consulted expert, the status update; live events written through the event tools.
- Every service name resolved against the graph before a tool runs, typos through FalkorDB's FLEX library (`test_a_service_the_graph_does_not_hold_is_named_unknown_not_answered_about`). Every step's Cypher is in the trace.

**02 Agent Memory and Coordination**
- Three roles hand off through the shared `Incident` board, with no in-process state (by default one deterministic planner plays all three roles); `AgentStep` history persisted per incident.
- Episodic, semantic and procedural memory; the runbook decides which suspects memory proposes and loses confidence when refuted. Act 2 recalls act 1; replayed on a copy of the pristine graph it takes 6 investigator calls and finds the culprit on check 2, with memory 3 calls and check 1 (`?compare=memory`, shown in the UI).
- Conversation memory per engineer and per session: `Session` and `Question` nodes with `FOLLOWS`, `ABOUT` and `ANSWERED_WITH`, so a follow-up's "it" resolves and "what did I ask about payments-gw" is a query, isolated per user and cleared by a tenant reset (`tests/integration/test_sessions.py`).
- One graph per tenant (`test_tenants_are_isolated`).
- Concurrency, measured: unique `id` constraints on every label, a per-tenant lease around agent runs and write tools, reads that never wait, and seeds and resets that swap graphs atomically (`GRAPH.COPY` + `RENAME`). 8 tenants at once, 1,548 reads during locked agent runs with 0 errors, 400 contended writes with 0 duplicates; p50/p95/p99 in [PERF.md](PERF.md#concurrency) (`tests/integration/test_concurrency.py`).
- Coordination is graph state: leases (a UNIQUE constraint as the mutex) and counters in the `oncall_brain_coord` graph, repaired after a database restart (`tests/integration/test_coordination.py`). Every dependency carries a UNIQUE key, so racing writers record it once without a lock (`test_racing_writers_record_one_dependency_once_without_any_lock`).
- Facts carry valid time and transaction time, and the outcome lists what was learned after the incident opened (`test_a_change_reported_after_the_incident_opened_is_used_and_marked_learned_late`).

**03 Company Brain**
- A synthetic corpus in the same graph as the services and incidents: 35 docs (postmortems, design notes, decision records, runbook pages), 41 chat messages, 21 tickets and 3 initiatives, linked by `MENTIONS`, `AUTHORED_BY`, `DECIDES`, `SUPERSEDES`, `REQUESTED` and `PART_OF`.
- `ask` answers a free-form question from FalkorDB full-text search plus graph expansion, puts a current doc before the one it superseded, and cites every source (`tests/integration/test_brain.py`). Answers are assembled from graph facts and quoted sentences, not written by an LLM. `who_knows` and `change_story` count docs too. All three are in the UI's Ask tab.
- Ownership with history: `OWNS {valid_from, valid_to}` and `transfer_ownership`, so "who owns" flips, "who owned payments-gw at the time of inc:0911" does not, and `who_knows` still credits the team that ran it (`tests/integration/test_ownership.py`).
- People, projects and decisions: "what is the Q4 cost review changing and who is on it" is a walk over `Initiative`, `PART_OF`, `REQUESTED`, `CHANGED`, the blamed incidents, `LEADS`, `AUTHORED_BY` and `MENTIONS`, and every status update names the initiative behind its cause (`tests/integration/test_initiatives.py`).
- Keeping knowledge current: temporal dependencies and event tools that record changes, anomalies, alerts and retired dependencies as they happen (`test_live_events_drive_a_new_investigation`). `record_doc` writes a new decision record with what it supersedes, so `ask` puts it first and flags the old one at once (`test_a_new_decision_record_flips_the_ask_answer_and_flags_the_old_one`). `record_message` and `record_ticket` bring in chat and tickets the same way; an unknown id is refused before anything is written. `recorded_at` beside valid time makes a late report visible as late (`learned_late`).
- Every status update cites its sources and the person to ask (`CITES` edges).

## The tutorial's five techniques, in this repo

WeMakeDevs' guide for this hackathon, [How to build an agent that reasons over a graph](https://www.wemakedevs.org/blogs/how-to-build-an-agent-that-reasons-over-a-graph),
names five techniques and four outcomes. Where each one lives here:

| Technique | In On-call Brain |
|---|---|
| Model the question, not the data | The model is shaped by the on-call questions: `DEPENDS_ON`, `OWNS` and `ON_CALL` carry validity windows, so "what was live at alert time" is one filter, and the `Incident` board holds hypotheses and evidence, so "what is ruled out" is a read ([DATA_MODEL.md](DATA_MODEL.md)). |
| A fixed tool catalogue beats generated queries | 33 tools over 120 named, parameterised `.cypher` statements ([QUERIES.md](QUERIES.md)). Claude picks tools and arguments; it never writes Cypher. Reads run as `GRAPH.RO_QUERY`. |
| Resolve names against the database | `resolve_service` runs before every tool, on every surface, and inside `ask`: `payment-service` gets "No service named 'payment-service' in the graph; did you mean svc:payments, svc:payments-gw?", and `payments-gw` or `Payments-GW` resolve to `svc:payments-gw`. |
| Memory is more nodes | Episodic (`Incident`, `CAUSED_BY`, `RECALLS`), procedural (`Runbook`, `FIXED_WITH`, its `uses` and `successes`) and conversation memory (`Session`, `Question`) are nodes and edges in the tenant graph, read by the next run: act 2 takes 3 investigator steps instead of 6. |
| Return the path with the answer | Every answer carries its trace (tool, Cypher, parameters, rows, reason) and the evidence path, which the UI highlights; the status update cites its sources with `CITES` edges. |

| Outcome | Where you see it |
|---|---|
| Answered with a path | Act 1: the payments-gw config change, with the path payments-gw -> payments -> checkout and when each hop slowed. |
| Answered from memory | Act 2: "Solved from memory", the confirmed fix tested first. |
| Not in the graph | An empty blast radius says no live `DEPENDS_ON` edge is recorded, "not proof nothing breaks"; `ask` says when nothing in docs, tickets or chat mentions the words. |
| Unknown service | "No service named ... in the graph", with the closest real ones. |

The guide's demo move, the same question at depth 1 and then depth 4, is the `max_hops` argument of `blast_radius`
(the hop limit of the `oncall.live_upstream` UDF): over MCP, `blast_radius {"service": "payments-gw", "max_hops": 1}`
returns the direct callers, `"max_hops": 4` the services further out.

## In FalkorDB's terms

FalkorDB describes a context layer as "a persistent, queryable, relationship-aware store of organizational knowledge
that sits between the agent and the LLM" ([FalkorDB, Oct 14](https://www.falkordb.com/reference/enterprise-ai-agents-context-layer/)).
In On-call Brain, each company's FalkorDB graph is that layer. The agents, whether Claude or the rules planner, never
see raw records and never write Cypher. They call named, parameterised queries, and each call returns rows together
with the Cypher that produced them. Without FalkorDB the agents have nothing to reason over.
[FALKORDB_NOTES.md](FALKORDB_NOTES.md) lists the FalkorDB behaviour behind each design choice.

FalkorDB's production readiness checklist ([FalkorDB, Oct 14](https://www.falkordb.com/reference/why-rag-projects-never-reach-production/)):

| Criterion | In this repo |
|---|---|
| Freshness | Event tools write facts as they happen (`record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency`, `transfer_ownership`, `record_doc`, `record_message`, `record_ticket`). `DEPENDS_ON` and `OWNS` edges are closed with `valid_to`, never deleted, and a MANDATORY constraint refuses one without `valid_from`. Facts carry two times: when they were true and when the graph learned them (`recorded_at`). A suspect change or an anomaly on the evidence paths, inside the alert window, that the graph learned after the incident opened is used and listed as `learned_late`. Tests: `test_live_events_drive_a_new_investigation`, `test_transfer_ownership_flips_who_owns_but_not_who_owned_at_the_time`, `test_the_database_refuses_an_undated_dependency_or_owner`, `test_a_change_reported_after_the_incident_opened_is_used_and_marked_learned_late` |
| Entity resolution | Every service argument, on every surface, is resolved against the graph before a tool runs (`registry.call`, query `resolve_service`). An unknown name is refused with the closest ids, typos included through FalkorDB's FLEX library (`flex.text.jaroWinkler`: `kafak` gets `svc:kafka`). Every label has a UNIQUE `id` constraint, and every dependency a UNIQUE key. Tests: `test_a_service_the_graph_does_not_hold_is_named_unknown_not_answered_about`, `test_every_label_has_a_unique_id_constraint_that_reset_keeps_and_the_database_enforces` |
| Answer traceability | Every tool call puts its queries (name, Cypher, parameters, rows, ms) in the trace. Each `AgentStep` node keeps the query names, parameters, row counts, timings and a hash of the Cypher. Evidence stores the live path it was judged on (`Evidence.path`). The status update cites its sources through `CITES` edges. Each query row in the UI shows FalkorDB's own execution time and whether the plan came from its cache; the Plan button (tool `query_plan`) shows `GRAPH.PROFILE` for a read and `GRAPH.EXPLAIN` for a write. Tests: `test_agent_steps_persist_in_the_graph_and_respond_is_idempotent`, `test_the_update_cites_the_decision_history_behind_the_cause` |
| Multi-hop reasoning | `blast_radius` walks up to 6 hops of live `DEPENDS_ON` edges in a UDF (`oncall.live_upstream`), and the fewest live hops to each suspect comes from a second one (`oncall.live_reach`). `shortestPath` lists the live paths a check judges and refutes decoys; `algo.pageRank`, `algo.WCC` and `algo.maxFlow` run on point-in-time projections. Tests: `tests/integration/test_query_equivalence.py`, `test_act1_finds_the_planted_cause_and_refutes_every_decoy` |
| Access control | Partly done. Each company is its own graph (`test_tenants_are_isolated`). Reads go through `GRAPH.RO_QUERY` (`test_read_tools_cannot_write`). `/mcp` needs a bearer token. Conversation memory is kept per user (`test_memory_is_per_user_and_per_session`). Not done: a FalkorDB user per tenant, and permissions at node or edge level |

The hackathon brief, mapped to this repo:

| The brief | In this repo |
|---|---|
| Follow connections across data | `blast_radius`, `path_suspects`, `storm_upstream` over live `DEPENDS_ON` edges (`test_query_equivalence.py`, `tests/integration/test_storms.py`) |
| Remember across sessions | Act 2 recalls act 1 through `RECALLS`, `CAUSED_BY` and `FIXED_WITH` a `Runbook` that counts `uses` and `successes` (`test_act2_is_solved_from_act1_memory_and_slower_without_it`). `Session` and `Question` nodes keep each engineer's conversation (`test_a_follow_up_says_it_and_what_did_i_ask_is_answered_from_the_graph`) |
| Share state between agents | Three roles hand off through the `Incident` board and its `AgentStep` nodes (`test_concurrent_responders_do_not_duplicate_work_or_edges`). Leases and counters live in the `oncall_brain_coord` graph (`tests/integration/test_coordination.py`) |
| Connect people, projects, and decisions | `who_knows`; `Initiative` with `DRIVES`, `LEADS` and `PART_OF`; `DECIDES` and `SUPERSEDES`; `OWNS` with its history (`test_ask_walks_an_initiative_to_its_tickets_changes_people_and_decisions`, `test_ask_why_names_the_decision_of_record_and_flags_what_it_superseded`) |
| Show the path behind an answer | The Cypher behind every step is in the trace, `blast_radius` returns each caller's path, `Evidence.path` is stored, and updates carry `CITES` edges (see Answer traceability above) |
| "Which accounts are linked to this flagged transaction?" | The graph has no accounts. The equivalent is "which alerts are linked to this alert": `correlate_alerts` runs `algo.WCC` on a projection of the alerting services and their red upstreams to decide which alerts form one incident (`test_a_chained_storm_is_one_incident_by_wcc_and_the_far_cause_is_a_co_cause`) |
| "What did this customer ask for last month, and was it resolved?" | The graph has no customers. The equivalents are an engineer's own questions ("what did I ask about payments-gw", `Session`/`Question`; `test_a_follow_up_says_it_and_what_did_i_ask_is_answered_from_the_graph`) and whether an incident was resolved, and by which change and runbook (`list_incidents`, `CAUSED_BY`, `FIXED_WITH`; `test_list_incidents_finds_the_ids_an_outside_agent_needs`) |
| "Who on the team has worked on this system before?" | `who_knows` ranks people by current and former ownership, the changes they made, the incidents they were paged for, and the docs they wrote (`test_company_brain_who_knows_and_change_sources`, `test_who_knows_counts_doc_authorship_and_change_story_cites_docs`) |
| "What breaks if this service goes down?" | `blast_radius` returns every service that depends on it over live edges, with paths, ordered by tier and by PageRank on a projection of the live edges (`test_the_same_question_at_depth_1_then_4`, `test_criticality_comes_from_the_dependencies_live_at_alert_time_not_from_history`) |
