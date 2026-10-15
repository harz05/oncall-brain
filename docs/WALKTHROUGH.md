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
| 2 | 3 | `src/oncall_brain/datagen.py` (docstring and the act 1, act 2 and act 3 blocks) | The planted story: the real cause `chg:pgw-pool-1` (a payments-gw pool cut from 200 to 20), and four decoys, each built to be refuted by a different graph fact. Act 2 adds `chg:pay-77`, a healthy decoy one hop away. Act 3 is three alerts in 4 minutes with a postgres-orders cause. Two decoys are timed to fool a change log that watches anomalies: act 1's legacy-billing deploy goes red before payments-gw does, and act 3's subscriptions deploy blips right after it. Times are epoch ints around `T1` (09:30 IST). Noise is random but kept out of the act windows. |
| 3 | 2 | `domain/models.py` | Five small types. `ToolOutput` (summary, data, queries, highlight) is what every tool returns. `Decision` is what the planner returns. `TraceStep` is one line of the trace. |
| 4 | 2 | `ports/__init__.py` | Three Protocols. Note `read()` vs `write()`: reads are `GRAPH.RO_QUERY`. Queries are addressed by name. |
| 5 | 3 | `adapters/falkordb/queries.py`, `repository.py` | How `// name: x` blocks are loaded. `_run()` picks `ro_query` or `query`. One graph per tenant (`tenant_<name>`). `snapshot()` / `restore()` use `GRAPH.COPY` (retried on "could not fork"). `lock()` is the per-tenant Redis lock every agent run holds. `ensure_schema()` creates the `id` and `at` indexes. |
| 6 | 5 | `adapters/falkordb/queries/*.cypher` | Read `triage.cypher` (`blast_radius`, `on_call_for`), then `investigate.cypher` (`recall_similar`, `path_suspects`, `recent_changes`, `live_paths`, `any_path`, `anomaly_baseline`), then `board.cypher` (`incident_board`, `log_step`), then `comms_memory.cypher` (`update_facts`, `post_update`, `resolve_incident`), then `knowledge.cypher` (`who_knows`, `record_consult`). `events.cypher` holds the five live-event writes. Spot the same temporal filter everywhere: `r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)`. |
| 7 | 2 | `agents/registry.py` | `@tool` reads the name, docstring and args model from the function, so a tool is defined once. `call()` validates args. `agent=False` keeps a tool away from agent runs: `specs(agents_only=True)` is what the planner or LLM sees (no `resolve_incident`, no event tools); `specs()` is what the MCP clients and `GET /api/tools` see. |
| 8 | 4 | `services/tools.py` | Each tool = named queries + a `ToolOutput`. Spend most of the time on `check_hypothesis`: facts, `live_paths`, `any_path` only if needed, `anomalies_between`, pick the path the anomaly lit up most, then the pure `judge()`, then coverage in a storm, then `record_evidence`. Then `correlate_alerts` (which alerts are related, and where their upstreams converge) and `conclude` (several supported suspects, one leading cause). |
| 9 | 3 | `domain/verdict.py`, `domain/planner.py` | `judge()`: five rules in order. `leading()`: most alerts explained, then memory, then nearest, then newest. The planner: three functions of the board. `check_order`: memory first, then (in an alert storm) the shared upstream in convergence order, then fewest hops, then newest. `RECALL_MIN_SCORE = 3`, `STORM_WINDOW` = 15 min. |
| 10 | 2 | `agents/loop.py`, `services/board.py`, `services/respond.py` | The loop: board, decide, call, record. `incident_id` is always forced to the current incident; a tool error falls back to the planner; a role out of steps (40) hands off. `respond()` takes the tenant lock and chains the roles through handoffs. `outcome()` builds the result card from the graph (cause, ruled out, update) and the trace (counters), plus both baselines: the flat change log and the anomaly-aware one. |
| 11 | 1 | `tests/integration/test_story.py` | The product's claims as tests: decoys refuted for the right reasons, the baseline is wrong, memory makes act 2 shorter, read tools cannot write, tenants are isolated, concurrent responders don't duplicate edges, live events drive a new investigation, act 3 needs correlation, an unrelated alert is not folded in, a re-run still reports its cause. |

