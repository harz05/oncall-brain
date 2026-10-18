# Walkthrough: learn the codebase in 30 minutes

This is for Harsh, and for anyone who has to explain this project without having written it line by line. Read it with the code open. Section 1 is the reading order. Section 2 traces one alert through the real functions and queries. Section 3 is what to say to a judge. Section 4 has exercises you can run on this machine.

Before you start (two minutes, from `graphhacks/`):

```bash
source /media/harsh/MyPassport1/devenv/env.sh
make db      # FalkorDB on :6379 (no-op if it is already up)
make seed    # rebuild graph tenant_acme from scratch + pristine copy pristine_acme
make demo    # acts 1-3 and both ablations in the terminal; ends with DEMO OK
```

Keep the `make demo` output on screen. Every section below points at lines in it.

---

## 1. Reading order (about 30 minutes)

| # | Min | File | What to look for |
|---|---|---|---|
| 1 | 3 | `docs/decisions/ADR-001-idea.md` | The two-act story, the decoys, and why "the plan lives in the graph". This is the pitch (act 3, the alert storm, came later). |
| 2 | 3 | `src/oncall_brain/datagen.py` (docstring and the act 1, act 2 and act 3 blocks) | The planted story: the real cause `chg:pgw-pool-1` (a payments-gw pool cut from 200 to 20), and four decoys, each built to be refuted by a different graph fact. Act 2 adds `chg:pay-77`, a healthy decoy one hop away. Act 3 is three alerts in 4 minutes with a postgres-orders cause. Two decoys are timed to fool a change log that watches anomalies: act 1's legacy-billing deploy goes red before payments-gw does, and act 3's subscriptions deploy blips right after it. Times are epoch ints around `T1` (09:30 IST). Noise is random but kept out of the act windows. Then skim `_corpus`: the docs, tickets and chat the company brain searches, with a few planted facts (why the payments-gw pool was lowered, who designed the checkout retries, why legacy-billing left the checkout path). |
| 3 | 2 | `domain/models.py` | Five small types. `ToolOutput` (summary, data, queries, highlight) is what every tool returns. `Decision` is what the planner returns. `TraceStep` is one line of the trace. |
| 4 | 2 | `ports/__init__.py` | Three Protocols. Note `read()` vs `write()`: reads are `GRAPH.RO_QUERY`. Queries are addressed by name. |
| 5 | 3 | `adapters/falkordb/queries.py`, `repository.py` | How `// name: x` blocks are loaded. `_run()` picks `ro_query` or `query`. One graph per tenant (`tenant_<name>`). `snapshot()` uses `GRAPH.COPY` (retried on "could not fork"); `restore()` copies to a staging key and `RENAME`s it over the tenant key, so readers never see a missing graph. `scratch()` gives a side graph for a projection an algorithm runs on. `lock()` is the per-tenant Redis lock every agent run and write tool holds. `ensure_schema()` creates the `id` and `at` indexes, the full-text indexes on `Doc`, `Ticket` and `Message`, and a unique constraint on `id` for every label. `clone_pristine()` copies the pristine graph into a scratch tenant (the memory ablation). |
| 6 | 5 | `adapters/falkordb/queries/*.cypher` | Read `triage.cypher` (`blast_radius`, `on_call_for`), then `investigate.cypher` (`recall_similar`, `path_suspects`, `recent_changes`, `live_paths`, `any_path`, `depends_among`, `anomaly_baseline`), then `board.cypher` (`incident_board`, `log_step`), then `comms_memory.cypher` (`update_facts`, `post_update`, `resolve_incident`), then `knowledge.cypher` (`who_knows`, `record_consult`, `search_knowledge` with `db.idx.fulltext.queryNodes`, `knowledge_context`). `events.cypher` holds the five live-event writes. `algorithms.cypher` holds the point-in-time projection and `algo.pageRank` (criticality), plus the heads-up queries. Spot the same temporal filter everywhere: `r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)`. |
| 7 | 2 | `agents/registry.py` | `@tool` reads the name, docstring and args model from the function, so a tool is defined once. `call()` validates args. `agent=False` keeps a tool away from agent runs: `specs(agents_only=True)` is what the planner or LLM sees (no `resolve_incident`, no event tools); `specs()` is what the MCP clients and `GET /api/tools` see. |
| 8 | 4 | `services/tools.py` | Each tool = named queries + a `ToolOutput`. Spend most of the time on `check_hypothesis`: facts, `live_paths`, `any_path` only if needed, `anomalies_between`, pick the path the anomaly lit up most, then the pure `judge()`, then which alerting services it explains (`explained`) and when its own service first went red (`onset`), then `record_evidence`. Then `correlate_alerts` (which alerts are related, and where their upstreams converge) and `conclude` (several supported suspects: one leading cause, the rest outranked or kept as co-causes). Then `services/brain.py::ask`: terms, full-text search, re-rank, graph expansion, an answer built from the facts. |
| 9 | 3 | `domain/verdict.py`, `domain/planner.py` | `judge()`: five rules in order; four refute, a silent middle hop is a weak support with the gap named, and each verdict carries a short tag. `leading()`: most alerting services explained, then fewest gaps, then memory, then nearest, then earliest onset, then newest, then id; then the cascade rule (an upstream suspect already red when the leader's change landed takes over); a suspect is outranked only if the leader explains every alerting service it explains, otherwise it is a co-cause. The planner: three functions of the board (in a storm, a memory hit that explains only part of it also triggers `propose_hypotheses`). `check_order`: memory first, then (in an alert storm) the shared upstream in convergence order, then fewest hops, then newest. `RECALL_MIN_SCORE = 3`, `STORM_WINDOW` = 15 min. |
| 10 | 2 | `agents/loop.py`, `services/board.py`, `services/respond.py` | The loop: board, decide, call, record. `incident_id` is always forced to the current incident; an `agent=False` tool is refused; a tool error falls back to the planner; a role out of steps (40) hands off. `respond()` takes the tenant lock and chains the roles through handoffs. `resolve()` confirms the human's cause and rewrites the update. `without_memory()` replays an alert on a scratch copy of the pristine graph (`?compare=memory`). `outcome()` builds the result card from the graph (cause, co-causes, ruled out, update, pages, impact, storm) and the trace (counters), plus both baselines: the flat change log and the anomaly-aware one. |
| 11 | 1 | `tests/integration/test_story.py`, `test_storms.py`, `test_causality.py`, `test_brain.py` | The product's claims as tests: decoys refuted for the right reasons, the baseline is wrong, memory makes act 2 shorter, read tools cannot write, tenants are isolated, concurrent responders don't duplicate edges, live events drive a new investigation, act 3 needs correlation, an unrelated alert is not folded in, a re-run still reports its cause, a human override becomes the cause. `test_storms.py` builds five storms from live events (two independent causes, alerts on one service, a quiet shared cache, memory explaining part of a storm, two changes on one service). `test_causality.py` keeps the two probes a mock judge ran: a deploy on a cascade victim is not blamed, and a monitoring gap on a middle hop still names the cause. `test_brain.py` checks `ask` (the right doc first, superseded docs flagged, no content words reach the index) and docs in `who_knows` / `change_story`. 206 tests in all. |

If time is left: `api/app.py` (thin handlers, error mapping, the Host / same-origin / token guard), `services/seeding.py` (rebuild from scratch, `Meta` fingerprint, reset), `mcp_server/` (the same registry over MCP, see `docs/MCP.md`), `wiring.py` (the only place adapters are chosen), `adapters/llm/openai_compat.py` (how an LLM planner falls back to the rules), `scenarios.py` and `scripts/eval.py` (the 200-scenario eval, with its perturbations).

---

## 2. The life of one alert

Act 1, `alert:checkout-latency` ("checkout p99 latency above 2s"), on the default seed. The step numbers match `make demo`.

**Entry.** From the UI: `POST /api/tenants/acme/alerts/alert:checkout-latency/respond`. `api/app.py::respond` checks the tenant exists (`tenant_repo`), then calls `services/respond.py::respond(repo, alert_id, llm)`. `make demo` calls the same `respond()` directly.

| Step | Role | Function -> named queries | What the graph returned |
|---|---|---|---|
| 1 | triage | `respond()` -> `open_incident` tool -> `open_incident` (W) | `MERGE (i:Incident {id:'inc:checkout-latency'})-[:TRIGGERED_BY]->(alert)`. This node is the board. `log_step` writes `AgentStep` #1. |
| 2 | triage | `run_role` -> `load_board` -> `incident_board` (RO). `planner.triage`: blast radius not run yet. -> `blast_radius` tool -> `incident_head`, `blast_radius` (RO), `record_impacts` (W) | 3 services depend on checkout at alert time: api-gateway (1 hop), web-frontend and mobile-bff (2 hops). Written as `IMPACTS` edges. |
| 3 | triage | board -> `page_on_call` -> `on_call_for` (RO), `record_page` (W) | The `ON_CALL {start, end}` shift covering 09:30 IST: Ravi Moreau (@ravi.moreau, Checkout). `PAGED` edge. |
| 4 | triage | board -> triage is done | `AgentStep` with tool `handoff`, target `investigator`. |
| 5 | investigator | board -> `recall_similar` (RO), `record_recalls` (W) | `inc:0911` "Checkout slow during flash sale": its cause service (inventory) is on checkout's live path and it has the same symptom, so the score is 3. `RECALLS` edge. |
| 6 | investigator | board shows recall score 3 -> `hypothesize_from_memory` -> `memory_suspects` (RO) | `inc:0911` was fixed with `rb:inventory-rollback`, a runbook for inventory deploys. No inventory deploy in the 2-hour window: 0 rows. Memory did not help, and the planner sees that on the next board. |
| 7 | investigator | board: no open hypotheses -> `propose_hypotheses` -> `path_suspects`, `recent_changes` (RO), `add_hypotheses` (W) | On the dependency path: `chg:cart-310`, `chg:pricing-2140` (1 hop), `chg:pgw-pool-1` (2 hops). From the flat log: `chg:search-420` (newest anywhere, 8 min before) and `chg:legacy-193`. Five open `Hypothesis` nodes. |
| 8 | investigator | `check_hypothesis(cart-310)` -> `hypothesis_facts`, `live_paths`, `anomalies_between` (RO), `record_evidence` (W) | Path exists, but cart had no anomaly: REFUTES (rule 3). |
| 9 | investigator | `check_hypothesis(pricing-2140)` | Rolled back 70 min before the alert: REFUTES (rule 1). |
| 10 | investigator | `check_hypothesis(pgw-pool-1)` | Live path checkout -> payments -> payments-gw, and anomalies on all three after the change: SUPPORTS (rule 5). |
| 11 | investigator | `check_hypothesis(search-420)`, also `any_path` | No path at all from checkout to search: REFUTES (rule 2). |
| 12 | investigator | `check_hypothesis(legacy-193)`, also `any_path` | A path exists only through a `DEPENDS_ON` edge retired 3 days ago: REFUTES with "dependency retired" (rule 2). |
| 13 | investigator | board: one supported, none open | Hand off to comms. `cause_service` = payments-gw is now on the board. |
| 14 | comms | `page_on_call(svc:payments-gw)` | Asha Nakamura (@asha.nakamura, Payments). |
| 15 | comms | `who_knows(svc:payments-gw)` -> `who_knows` (RO), `record_consult` (W) | Sana Brandt (Payments): on the owning team (3), authored 3 changes to payments-gw (6), and wrote docs and chat about it (3, the cap): score 12. Written as `CONSULTED {for_service, score}`. |
| 16 | comms | `blast_radius(svc:payments-gw)` | 7 services depend on payments-gw. The ones not already hit and not on the failure path (refunds, subscriptions) are "also at risk"; payments is on the path, so it is not listed. |
| 17 | comms | `post_update` -> `incident_head`, `update_facts`, `refuted_hypotheses`, `co_causes`, `cause_facts`, `cause_context`, `cause_initiative` (RO), `post_update` (W) | `domain/update.status_update()` writes the text: "Likely cause: config change on payments-gw by Sana Brandt: \"Lower payments-gw HTTP pool ...\"", "Ruled out: legacy-193 (dependency retired), search-420 (no dependency path), pricing-2140 (rolled back), cart-310 (no anomaly after it)", "Behind it: CR-881 is part of 'Q4 cost review' (Payments, led by Lena Costa, due 2026-12-31)", "Ask: Sana Brandt (@sana.brandt, Payments) knows payments-gw best". The `Message` is stored on the incident (nothing goes to Slack) and `CITES` the change, `ticket:CR-881`, `msg:pay-deploys-1`, `doc:cost-review-pgw`, `person:sana-brandt` and `init:q4-cost-review`. |
| 18 | comms | board -> done | Handoff to `human`. `respond()` ends and builds `outcome()`. |

**Outcome.** Root cause `chg:pgw-pool-1`, 4 refuted, 8 investigator calls, 5 checks, culprit on check 3. `outcome()` runs two baselines with no traversal. `recent_changes`: a flat change log blames `chg:search-420`, the newest change. `anomaly_baseline`: a change log that also watches anomalies blames `chg:legacy-193`, because legacy-billing went red at 08:45, before payments-gw. Both are wrong; only the retired `DEPENDS_ON` edge says checkout stopped calling legacy-billing.

**Human resolve.** `POST .../incidents/inc:checkout-latency/resolve {"change_id": "chg:pgw-pool-1"}` -> `resolve()` -> `resolve_incident` tool. `change_info` (RO), then `domain/update.learned_runbook()`, then the `resolve_incident` query (W). It writes `CAUSED_BY`, `MERGE`s `Runbook rb:payments-gw:config` (kind `config`, uses 1, successes 1), `FIXED_WITH` and `FOR_SERVICE`, and marks the hypothesis `confirmed` with "confirmed by a human" evidence. Had the human picked a change no agent suspected, the query would create that hypothesis (source `human`) and outrank the agents' pick. `resolve()` then re-runs `post_update`, so the stored update starts "status: resolved, cause confirmed" and says "Cause (confirmed)".

**Act 2** (`alert:refunds-latency`, three days later). `recall_similar` now finds `inc:checkout-latency`: its cause service, payments-gw, is on refunds -> payments -> payments-gw, and the symptom is the same, so the score is 3. `memory_suspects` follows `RECALLS` -> `inc:checkout-latency` -> `FIXED_WITH` -> `rb:payments-gw:config` -> `FOR_SERVICE` -> payments-gw, and returns the config changes on payments-gw in the window: `chg:pgw-pool-2`. The hypothesis carries `runbook: rb:payments-gw:config`. One `check_hypothesis` gives SUPPORTS. That is 3 investigator calls instead of 6, 1 check instead of 4, and the culprit on check 1 instead of 2, where "instead of" is the same incident without memory: the UI asks for `?compare=memory` on act 2, and `without_memory()` copies `pristine_acme` into a scratch tenant, replays the alert there, drops it and returns the counters as `ablation.without_memory`. (Without memory, nearest-first checking tries `chg:pay-77` first: a newer payments deploy one hop away, with no anomaly.) The status update now includes "Next action: Revert the config change on payments-gw (this runbook worked 1 of 1 times)". Had the check refuted it, `record_evidence` would have added 1 to the runbook's `uses` (once), lowering its confidence. The anomaly-aware baseline also gets act 2 right (payments-gw is the first to go red), so act 2 shows memory and speed, not accuracy over that baseline.

**Act 3** (`alert:subscriptions-latency`, two days after act 2). Checkout and refunds alerted 4 and 2 minutes earlier, so the board's `storm` count is 2 and triage calls `correlate_alerts` before anything else: `storm_alerts`, then `storm_upstream` (for each alerting service, every service it reaches over live edges, with hop counts, and whether it went red). Both other alerts share red upstream services with subscriptions (payments, postgres-orders), so both are folded in; an unrelated alert sharing only a quiet cache would not be. The services all three reach are ranked by total hops: payments 3, postgres-orders 5, fraud-check 6, payments-gw 6, redis-cache 8, kafka 9 (the step's summary: "6 upstream services are shared by all of them, nearest to all first: payments, postgres-orders, fraud-check"; the UI labels payments "shared by all 3 alerting services", not "the cause"). `record_correlation` writes `CORRELATED_WITH` and `SHARED_UPSTREAM {rank, hops}`. The investigator checks `chg:pg-conn-3` first, the only suspect on the shared upstream: SUPPORTS, explains 3 of 3 alerting services. `chg:subs-88` is SUPPORTED too (subscriptions blipped 2 minutes after the deploy) but explains 1 of 3 (`storm_unexplained` finds no live path from checkout or refunds to subscriptions). `chg:search-430` is refuted (no path). Two supported suspects, so the investigator calls `conclude` (`incident_head`, `incident_board`, `depends_among` for the cascade rule): `leading()` keeps `chg:pg-conn-3` on coverage (3 alerting services against 1), and since it also explains subscriptions, `record_outranked` marks `chg:subs-88` outranked ("chg:pg-conn-3 explains every alerting service this change does (1) and 2 more"). On a fresh graph: 17 steps, 6 investigator calls, 3 checks, culprit on check 1 (after acts 1 and 2 in the UI, a `hypothesize_from_memory` step that finds nothing makes it 18 and 7). The flat change log blames `chg:search-430`, and the anomaly-aware one `chg:subs-88`, because subscriptions went red first. `make demo` then reruns act 3 with correlation switched off: both suspects explain the one alert, the nearer `chg:subs-88` leads, and the answer is wrong.

