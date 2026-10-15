# Walkthrough: learn the codebase in 30 minutes

This is for Harsh, and for anyone who has to explain this project without having written it line by line. Read it with the code open. Section 1 is the reading order. Section 2 traces one alert through the real functions and queries. Section 3 is what to say to a judge. Section 4 has exercises you can run on this machine.

Before you start (two minutes, from `graphhacks/`):

```bash
source /media/harsh/MyPassport1/devenv/env.sh
make db      # FalkorDB on :6379 (no-op if it is already up)
make seed    # graph tenant_acme + pristine copy pristine_acme
make demo    # the whole two-act story in the terminal; ends with DEMO OK
```

Keep the `make demo` output on screen. Every section below points at lines in it.

---

## 1. Reading order (about 30 minutes)

| # | Min | File | What to look for |
|---|---|---|---|
| 1 | 3 | `docs/decisions/ADR-001-idea.md` | The two-act story, the decoys, and why "the plan lives in the graph". This is the pitch. |
| 2 | 3 | `src/oncall_brain/datagen.py` (docstring and the act 1 and act 2 blocks) | The planted story: the real cause `chg:pgw-pool-1` (a payments-gw pool cut from 200 to 20), and four decoys, each built to be refuted by a different graph fact. Times are epoch ints around `T1` (09:30 IST). Noise is random but kept out of the act windows. |
| 3 | 2 | `domain/models.py` | Five small types. `ToolOutput` (summary, data, queries, highlight) is what every tool returns. `Decision` is what the planner returns. `TraceStep` is one line of the trace. |
| 4 | 2 | `ports/__init__.py` | Three Protocols. Note `read()` vs `write()`: reads are `GRAPH.RO_QUERY`. Queries are addressed by name. |
| 5 | 3 | `adapters/falkordb/queries.py`, `repository.py` | How `// name: x` blocks are loaded. `_run()` picks `ro_query` or `query`. One graph per tenant (`tenant_<name>`). `snapshot()` / `restore()` use `GRAPH.COPY`. |
| 6 | 5 | `adapters/falkordb/queries/*.cypher` | Read `triage.cypher` (`blast_radius`, `on_call_for`), then `investigate.cypher` (`recall_similar`, `path_suspects`, `recent_changes`, `live_paths`, `any_path`), then `board.cypher` (`incident_board`, `log_step`), then `comms_memory.cypher` (`resolve_incident`). Spot the same temporal filter everywhere: `r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)`. |
| 7 | 2 | `agents/registry.py` | `@tool` reads the name, docstring and args model from the function, so a tool is defined once. `call()` validates args. `specs()` is what the LLM, the MCP clients and `GET /api/tools` see. |
| 8 | 4 | `services/tools.py` | Each tool = named queries + a `ToolOutput`. Spend most of the time on `check_hypothesis`: facts, `live_paths`, `any_path` only if needed, `anomalies_between`, pick the path the anomaly lit up most, then the pure `judge()`, then `record_evidence`. |
| 9 | 3 | `domain/verdict.py`, `domain/planner.py` | `judge()`: five rules in order. The planner: three functions of the board. `check_order`: memory first, then fewest hops, then newest. `RECALL_MIN_SCORE = 3`. |
| 10 | 2 | `agents/loop.py`, `services/board.py`, `services/respond.py` | The loop: board, decide, call, record. `respond()` chains the roles through handoffs. `outcome()` builds the result card and the flat baseline. |
| 11 | 1 | `tests/integration/test_story.py` | The product's claims as tests: decoys refuted for the right reasons, the baseline is wrong, memory makes act 2 shorter, read tools cannot write, tenants are isolated. |

If time is left: `api/app.py` (thin handlers and error mapping), `mcp_server/` (the same registry over MCP, see `docs/MCP.md`), `wiring.py` (the only place adapters are chosen), `adapters/llm/openai_compat.py` (how an LLM planner falls back to the rules), `scenarios.py` and `scripts/eval.py` (the 200-scenario eval).

---

## 2. The life of one alert

Act 1, `alert:checkout-latency` ("checkout p99 latency above 2s"), on the default seed. The step numbers match `make demo`.

**Entry.** From the UI: `POST /api/tenants/acme/alerts/alert:checkout-latency/respond`. `api/app.py::respond` checks the tenant exists (`tenant_repo`), then calls `services/respond.py::respond(repo, alert_id, llm)`. `make demo` calls the same `respond()` directly.