If time is left: `api/app.py` (thin handlers, error mapping, the Host / same-origin / token guard), `services/seeding.py` (rebuild from scratch, `Meta` fingerprint, reset), `mcp_server/` (the same registry over MCP, see `docs/MCP.md`), `wiring.py` (the only place adapters are chosen), `adapters/llm/openai_compat.py` (how an LLM planner falls back to the rules), `scenarios.py` and `scripts/eval.py` (the 200-scenario eval).

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
| 14 | comms | `page_on_call(svc:payments-gw)` | Bram Nakamura (@bram.nakamura, Payments). |
| 15 | comms | `who_knows(svc:payments-gw)` -> `who_knows` (RO), `record_consult` (W) | Sana Brandt (Payments): authored 3 changes to payments-gw and is on the owning team (score 9). Written as `CONSULTED {for_service, score}`. |
| 16 | comms | `blast_radius(svc:payments-gw)` | 7 services depend on payments-gw. The ones not already hit (payments, refunds, subscriptions) are "also at risk". |
| 17 | comms | `post_update` -> `incident_head`, `update_facts`, `refuted_hypotheses` (RO), `post_update` (W) | `domain/update.status_update()` writes the text, including "Ask: Sana Brandt (@sana.brandt, Payments) knows payments-gw best". The `Message` `CITES` the change, `ticket:CR-881`, `msg:pay-deploys-1` and `person:sana-brandt`. |
| 18 | comms | board -> done | Handoff to `human`. `respond()` ends and builds `outcome()`. |

**Outcome.** Root cause `chg:pgw-pool-1`, 4 refuted, 8 investigator calls, 5 checks, culprit on check 3. `outcome()` runs two baselines with no traversal. `recent_changes`: a flat change log blames `chg:search-420`, the newest change. `anomaly_baseline`: a change log that also watches anomalies blames `chg:legacy-193`, because legacy-billing went red at 08:45, before payments-gw. Both are wrong; only the retired `DEPENDS_ON` edge says checkout stopped calling legacy-billing.

**Human resolve.** `POST .../incidents/inc:checkout-latency/resolve {"change_id": "chg:pgw-pool-1"}` -> `resolve()` -> `resolve_incident` tool. `change_info` (RO), then `domain/update.learned_runbook()`, then the `resolve_incident` query (W). It writes `CAUSED_BY`, `MERGE`s `Runbook rb:payments-gw:config` (kind `config`, uses 1, successes 1), `FIXED_WITH` and `FOR_SERVICE`, and marks the hypothesis `confirmed`.

**Act 2** (`alert:refunds-latency`, three days later). `recall_similar` now finds `inc:checkout-latency`: its cause service, payments-gw, is on refunds -> payments -> payments-gw, and the symptom is the same, so the score is 3. `memory_suspects` follows `RECALLS` -> `inc:checkout-latency` -> `FIXED_WITH` -> `rb:payments-gw:config` -> `FOR_SERVICE` -> payments-gw, and returns the config changes on payments-gw in the window: `chg:pgw-pool-2`. The hypothesis carries `runbook: rb:payments-gw:config`. One `check_hypothesis` gives SUPPORTS. That is 3 investigator calls instead of 6, 1 check instead of 4, and the culprit on check 1 instead of 2. (Without memory, nearest-first checking tries `chg:pay-77` first: a newer payments deploy one hop away, with no anomaly.) The status update now includes "Next action: Revert the config change on payments-gw (last time: ...) (runbook 'Revert the config change on payments-gw', worked 1 of 1 times)". Had the check refuted it, `record_evidence` would have added 1 to the runbook's `uses` (once), lowering its confidence. The anomaly-aware baseline also gets act 2 right (payments-gw is the first to go red), so act 2 shows memory and speed, not accuracy over that baseline.