One query to read slowly, `live_paths` (in `investigate.cypher`):

```cypher
MATCH p = (:Service {id: $origin})-[:DEPENDS_ON*0..6]->(:Service {id: $target})   // every path up to 6 hops
WHERE all(r IN relationships(p)
          WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)) // only edges live at alert time
WITH p ORDER BY length(p) LIMIT 20                                                  // shortest first, bounded
RETURN [n IN nodes(p) | n.id] AS path
```

`*0..6` (not `1..`) lets a change on the alerting service itself match with a path of length 0. `check_hypothesis` then looks up anomalies on every service on these paths and judges the path the anomaly lit up most. If the query returns nothing, `any_path` runs `shortestPath` with no time filter. If that finds a path, the dependency existed once but was retired. That difference is the whole legacy-billing decoy. (The `dependency_path` tool runs the same query and keeps the first, shortest path.)

---

## 3. How to explain it to a judge

### The graph model in three sentences
1. The company is a graph: teams `OWNS` services (with `valid_from` / `valid_to`, so a handover keeps the history), people are `MEMBER_OF` teams and hold time-bounded `ON_CALL` shifts, services `DEPENDS_ON` each other with `valid_from` / `valid_to`, and every deploy or config `Change` `CHANGED` a service and was `AUTHORED_BY` a person. A ticket `REQUESTED` it, and chat messages and docs (postmortems, design notes, decision records, runbook pages) `MENTIONS` it; a doc `DECIDES` a service and `SUPERSEDES` an older doc.
2. An `Incident` is the agents' shared board: it is `TRIGGERED_BY` an alert, and the agents attach `IMPACTS`, `PAGED`, `CONSULTED`, `Hypothesis` nodes (each `SUSPECTS` a change, and `Evidence` `SUPPORTS` or `REFUTES` it), their own `AgentStep` history (`LOGGED`), and a status update that `CITES` its sources.
3. A resolved incident is memory: it is `CAUSED_BY` a change and `FIXED_WITH` a `Runbook` (which is `FOR_SERVICE` a service and a change kind). A new incident `RECALLS` old ones whose cause service is still on its live dependency path, and their runbooks pick its first suspects.