| Step | Role | Function -> named queries | What the graph returned |
|---|---|---|---|
| 1 | triage | `respond()` -> `open_incident` tool -> `open_incident` (W) | `MERGE (i:Incident {id:'inc:checkout-latency'})-[:TRIGGERED_BY]->(alert)`. This node is the board. `log_step` writes `AgentStep` #1. |
| 2 | triage | `run_role` -> `load_board` -> `incident_board` (RO). `planner.triage`: blast radius not run yet. -> `blast_radius` tool -> `incident_head`, `blast_radius` (RO), `record_impacts` (W) | 3 services depend on checkout at alert time: api-gateway (1 hop), web-frontend and mobile-bff (2 hops). Written as `IMPACTS` edges. |
| 3 | triage | board -> `page_on_call` -> `on_call_for` (RO), `record_page` (W) | The `ON_CALL {start, end}` shift covering 09:30 IST: Ravi Moreau (@ravi, Checkout). `PAGED` edge. |
| 4 | triage | board -> triage is done | `AgentStep` with tool `handoff`, target `investigator`. |
| 5 | investigator | board -> `recall_similar` (RO), `record_recalls` (W) | `inc:0911` "Checkout slow during flash sale": its cause service (inventory) is on checkout's live path and it has the same symptom, so the score is 3. `RECALLS` edge. |
| 6 | investigator | board shows recall score 3 -> `hypothesize_from_memory` -> `memory_suspects` (RO) | 0 rows: no change on inventory in the 2-hour window. Memory did not help, and the planner sees that on the next board. |
| 7 | investigator | board: no open hypotheses -> `propose_hypotheses` -> `path_suspects`, `recent_changes` (RO), `add_hypotheses` (W) | On the dependency path: `chg:cart-310`, `chg:pricing-2140` (1 hop), `chg:pgw-pool-1` (2 hops). From the flat log: `chg:search-420` (newest anywhere, 8 min before) and `chg:legacy-193`. Five open `Hypothesis` nodes. |
| 8 | investigator | `check_hypothesis(cart-310)` -> `hypothesis_facts`, `live_paths`, `anomalies_between` (RO), `record_evidence` (W) | Path exists, but cart had no anomaly: REFUTES (rule 3). |
| 9 | investigator | `check_hypothesis(pricing-2140)` | Rolled back 70 min before the alert: REFUTES (rule 1). |
| 10 | investigator | `check_hypothesis(pgw-pool-1)` | Live path checkout -> payments -> payments-gw, and anomalies on all three after the change: SUPPORTS (rule 5). |
| 11 | investigator | `check_hypothesis(search-420)`, also `any_path` | No path at all from checkout to search: REFUTES (rule 2). |
| 12 | investigator | `check_hypothesis(legacy-193)`, also `any_path` | A path exists only through a `DEPENDS_ON` edge retired 3 days ago: REFUTES with "dependency retired" (rule 2). |
| 13 | investigator | board: one supported, none open | Hand off to comms. `cause_service` = payments-gw is now on the board. |
| 14 | comms | `page_on_call(svc:payments-gw)` | Bram Nakamura (@bram, Payments). |
| 15 | comms | `blast_radius(svc:payments-gw)` | 7 services depend on payments-gw. The ones not already hit (payments, refunds, subscriptions) are "also at risk". |
| 16 | comms | `post_update` -> `update_facts`, `refuted_hypotheses` (RO), `post_update` (W) | `domain/update.status_update()` writes the text. The `Message` `CITES` the change, `ticket:CR-881` and `msg:pay-deploys-1`. |
| 17 | comms | board -> done | Handoff to `human`. `respond()` ends and builds `outcome()`. |

**Outcome.** Root cause `chg:pgw-pool-1`, 4 refuted, 8 investigator calls, 5 checks. `outcome()` re-runs `recent_changes` for the baseline: a flat change log blames `chg:search-420`, which is wrong.

**Human resolve.** `POST .../incidents/inc:checkout-latency/resolve {"change_id": "chg:pgw-pool-1"}` -> `resolve()` -> `resolve_incident` tool. `change_info` (RO), then `domain/update.learned_runbook()`, then the `resolve_incident` query (W). It writes `CAUSED_BY`, `MERGE`s `Runbook rb:payments-gw:config` (successes 1), `FIXED_WITH` and `FOR_SERVICE`, and marks the hypothesis `confirmed`.