**Act 3** (`alert:subscriptions-latency`, two days after act 2). Checkout and refunds alerted 4 and 2 minutes earlier, so the board's `storm` count is 2 and triage calls `correlate_alerts` before anything else: `storm_alerts`, then `storm_upstream` (for each alerting service, every service it reaches over live edges, with hop counts, and whether it went red). Both other alerts share red upstream services with subscriptions (payments, postgres-orders), so both are folded in; an unrelated alert sharing only a quiet cache would not be. The services all three reach are ranked by total hops: payments 3, postgres-orders 5, fraud-check 6, payments-gw 6, redis-cache 8, kafka 9. `record_correlation` writes `CORRELATED_WITH` and `SHARED_UPSTREAM {rank, hops}`. The investigator checks `chg:pg-conn-3` first, the only suspect on the shared upstream: SUPPORTS, explains 3 of 3 alerts. `chg:subs-88` is SUPPORTED too (subscriptions blipped 2 minutes after the deploy) but explains 1 of 3 (`storm_unexplained` finds no live path from checkout or refunds to subscriptions). `chg:search-430` is refuted (no path). Two supported suspects, so the investigator calls `conclude`: `leading()` keeps `chg:pg-conn-3` and `record_outranked` marks `chg:subs-88` outranked ("chg:pg-conn-3 explains 3 of the correlated alerts, this change 1"). On a fresh graph: 17 steps, 6 investigator calls, 3 checks, culprit on check 1 (after acts 1 and 2 in the UI, a `hypothesize_from_memory` step that finds nothing makes it 18 and 7). The flat change log blames `chg:search-430`, and the anomaly-aware one `chg:subs-88`, because subscriptions went red first. `make demo` then reruns act 3 with correlation switched off: both suspects explain the one alert, the nearer `chg:subs-88` leads, and the answer is wrong.

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
1. The company is a graph: teams `OWNS` services, people are `MEMBER_OF` teams and hold time-bounded `ON_CALL` shifts, services `DEPENDS_ON` each other with `valid_from` / `valid_to`, and every deploy or config `Change` `CHANGED` a service and was `AUTHORED_BY` a person. A ticket `REQUESTED` it, and a chat message `MENTIONS` it.
2. An `Incident` is the agents' shared board: it is `TRIGGERED_BY` an alert, and the agents attach `IMPACTS`, `PAGED`, `CONSULTED`, `Hypothesis` nodes (each `SUSPECTS` a change, and `Evidence` `SUPPORTS` or `REFUTES` it), their own `AgentStep` history (`LOGGED`), and a status update that `CITES` its sources.
3. A resolved incident is memory: it is `CAUSED_BY` a change and `FIXED_WITH` a `Runbook` (which is `FOR_SERVICE` a service and a change kind). A new incident `RECALLS` old ones whose cause service is still on its live dependency path, and their runbooks pick its first suspects.

### Why FalkorDB is indispensable (what breaks without which query)

| Feature | Query | Without it |
|---|---|---|
| Who is hurt, who else is at risk | `blast_radius` (reverse `DEPENDS_ON*1..6`, edges live at alert time) | No impact list, no "also at risk" warning. |
| Which changes could explain the alert | `path_suspects` (`DEPENDS_ON*0..6` at alert time, then `CHANGED` in the window) | Only the flat change log is left, and it blames `chg:search-420`, which is wrong. |
| Ruling out decoys | `live_paths`, `any_path` (`shortestPath`), `anomalies_between` | You cannot tell "retired dependency" from "never connected", or check that the symptom travelled the path. |
| Alert storms | `storm_alerts`, `storm_upstream` (upstream closures with hops, intersected), `storm_unexplained` (coverage), `record_outranked` | Each alert is investigated alone, and act 3 blames the subscriptions deploy. |
| Who to page | `on_call_for` (`ON_CALL` shift valid at alert time) | No owner and no page. |
| Agent coordination | `incident_board`, `log_step` | The planner has no input at all. It has no state outside the graph. |
| Memory | `recall_similar`, `memory_suspects` (recall -> runbook -> service -> changes of that kind), `resolve_incident` | Act 2 takes the long road (6 calls and 4 checks instead of 3 and 1). |
| Sources and company brain | `update_facts`, `change_story`, `who_knows` | The update cannot cite the ticket or chat, cannot say who to ask, and "who knows payments-gw" has no answer. |
| Keeping knowledge current | `record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency` (`events.cypher`) | New facts would need a re-seed before an investigation could use them. |
| Safety and tenancy | `GRAPH.RO_QUERY`, one graph per tenant, `GRAPH.COPY` | Read tools could write, tenants would share data, and demo resets would mean re-seeding. |

The one-liner: take FalkorDB out and nothing runs, not because a database is missing, but because every decision the agents make is a query result.

### Eleven likely questions, with short answers