### Why FalkorDB is indispensable (what breaks without which query)

| Feature | Query | Without it |
|---|---|---|
| Who is hurt, who else is at risk | `blast_radius` (reverse `DEPENDS_ON*1..6`, edges live at alert time) | No impact list, no "also at risk" warning. |
| Which changes could explain the alert | `path_suspects` (`DEPENDS_ON*0..6` at alert time, then `CHANGED` in the window) | Only the flat change log is left, and it blames `chg:search-420`, which is wrong. |
| Ruling out decoys | `live_paths`, `any_path` (`shortestPath`), `anomalies_between` | You cannot tell "retired dependency" from "never connected", or check that the symptom travelled the path. |
| Cascade victims | `depends_among` (live `DEPENDS_ON*` among the supported suspects) plus each suspect's `onset` | A deploy on a service that was already red from upstream is blamed because it is nearest. |
| Alert storms | `storm_alerts`, `storm_upstream` (upstream closures with hops, intersected), `storm_unexplained` (which alerting services a suspect explains), `record_outranked`, `record_co_causes` | Each alert is investigated alone, and act 3 blames the subscriptions deploy. |
| Who to page | `on_call_for` (`ON_CALL` shift valid at alert time) | No owner and no page. |
| Agent coordination | `incident_board`, `log_step` | The planner has no input at all. It has no state outside the graph. |
| Memory | `recall_similar`, `memory_suspects` (recall -> runbook -> service -> changes of that kind), `resolve_incident` | Act 2 takes the long road (6 calls and 4 checks instead of 3 and 1, same incident). |
| Sources and company brain | `update_facts`, `cause_initiative`, `change_story`, `who_knows`, `search_knowledge` (full-text indexes) + `knowledge_context` and `initiative_story` for `ask` | The update cannot cite the ticket, chat or design note, cannot say who to ask or which project the change was made for; "who knows payments-gw" has no answer; a question finds text but not the change, the owner or whether a doc is still current. |
| Keeping knowledge current | `record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency` (`events.cypher`) | New facts would need a re-seed before an investigation could use them. |
| Safety and tenancy | `GRAPH.RO_QUERY`, one graph per tenant, `GRAPH.COPY` | Read tools could write, tenants would share data, and demo resets would mean re-seeding. |