**Act 2** (`alert:refunds-latency`, three days later). `recall_similar` now finds `inc:checkout-latency`: its cause service, payments-gw, is on refunds -> payments -> payments-gw, and the symptom is the same, so the score is 3. `memory_suspects` returns `chg:pgw-pool-2`. One `check_hypothesis` gives SUPPORTS. That is 3 investigator calls instead of 5, and 1 check instead of 3. The status update now includes "Runbook: Revert the config change on payments-gw (worked 1x)".

One query to read slowly, `live_paths` (in `investigate.cypher`):

```cypher
MATCH p = (:Service {id: $origin})-[:DEPENDS_ON*0..6]->(:Service {id: $target})   // every path up to 6 hops
WHERE all(r IN relationships(p)
          WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)) // only edges live at alert time
WITH p ORDER BY length(p) LIMIT 20                                                  // shortest first, bounded
RETURN [n IN nodes(p) | n.id] AS path
```

`*0..6` (not `1..`) lets a change on the alerting service itself match with a path of length 0. `check_hypothesis` then looks up anomalies on every service on these paths and judges the path the anomaly lit up most. If the query returns nothing, `any_path` runs `shortestPath` with no time filter. If that finds a path, the dependency existed once but was retired. That difference is the whole legacy-billing decoy. (`live_path`, the same query with `LIMIT 1`, backs the `dependency_path` tool.)

---

## 3. How to explain it to a judge

### The graph model in three sentences
1. The company is a graph: teams `OWN` services, people are `MEMBER_OF` teams and hold time-bounded `ON_CALL` shifts, services `DEPENDS_ON` each other with `valid_from` / `valid_to`, and every deploy or config `Change` `CHANGED` a service, was `AUTHORED_BY` a person, `REQUESTED` by a ticket and `MENTIONED` in chat.
2. An `Incident` is the agents' shared board: it is `TRIGGERED_BY` an alert, and the agents attach `IMPACTS`, `PAGED`, `Hypothesis` nodes (each `SUSPECTS` a change and is `SUPPORTED` or `REFUTED` by `Evidence`), their own `AgentStep` history, and a status update that `CITES` its sources.
3. A resolved incident is memory: it is `CAUSED_BY` a change and `FIXED_WITH` a `Runbook`, and a new incident `RECALLS` old ones whose cause service is still on its live dependency path.

### Why FalkorDB is indispensable (what breaks without which query)

| Feature | Query | Without it |
|---|---|---|
| Who is hurt, who else is at risk | `blast_radius` (reverse `DEPENDS_ON*1..6`, edges live at alert time) | No impact list, no "also at risk" warning. |
| Which changes could explain the alert | `path_suspects` (`DEPENDS_ON*0..6` at alert time, then `CHANGED` in the window) | Only the flat change log is left, and it blames `chg:search-420`, which is wrong. |
| Ruling out decoys | `live_paths`, `any_path` (`shortestPath`), `anomalies_between` | You cannot tell "retired dependency" from "never connected", or check that the symptom travelled the path. |
| Who to page | `on_call_for` (`ON_CALL` shift valid at alert time) | No owner and no page. |
| Agent coordination | `incident_board`, `log_step` | The planner has no input at all. It has no state outside the graph. |
| Memory | `recall_similar`, `memory_suspects`, `resolve_incident` | Act 2 takes the long road (5 calls and 3 checks instead of 3 and 1). |
| Sources and company brain | `update_facts`, `change_story`, `who_knows` | The update cannot cite the ticket or chat, and "who knows payments-gw" has no answer. |
| Safety and tenancy | `GRAPH.RO_QUERY`, one graph per tenant, `GRAPH.COPY` | Read tools could write, tenants would share data, and demo resets would mean re-seeding. |

The one-liner: take FalkorDB out and nothing runs, not because a database is missing, but because every decision the agents make is a query result.

### Ten likely questions, with short answers