1. **"You planted the answer. Isn't this a hardcoded pipeline?"** The story is planted, so we know the right answer. The agent still has to find it. The planner only sees the board and branches on what queries return. Four decoys are refuted for four different graph reasons, shown with their Cypher. The flat baseline gets it wrong, and so does an anomaly-aware change log in acts 1 and 3 (it gets act 2 right). Memory changes the path in act 2. The eval (`make eval`, `docs/EVAL.md`) runs the same code on 200 random incidents with their own decoys: the graph agent is right in 200, an anomaly-aware change log in 141 (it is fooled only by the retired-dependency decoy), keyword matching in 59, the flat change log in 0.
2. **"networkx or SQL could do this."** For one traversal, maybe. Here, temporal edges filtered at alert time, persistent state that three roles read and write, memory that outlives the process, `GRAPH.RO_QUERY` and per-tenant graphs are used together, in one database, by every step. In SQL, the variable-length temporal paths become recursive CTEs, and you would rebuild the rest yourself.
3. **"Where is the AI? The planner is rules."** Yes, the default planner is deterministic, and the UI says so. That is a choice: it runs with no key, it is repeatable, and the graph decides every branch. An LLM can plug into the same `LLMProvider` port, gets the same board and tools, and falls back to the rules if its answer is invalid. The interesting part is the context layer, and that is the same either way.
4. **"Why not vector search for similar incidents?"** Incident titles all look alike ("p99 latency"). What matters is whether the old cause is still upstream of the new alert, at the new alert's time. That is a path query, not a text distance. It needs no model, works offline, and the path is the explanation. Vectors could be a tie-breaker later (ADR-004).
5. **"How do the agents actually coordinate?"** Only through the graph. Each decision starts by reading the incident board. Each step is written as an `AgentStep`. A handoff is a step too. The investigator knows what triage did because it is in the graph, not because a variable was passed.
6. **"How do you keep knowledge current?"** Facts that change carry validity times (`DEPENDS_ON valid_from / valid_to`, `ON_CALL start / end`). Queries filter by the alert time. Old facts stay as history but do not count. That is how the retired legacy-billing dependency is ruled out.
7. **"What stops an agent from corrupting the graph?"** Read tools use `GRAPH.RO_QUERY`, so FalkorDB refuses writes (there is a test for it). Writes go through a few narrow, named, parameterised queries that `MERGE` on stable ids. Cause and runbook memory are written only when a human confirms the fix.
8. **"Multi-tenant? Concurrent?"** One graph per tenant, so data and memory are isolated (tested). That is isolation, not access control: there is no per-user auth, and the demo is meant for localhost (`API_TOKEN` is all-or-nothing). Each FalkorDB query is atomic, but two concurrent `MERGE`s of the same edge can both create it. So every agent run (respond, resolve, reset) holds a per-tenant Redis lock, shared by the API, MCP and scripts. Reads stay concurrent and other tenants run in parallel. Four responders at once give 5 checks and no duplicate edge (tested). Re-running an incident is safe (tested).
9. **"Can my own agent use this?"** Yes. The same 21-tool registry is served over MCP (`make mcp` for stdio, `--http` for Streamable HTTP; see `docs/MCP.md`) and HTTP (`GET /api/tools`, `POST /api/tenants/{t}/tools/{name}`). Each tool's schema comes from its pydantic args model, and its description from its docstring. MCP adds `respond_to_alert` and `reset_tenant`, so an outside agent can run the whole story, or push its own events (`record_change`, `record_anomaly`, `raise_alert`) and respond to them. Our own agent runs are offered only 15 tools: `resolve_incident` and the event tools are registered with `agent=False`, because an agent must not confirm its own fix or invent graph facts.
10. **"Would it scale to thousands of services?"** The queries are bounded (6 hops, `LIMIT`s on paths and the flat log, a 2-hour window on suspects) and anchored on indexed ids. `Change.at` and `Anomaly.at` have range indexes, and `recent_changes` and `anomalies_between` use them (`GRAPH.EXPLAIN` shows `Node By Index Scan`). Next: start the suspect search from the few changes in the window, start `who_knows` from the service instead of scanning every person, cache the service map, and lock per incident instead of per tenant. Measured today: 1 to 7 ms per tool, about 65 ms per incident (eval median).
11. **"Where do you use graph algorithms?"** We don't, on purpose. The product's graph work is Cypher traversal: temporal variable-length paths, `shortestPath`, and, for alert storms, intersecting the alerting services' upstream closures and ranking the result by total hops. We tried FalkorDB's `algo.betweenness` for that ranking and rejected it for two reasons. It is sampled: on this graph, changing `samplingSeed` reorders the services even with `samplingSize` above the node count (api-gateway is outside the top 6 with seed 1 and third with seed 2). And it filters by label and relationship type, not by property, so it cannot leave out `DEPENDS_ON` edges retired before the alert. A score that decides which change gets blamed has to be exact and respect time. Summed hops over live edges are both, and the trace can show them. PageRank on 25 services would be decoration.

---

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