The one-liner: take FalkorDB out and nothing runs, not because a database is missing, but because every decision the agents make is a query result.

### Fourteen likely questions, with short answers

1. **"You planted the answer. Isn't this a hardcoded pipeline?"** The story is planted, so we know the right answer. The agent still has to find it. The planner only sees the board and branches on what queries return. Four decoys are refuted for four different graph reasons, shown with their Cypher. The flat baseline gets it wrong, and so does an anomaly-aware change log in acts 1 and 3 (it gets act 2 right). Memory changes the path in act 2. The eval (`make eval`, `docs/EVAL.md`) runs the same code on 200 random incidents with their own decoys, plus noise, telemetry gaps and cascade victims: the graph agent is right in 184, an anomaly-aware change log in 134 (fooled by the retired-dependency decoy 55 times and by a decoy that noise made red 11 times), keyword matching in 57, the flat change log in 0. See question 13 for what the 16 misses are.
2. **"networkx or SQL could do this."** For one traversal, maybe. Here, temporal edges filtered at alert time, persistent state that three roles read and write, memory that outlives the process, `GRAPH.RO_QUERY` and per-tenant graphs are used together, in one database, by every step. In SQL, the variable-length temporal paths become recursive CTEs, and you would rebuild the rest yourself.
3. **"Where is the AI? The planner is rules."** Yes. By default one deterministic planner plays all three roles: hand-written rules that choose each step from what the graph returns, and the UI badge says exactly that. `ask` is not an LLM either: its answer is assembled from graph facts and quoted sentences. That is a choice: it runs with no key, it is repeatable, every claim points at a node, and the eval measures the checks rather than a model's mood. An LLM can plug into the same `LLMProvider` port, gets the same board and tools, and falls back to the rules if its answer is invalid. Be plain about the limit: those adapters are tested against canned HTTP replies only and have never been run against a live model here, so we claim nothing about how an LLM planner performs. What we do claim is the context layer, the graph the planner reads, which is the same either way.
4. **"Why not vector search for similar incidents?"** Incident titles all look alike ("p99 latency"). What matters is whether the old cause is still upstream of the new alert, at the new alert's time. That is a path query, not a text distance. It needs no model, works offline, and the path is the explanation. Vectors could be a tie-breaker later (ADR-004).
5. **"How do the agents actually coordinate?"** Only through the graph. Each decision starts by reading the incident board. Each step is written as an `AgentStep`. A handoff is a step too. The investigator knows what triage did because it is in the graph, not because a variable was passed.
6. **"How do you keep knowledge current?"** Facts that change carry validity times (`DEPENDS_ON valid_from / valid_to`, `ON_CALL start / end`). Queries filter by the alert time. Old facts stay as history but do not count. That is how the retired legacy-billing dependency is ruled out.
7. **"What stops an agent from corrupting the graph?"** Read tools use `GRAPH.RO_QUERY`, so FalkorDB refuses writes (there is a test for it). Writes go through a few narrow, named, parameterised queries that `MERGE` on stable ids. Cause and runbook memory are written only when a human confirms the fix.
8. **"Multi-tenant? Concurrent?"** One graph per tenant, so data and memory are isolated (tested). That is isolation, not access control: there is no per-user auth (the company brain's conversation memory is per `user` and session, but `user` is a parameter the caller supplies), and the demo is meant for localhost (`API_TOKEN` is all-or-nothing). Every label has a unique constraint on `id`, so the database itself refuses a duplicate node, even from a raw query. FalkorDB has no edge constraint, and two concurrent `MERGE`s of the same edge can both create it (measured), so every agent run and write tool holds a per-tenant Redis lock, shared by the API, MCP and scripts. That serialises writes on one tenant; reads never take the lock, and a reset swaps the graph in with `GRAPH.COPY` + `RENAME`, so reads never fail mid-reset. Other tenants run in parallel. Measured: 8 tenants at once, 1,236 reads during locked agent runs with no error, 600 contended writes with no duplicate (docs/PERF.md, Concurrency; `tests/integration/test_concurrency.py`). Four responders at once give 5 checks and no duplicate edge (tested). Re-running an incident is safe (tested).
9. **"Can my own agent use this?"** Yes. The same 26-tool registry (28 tools with the two use cases) is served over MCP (`make mcp` for stdio, `--http` for Streamable HTTP; see `docs/MCP.md`) and HTTP (`GET /api/tools`, `POST /api/tenants/{t}/tools/{name}`). Each tool's schema comes from its pydantic args model, and its description from its docstring. MCP adds `respond_to_alert` and `reset_tenant` (28 tools), so an outside agent can run the whole story, ask the company brain (`ask`), or push its own events (`record_change`, `record_anomaly`, `raise_alert`) and respond to them. Our own agent runs are offered only 17 tools: `resolve_incident`, `my_questions` and the event tools are registered with `agent=False`, because an agent must not confirm its own fix or invent graph facts. The loop refuses them too if a planner names one.
10. **"Would it scale to thousands of services?"** The queries are bounded (6 hops, `LIMIT`s on paths and the flat log, a 2-hour window on suspects) and anchored on indexed ids. `Change.at` and `Anomaly.at` have range indexes, and `recent_changes` and `anomalies_between` use them (`GRAPH.EXPLAIN` shows `Node By Index Scan`). The first versions enumerated every dependency path and filtered afterwards; that took 2.6 s for the blast radius of a hub in a 1,000-service graph. The shipped queries start from the few candidates (the suspect search from the `Change.at` index), use `shortestPath` checked against edge validity, fall back to a traversal with a per-hop `WHERE` on the edge only when a retired edge is involved, and walk closures breadth-first with `CALL {}`: 45 ms for the same blast radius, with identical rows (`tests/integration/test_query_equivalence.py`, numbers in docs/PERF.md). Still to do: start `who_knows` from the service, cache the service map, lock per incident. Measured on the demo graph: 1 to 8 ms per tool, about 85 ms per incident (eval median, p95 126 ms).
11. **"Where do you use graph algorithms?"** In one decision, where it earns its place: who to warn first. `blast_radius` ranks the impacted services by criticality, PageRank (`algo.pageRank`) over the dependency graph as it was at alert time, tier 1 first, and comms' `warn_owners` sends a heads-up to the on-call of the top-ranked impacted teams nobody paged. Two things made that acceptable. The procedure runs on a point-in-time projection: FalkorDB's algorithms walk every edge and cannot filter `DEPENDS_ON` by `valid_from`/`valid_to`, so the live edges are copied into a scratch graph first (`topology_at`, `project_topology`, `criticality` in `algorithms.cypher`, all in the trace), and a test plants retired and future dependencies to show they add no rank. And PageRank is exact and deterministic. Cause-finding stays Cypher traversal: temporal variable-length paths, `shortestPath`, and for alert storms intersecting the alerting services' upstream closures ranked by total hops. We tried `algo.betweenness` for that ranking and rejected it: it is sampled, so changing `samplingSeed` reorders the services even with `samplingSize` above the node count, and a score that decides which change gets blamed has to be exact.
12. **"What if two things broke at once?"** Then neither is ruled out. Each supported suspect records which alerting services it can reach (`h.explained`). `conclude` outranks a suspect only if the leader explains every alerting service it explains; otherwise it becomes a co-cause. In `test_a_second_independent_cause_is_a_co_cause_not_ruled_out`, a cart deploy and a payments-gw config change both land before one storm of alerts on cart, refunds and checkout. Each change explains 2 of the 3 alerting services, so the nearer cart deploy leads and the payments-gw change is a co-cause ("also needed: it alone explains refunds"). Comms pages both owning teams, and the update has an "Also contributing:" line. The top shared upstream there is redis-cache, a cache all three alerting services reach: it only orders the checks, it is not a verdict. Limit: the leader is still one change, picked by rules (coverage, monitoring gaps, memory, hops, onset, recency, id, then the cascade rule), and a human's confirmation overrides it.
13. **"Is 92% good? What fails?"** Good on this generator, and we say why it is not a benchmark. Of 200 seeds the graph agent gets 184. On the 66 seeds with only the planted story it gets all 66; with a cascade victim (a nearer service deploys after the cause already went red) 48 of 51; with a silent middle hop 11 of 13. All 16 misses are one pattern: a random blip lands on decoy *c*'s service after *c*'s change, so *c* looks like a real, supported cause, and it then wins on a ranking rule: it is nearer, its anomaly came sooner, it is upstream of the truth and went red first (the cascade rule, 8 times), or the truth has a gap and *c* does not. EVAL.md lists every miss in the agent's own words from the trace. The honest caveats: the generator, the checks and the agent are written by the same team; the perturbations were added after mock judges called the first version (200/200) built to be passed, and the ranking rules changed in the same round by people who knew the perturbations, so it is not a blind test; and the perturbation rates are ours. The strongest baseline without the graph, an anomaly-aware change log, gets 134: the retired-dependency decoy fools it 55 times. Telling "red because of my change" from "red at the same time for another reason" is the next thing to fix (ARCHITECTURE section 6).
14. **"Is the company brain real or a demo?"** A demo of the mechanism on a small synthetic corpus: 34 docs (postmortems, design notes, decision records, runbook pages), 21 tickets, 41 chat messages and 3 initiatives, in the same graph as the services and incidents. `ask` runs FalkorDB full-text search over `Doc`, `Ticket` and `Message`, re-ranks the hits, walks `MENTIONS` / `DECIDES` / `SUPERSEDES` / `AUTHORED_BY` to name the change, the service, its team and the people, puts a current doc before the one it superseded, and cites every source. "Why was the payments gateway pool lowered?" leads with the Q4 cost review design note by Sana Brandt and links `chg:pgw-pool-1`; "who designed the checkout retries" names Bram Mensah's v2 design and says it replaces Dana Okafor's v1. It has no LLM, so it quotes sentences rather than summarising them, and its ranking (a prefix stemmer, a stopword list) has only been tried on this corpus. What a vector or keyword search alone would not give you is the part after the hit: whose change it was, who owns it now, and whether the doc is still current. Given a `user`, it also remembers the conversation in the graph: a follow-up's "it" is read as the previous question's subject, and "what did I ask about payments-gw" is answered from `Session` and `Question` nodes (`tests/integration/test_sessions.py`). Projects are nodes too: "what is the Q4 cost review changing and who is on it" walks the `Initiative` to its tickets, their changes, the incidents those are blamed for, the lead and the filers, and the ADRs that mention it (`tests/integration/test_initiatives.py`).

---

### Three more, about the product (Oct 16)

- **"Why is the MCP server the product and not the web page?"** An on-call engineer already lives in Claude Code,
  Slack and their alerting tool. The MCP server exposes the registry the agents use, 28 tools in all (`mcp_server/__init__.py`
  builds them from the registry), with instructions and two prompts, so Claude Code or Claude Desktop can work an alert
  or answer "who owns kafka" without our UI. The webhook (`POST .../alerts?respond=true`) and the Slack post
  (`adapters/slack.py`) close the loop headlessly. The inbox is where a human reviews and confirms. `docs/PRODUCT.md`.
- **"How do you know a model picks the right tool?"** `python -m scripts.mcp_pick` gives Claude only what an MCP
  client gets (instructions + tool list) and 17 plain requests; it picked right 17/17 (`docs/MCP_PICK.md`). Inside the
  product, every step records `by` (model id or `rules`) and the model's own one-line reason; `docs/LLM_RUN.md` has
  60/60 model decisions with 0 fallbacks.
- **"What stops a model from running up a bill or confirming its own guess?"** `RunBudget` caps tokens per run
  (`LLM_RUN_TOKEN_CAP`) and hands the rest to the rules; `resolve_incident` and the event tools are `agent=False`, so
  no agent run is ever offered them (`agents/registry.py`, enforced again in `agents/loop.py::_call`).

## 4. Exercises

All commands start from `graphhacks/` after `source /media/harsh/MyPassport1/devenv/env.sh`. `T1` is `1792036800` (act 1 alert time, 2026-10-15 09:30 IST). To put `tenant_acme` back to pristine at any time:

```bash
python -c "from oncall_brain.wiring import make_store; from oncall_brain.services.seeding import reset; print(reset(make_store(), 'acme'))"
```

**E1. See every query.** Run `python -m scripts.demo --tenant walk --cypher`. Find the step where the investigator gives up on memory, and the query that told it to. Clean up afterwards with `python -c "from oncall_brain.wiring import make_store; make_store().drop('walk')"`.

**E2. Run a query by hand.** The multi-hop path from the alert to the culprit:

```bash
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.RO_QUERY tenant_acme "MATCH p = (:Service {id:'svc:checkout'})-[:DEPENDS_ON*1..3]->(:Service {id:'svc:payments-gw'}) RETURN [n IN nodes(p) | n.name] AS path"
```

Expected: `[checkout, payments, payments-gw]`.

**E3. Time matters.** Is legacy-billing on checkout's path at alert time? (`CYPHER at=...` passes a parameter from redis-cli.)

```bash
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.RO_QUERY tenant_acme "CYPHER at=1792036800 MATCH p = (:Service {id:'svc:checkout'})-[:DEPENDS_ON*1..6]->(:Service {id:'svc:legacy-billing'}) WHERE all(r IN relationships(p) WHERE r.valid_from <= \$at AND (r.valid_to IS NULL OR r.valid_to > \$at)) RETURN [n IN nodes(p) | n.name] AS path"
```

Expected: no rows. Now remove the `WHERE all(...)` clause and run it again: you get `[checkout, legacy-billing]`. Then look at the edge itself:

```bash
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.RO_QUERY tenant_acme "MATCH (:Service {id:'svc:checkout'})-[d:DEPENDS_ON]->(:Service {id:'svc:legacy-billing'}) RETURN d.valid_from, d.valid_to"
```

`valid_to` is `1791777600`, three days before `T1`.

**E4. The flat baseline vs the graph.** Every change in the 2 hours before the alert, newest first (what a change log alone shows):

```bash
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.RO_QUERY tenant_acme "CYPHER at=1792036800 MATCH (c:Change)-[:CHANGED]->(s:Service) WHERE c.at >= \$at - 7200 AND c.at <= \$at RETURN c.id, s.name, (\$at - c.at) / 60 AS minutes_before ORDER BY c.at DESC"
```

Now only the changes on services checkout depends on at alert time (the `path_suspects` idea):

```bash
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.RO_QUERY tenant_acme "CYPHER at=1792036800 MATCH p = (:Service {id:'svc:checkout'})-[:DEPENDS_ON*0..6]->(s:Service) WHERE all(r IN relationships(p) WHERE r.valid_from <= \$at AND (r.valid_to IS NULL OR r.valid_to > \$at)) WITH s, min(length(p)) AS hops MATCH (c:Change)-[:CHANGED]->(s) WHERE c.at >= \$at - 7200 AND c.at <= \$at RETURN c.id, s.name, hops ORDER BY hops"
```

The first list starts with `chg:search-420`. The second has only `pricing-2140`, `cart-310` and `pgw-pool-1`.

**E5. Read-only is enforced by the database.**

```bash
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.RO_QUERY tenant_acme "MERGE (:Service {id:'x'})"
```

Expected: `graph.RO_QUERY is to be executed only on read-only queries`.

**E6. Agent history is in the graph.** Start the API (`make dev`), then in another shell:

```bash
curl -s -X POST localhost:8000/api/tenants/acme/reset
curl -s -X POST localhost:8000/api/tenants/acme/alerts/alert:checkout-latency/respond > /dev/null
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.RO_QUERY tenant_acme "MATCH (:Incident {id:'inc:checkout-latency'})-[:LOGGED]->(s:AgentStep) RETURN s.seq, s.role, s.tool, s.target ORDER BY s.seq"
```

Then run the `respond` curl again and re-run the query. Only `open_incident` and three handoffs are added, because the board already shows the work as done.

**E7. Break a verdict rule.** In `domain/verdict.py`, move the rollback check below the anomaly check (rule 3), then run `pytest -q tests/unit/test_verdict.py tests/integration/test_story.py`. Which test fails, and which act 1 decoy is now refuted for the wrong reason? Undo with `git checkout src/oncall_brain/domain/verdict.py`.
(Answer: no unit test fails, because `test_rollback_beats_everything` only checks the verdict, and its facts give the changed service an anomaly. `test_act1_finds_the_planted_cause_and_refutes_every_decoy` fails on `"rolled back" in reasons["chg:pricing-2140"]`: pricing is now refuted as "pricing showed no anomaly after the change". The verdict is still right, but the reason is wrong, and the reason is what the update tells humans. Moving the rollback check only below the path check changes nothing in act 1, because pricing is on a live path.)

**E8. Tune memory.** In `domain/planner.py`, set `RECALL_MIN_SCORE = 2` (same path, any symptom). Before running `make demo`, predict which run changes, and by how many investigator calls. Then check, and undo with `git checkout`.
(Answer: act 1 does not change. A weak recall now counts: `inc:1003` ("fraud-check degraded", symptom errors, fixed by a runbook for fraud-check deploys). Its runbook makes memory suspect `chg:fraud-512`, a healthy fraud-check deploy in act 2's window. Act 2 with memory goes from 3 to 4 investigator calls (the culprit is still check 1, but the second memory suspect is checked too). Act 2 without memory goes from 6 to 7 calls, and the culprit moves from check 2 to check 3, because the useless memory suspect is checked first. Act 3 gets shorter, for the wrong reason: `inc:0877` (refunds 500s, fixed by expanding the postgres-orders disk) now counts, its runbook is for postgres-orders config changes, so memory suspects `chg:pg-conn-3` first: 3 investigator calls instead of 6, and the update suggests "Expand the data volume" for a connection limit. That is why the threshold needs the same symptom as well as the same path.)

**E9. Index or scan?**

```bash
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.EXPLAIN tenant_acme "MATCH (c:Change {id:'chg:search-420'}) RETURN c"
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.EXPLAIN tenant_acme "MATCH (c:Change) WHERE c.at > 0 RETURN c"
```

Both use `Node By Index Scan`: the first the `id` index, the second the `Change.at` range index. Now a query that still scans:

```bash
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.EXPLAIN tenant_acme "MATCH (p:Person)-[:MEMBER_OF]->(t:Team) RETURN p.id"
```

It starts with `Node By Label Scan | (t:Team)`. `who_knows` begins this way, so it looks at every person. That is fine for 24 people, and it is the next thing to fix at scale (ARCHITECTURE 4.1).