1. **"You planted the answer. Isn't this a hardcoded pipeline?"** The story is planted, so we know the right answer. The agent still has to find it. The planner only sees the board and branches on what queries return. Four decoys are refuted for four different graph reasons, shown with their Cypher. The flat baseline gets it wrong. Memory changes the path in act 2. The eval (`make eval`, `docs/EVAL.md`) runs the same code on 200 random incidents with their own decoys: the graph agent is right in 200, the flat change log in 0, keyword matching in 59.
2. **"networkx or SQL could do this."** For one traversal, maybe. Here, temporal edges filtered at alert time, persistent state that three roles read and write, memory that outlives the process, `GRAPH.RO_QUERY` and per-tenant graphs are used together, in one database, by every step. In SQL, the variable-length temporal paths become recursive CTEs, and you would rebuild the rest yourself.
3. **"Where is the AI? The planner is rules."** Yes, the default planner is deterministic, and the UI says so. That is a choice: it runs with no key, it is repeatable, and the graph decides every branch. An LLM can plug into the same `LLMProvider` port, gets the same board and tools, and falls back to the rules if its answer is invalid. The interesting part is the context layer, and that is the same either way.
4. **"Why not vector search for similar incidents?"** Incident titles all look alike ("p99 latency"). What matters is whether the old cause is still upstream of the new alert, at the new alert's time. That is a path query, not a text distance. It needs no model, works offline, and the path is the explanation. Vectors could be a tie-breaker later (ADR-004).
5. **"How do the agents actually coordinate?"** Only through the graph. Each decision starts by reading the incident board. Each step is written as an `AgentStep`. A handoff is a step too. The investigator knows what triage did because it is in the graph, not because a variable was passed.
6. **"How do you keep knowledge current?"** Facts that change carry validity times (`DEPENDS_ON valid_from / valid_to`, `ON_CALL start / end`). Queries filter by the alert time. Old facts stay as history but do not count. That is how the retired legacy-billing dependency is ruled out.
7. **"What stops an agent from corrupting the graph?"** Read tools use `GRAPH.RO_QUERY`, so FalkorDB refuses writes (there is a test for it). Writes go through a few narrow, named, parameterised queries that `MERGE` on stable ids. Cause and runbook memory are written only when a human confirms the fix.
8. **"Multi-tenant? Concurrent?"** One graph per tenant, so data and memory are isolated (tested). FalkorDB runs reads concurrently and serialises writes per graph, and each query is atomic. Writes are idempotent `MERGE`s, and the step number is computed inside the write. Re-running an incident is safe (tested).
9. **"Can my own agent use this?"** Yes. The same tool registry is served over MCP (`make mcp` for stdio, `--http` for Streamable HTTP; see `docs/MCP.md`) and HTTP (`GET /api/tools`, `POST /api/tenants/{t}/tools/{name}`). Each tool's schema comes from its pydantic args model, and its description from its docstring. MCP adds `respond_to_alert` and `reset_tenant`, so an outside agent can run the whole story.
10. **"Would it scale to thousands of services?"** The queries are bounded (6 hops) and indexed on ids. Next we would add range indexes on `Change.at` and `Anomaly.at` (today the time-window filter scans all changes; `GRAPH.EXPLAIN` shows it), start the suspect search from the few changes in the window, cache the service map, and add an incident lease for concurrent responders. Tenants already shard writes. Measured today: 1 to 15 ms per tool, about 140 ms per incident.

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

**E7. Break a verdict rule.** In `domain/verdict.py`, move the rollback check below the path check, then run `pytest -q tests/unit/test_verdict.py`. Which test fails, and which act 1 decoy would now be refuted for the wrong reason? Undo with `git checkout src/oncall_brain/domain/verdict.py`.
(Answer: `test_rollback_beats_everything` fails. `chg:pricing-2140` would now be refuted as "pricing showed no anomaly" instead of "rolled back before the alert", so the integration test fails too. The verdict is still right, but the reason is wrong, and the reason is what the update tells humans.)

**E8. Tune memory.** In `domain/planner.py`, set `RECALL_MIN_SCORE = 2` (same path, any symptom). Before running `make demo`, predict which run changes, and by how many investigator calls. Then check, and undo with `git checkout`.
(Answer: acts 1 and 2 with memory do not change. Act 2 without memory goes from 5 to 6 investigator calls: a weak recall (`inc:1003`, redis-cache, a different symptom) now triggers a useless memory step. That is why the threshold needs the same symptom as well as the same path.)

**E9. Index or scan?**

```bash
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.EXPLAIN tenant_acme "MATCH (c:Change {id:'chg:search-420'}) RETURN c"
$FALKORDB_BIN/redis-cli -p 6379 GRAPH.EXPLAIN tenant_acme "MATCH (c:Change) WHERE c.at > 0 RETURN c"
```

The first uses `Node By Index Scan`, the second a `Node By Label Scan`. That is the first thing to fix at scale (ARCHITECTURE 4.1).
