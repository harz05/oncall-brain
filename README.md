# On-call Brain

Incident agents that reason over a FalkorDB graph and remember what fixed things.

When an alert fires, three agents (triage, investigator, comms) work one incident together through a shared graph: who is hurt, which change broke it, who to page, what to tell people. When a human confirms the fix, the graph remembers it, and the next similar incident is solved in a fraction of the steps.

**Tracks entered:** 01 Agents That Act on Connected Data, 02 Agent Memory and Coordination, 03 Company Brain.
Built for Graph Hacks (WeMakeDevs x FalkorDB), October 2026. All data is synthetic (seeded generator, fake names).

<!-- DEMO VIDEO LINK: add after recording -->

![Act 2: the refunds incident solved from act 1's memory, 8 -> 3 investigator calls](docs/img/act2.png)

## The story the demo tells

**Act 1, 09:30: "checkout p99 latency above 2s".**
- Triage walks `DEPENDS_ON` backwards: checkout, api-gateway, web-frontend and mobile-bff are hurt. It pages whoever is on call for checkout (rotation edges in the graph).
- The investigator recalls past incidents first. An old checkout incident was caused by inventory, but inventory has no change today, so it moves on.
- It lists every change from the last 2 hours on services checkout depends on at alert time, plus the newest changes anywhere (what a flat change log would blame). Each suspect becomes a `Hypothesis` on the incident and is tested against the graph:

| Suspect | Verdict | Graph fact that decided it |
|---|---|---|
| search deploy, 8 min before (the newest change anywhere) | refuted | no `DEPENDS_ON` path from checkout to search |
| legacy-billing deploy | refuted | checkout's dependency on it was retired 3 days ago (`valid_to`) |
| pricing deploy | refuted | rolled back before the alert |
| cart deploy | refuted | cart shows no anomaly after the change |
| **payments-gw config change** (pool 200 -> 20) | **supported** | anomaly propagates payments-gw -> payments -> checkout, two hops |

- Comms pages the payments team, asks the graph who knows payments-gw best (`who_knows`, recorded as `CONSULTED`), warns refunds and subscriptions (they depend on the same gateway), and posts a status update. The update names who to ask and cites the change ticket, the chat message that announced it and that person.
- A human confirms. The incident gets `CAUSED_BY` the change, and a `Runbook` is learned for (payments-gw, config).

**Act 2, three days later: "refunds p99 latency above 2s".**
Recall finds act 1 by structure, because payments-gw is on refunds' live dependency path and the symptom is the same. Text similarity plays no part. The runbook that fixed act 1 is for config changes on payments-gw, so the investigator suspects the new payments-gw config change first and confirms it in one check: **8 investigator calls on act 1 (culprit on check 3), 3 on act 2 (culprit on check 1).** The update adds "Next action: Revert the config change on payments-gw ... worked 1 of 1 times". Replayed on a graph without act 1's memory, act 2 takes 6 calls and checks 4 hypotheses: nearest-first checking tries a newer, healthy payments deploy (`chg:pay-77`, 1 hop away) before the culprit (check 2).

**Act 3, two days later: three alerts in 4 minutes** (checkout, refunds, subscriptions).
Triage sees other alerts in the last 15 minutes on the board and calls `correlate_alerts` first. It folds the other two alerts into the incident (`CORRELATED_WITH`) and finds the services all three depend on at alert time (payments, payments-gw, fraud-check, kafka, postgres-orders, redis-cache). It ranks them with FalkorDB's `algo.betweenness` (paths converge on payments) and stores them as `SHARED_UPSTREAM {rank, betweenness}`. The investigator checks suspects on that shared upstream first: the postgres-orders config change (max_connections 500 -> 150) is supported on check 1. A subscriptions deploy 10 minutes before the alert is refuted: it "cannot explain the alerts on refunds, checkout (they do not depend on subscriptions)". Without correlation, the same planner blames that subscriptions deploy (`make demo` prints this ablation). Two limits: betweenness orders suspects inside the shared upstream, but here only one suspect sits there, so the shared-upstream set and the storm rule decide act 3. And `algo.betweenness` counts all `DEPENDS_ON` edges, retired ones too (FalkorDB's algorithms filter by label and type, not by property); the shared-upstream set uses live edges only.

## Why the graph is not decoration

| What the agents do | FalkorDB feature doing the work | Without it |
|---|---|---|
| Blast radius, suspects, recall | variable-length `DEPENDS_ON*` traversals filtered per relationship by `valid_from`/`valid_to` at alert time | no multi-hop suspects; retired dependencies blamed |
| Refute "no path" suspects | `shortestPath` in `WITH` | the flat baseline's wrong answer stands |
| Alert storms | shared upstream of every alerting service (live edges), ranked by the graph algorithm `algo.betweenness`; a suspect that cannot reach every alerting service is refuted | each alert is investigated alone, and act 3 blames the subscriptions deploy |
| Shared state and handoffs | the `Incident` board: `Hypothesis`, `Evidence` (`SUPPORTS`/`REFUTES`), `AgentStep` nodes, re-read before every decision | agents can't coordinate; the planner has nothing to decide from |
| Memory | `RECALLS` -> `FIXED_WITH` -> `Runbook` -`FOR_SERVICE`-> service picks the first suspects; `uses`/`successes` set the runbook's confidence; persisted per tenant | act 2 is as slow as act 1 |
| Company brain | `who_knows` (ownership + authored changes + incidents paged for), `change_story` (ticket, chat, author, incidents) | no sourced answers, nobody to ask |
| Keeping knowledge current | event tools write changes, anomalies, alerts and dependency start/end (`valid_from`/`valid_to`) as they happen | the next investigation works from stale facts |
| Safety, multi-tenancy, repeatable demo | `GRAPH.RO_QUERY` for every read, one graph per tenant, `GRAPH.COPY` for resets | |

The full query catalogue is in [docs/QUERIES.md](docs/QUERIES.md); the data model in [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

### Measured, not just claimed

On 200 generated incidents (random alert service, random cause 0-3 hops upstream, planted decoys of every kind above), from [docs/EVAL.md](docs/EVAL.md):

| method | uses the graph | correct |
|---|---|---|
| **On-call Brain** (deterministic planner) | yes | **200/200** |
| anomaly-aware change log: change behind the first service to go red | no | 141/200 (fooled only by the retired-dependency decoy) |
| keyword match: change summary vs alert name | no | 59/200 |
| flat change log: newest change in the window | no | 0/200 (its pick is always a planted decoy) |

The eval has single-alert incidents only; act 3's storm is checked by `make demo` and `test_act3_alert_storm_is_correlated_and_only_then_solved`. A whole incident (three agents, all reads and writes) takes about 65 ms (median over the eval) on the deterministic planner; a single tool's queries take 1-7 ms.

## Graph data model

```mermaid
flowchart LR
  Team -- OWNS --> Service
  Person -- MEMBER_OF --> Team
  Person -- "ON_CALL {start,end}" --> Team
  Service -- "DEPENDS_ON {valid_from,valid_to}" --> Service
  Change -- CHANGED --> Service
  Change -- AUTHORED_BY --> Person
  Ticket -- REQUESTED --> Change
  Message -- MENTIONS --> Change
  Anomaly -- ON --> Service
  Alert -- FIRED_ON --> Service
  Incident -- TRIGGERED_BY --> Alert
  Incident -- CORRELATED_WITH --> Alert
  Incident -- "SHARED_UPSTREAM {rank,betweenness}" --> Service
  Incident -- "IMPACTS {hops,via}" --> Service
  Incident -- "PAGED {for_service}" --> Person
  Incident -- "CONSULTED {for_service,score}" --> Person
  Incident -- HAS_HYPOTHESIS --> Hypothesis
  Hypothesis -- SUSPECTS --> Change
  Evidence -- "SUPPORTS / REFUTES" --> Hypothesis
  Incident -- LOGGED --> AgentStep
  Incident -- "RECALLS {score}" --> Incident
  Incident -- CAUSED_BY --> Change
  Incident -- FIXED_WITH --> Runbook
  Runbook -- FOR_SERVICE --> Service
  Meta["Meta {version, seed}: data fingerprint"]
```

- **Episodic memory:** `Incident` + `CAUSED_BY` + its `AgentStep` history. **Semantic:** the org, ownership and dependency facts, with `valid_from`/`valid_to` so the agents use what was true at alert time. **Procedural:** `Runbook` + `FIXED_WITH`, with `uses`/`successes` counts.
- One graph per tenant (`tenant_<name>`), plus `pristine_<name>` for resets. The single `Meta` node fingerprints the seed data, so a reset never restores a copy made by an older generator.
- Every label except `Meta` is indexed on `id`; `Change.at` and `Anomaly.at` have range indexes for the alert-window filters.
- Every label, property and relationship, with who writes it: [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

## Quick start (local, no Docker)

Needs Python 3.12 (or `uv`, which fetches it), `make`, and either glibc >= 2.39 (uses the `falkordblite` wheel) or gcc (builds redis and fetches the official FalkorDB module).

```bash
make setup     # venv + deps; FalkorDB binaries via falkordblite or scripts/falkordb_bin.sh
make db        # FalkorDB on :6379 (make db-stop saves and stops it)
make seed      # rebuild graph tenant_acme from scratch with the synthetic company (+ a pristine copy for resets)
make demo      # all three acts and both ablations in the terminal, with the trace; exits non-zero if the story breaks
make dev       # API + web UI on http://localhost:8000
make test      # unit + integration tests (integration tests skip if FalkorDB is not running)
```

No LLM key is needed: by default a deterministic planner chooses each step from what the graph says. To let an LLM choose the tools instead, set `LLM_PROVIDER` (gemini, openai, groq, openrouter, ollama, anthropic) and a key in `.env` (see `.env.example`). If the model picks an unknown tool, invalid arguments or a repeated step, or the API fails, that step falls back to the deterministic planner and the trace says so.

## Using it

- **Web UI** (`make dev`, then http://localhost:8000): click 0 Reset, 1 Act 1, 2 Confirm root cause, 3 Act 2, 4 Act 3 (three alerts at once). The trace plays step by step; every card shows why the planner chose that tool and the exact Cypher it ran; clicking a card lights up its evidence in the graph. The outcome panel shows "culprit on check N", the next action and who to ask. The **Ask the brain** tab runs `who_knows` and `change_story` live. `?offline=1` replays recorded fixtures without a database.
- **HTTP API:** `GET /api/tools` lists every tool with its JSON schema; `POST /api/tenants/{tenant}/tools/{name}` runs one. Use-case endpoints: `POST /api/tenants/{t}/reset`, `POST /api/tenants/{t}/alerts/{alert_id}/respond`, `POST /api/tenants/{t}/incidents/{id}/resolve`.
- **MCP:** the same 20 tools, plus `respond_to_alert` and `reset_tenant`, for any MCP client. Run `make mcp` for stdio, or `python -m oncall_brain.mcp_server --http --port 8001`. For Claude Code: `claude mcp add --transport stdio oncall-brain -- <venv>/bin/python -m oncall_brain.mcp_server`. Details in [docs/MCP.md](docs/MCP.md).
- **Company brain** questions, as tools: `who_knows` (who knows a service, ranked by ownership, changes they authored and incidents they were paged for) and `change_story` (trace a change to its ticket, its chat announcement, its author and the incidents it caused).
- **Live events**, as tools: `record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency`. Push a change and an anomaly, raise an alert, then respond to it: the agents use the new facts at once.
- **Exposure:** the API checks the `Host` header (`ALLOWED_HOSTS`) and refuses cross-origin POSTs. `API_TOKEN` optionally requires a bearer token on `/api/*` (not `/api/health`; the bundled UI does not send it). There is no per-user auth: anyone who can reach the API can address any tenant. Keep it on localhost unless you set these.

## Docker

```bash
docker compose up --build    # falkordb/falkordb:v4.22.0 + the app on :8000 (+ FalkorDB Browser on :3000)
```

Ports are published on 127.0.0.1 only. The app container seeds the default tenant if its graph is missing, then serves on `$PORT` (default 8000). For a live deployment (FalkorDB Cloud + Render via `render.yaml`, or any Docker VM), see [docs/DEPLOY.md](docs/DEPLOY.md).

## How each track is covered

| Track | What to look at |
|---|---|
| 01 Agents That Act on Connected Data | multi-hop `DEPENDS_ON*` suspects with temporal edge filters; `shortestPath` refutations; alert-storm correlation over the shared upstream, ranked with `algo.betweenness` (`test_act3_alert_storm_is_correlated_and_only_then_solved`); the planner branches on what each query returns; actions written back (incident, impacts, pages, hypotheses, evidence, the consulted expert, status update); live events written through tools (`record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency`); tools exposed via MCP; every step's Cypher in the trace |
| 02 Agent Memory and Coordination | three roles hand off through the shared `Incident` board (no in-process state); `AgentStep` history persisted per incident; episodic + semantic + procedural memory, where the runbook decides what memory suspects and loses confidence when refuted; act 2 recalls act 1; one graph per tenant (`test_tenants_are_isolated`); a per-tenant lock so concurrent responders don't duplicate work (`test_concurrent_responders_do_not_duplicate_work_or_edges`) |
| 03 Company Brain | changes, tickets, chat, incidents, runbooks and people in one graph; `who_knows` / `change_story` (also in the UI's Ask tab); every status update cites its sources and the person to ask (`CITES` edges); keeping knowledge current: temporal dependencies, plus event tools that record changes, anomalies, alerts and retired dependencies as they happen (`test_live_events_drive_a_new_investigation`) |

## Repo layout

```
src/oncall_brain/
  domain/        pure logic: planner, hypothesis verdicts, update templates, models
  ports/         Protocols: GraphRepository, GraphStore, LLMProvider
  adapters/      falkordb/ (repository + queries/*.cypher), llm/ (mock, openai_compat, anthropic)
  services/      use cases: respond, resolve, seeding, the tool implementations, board loader
  agents/        tool registry and the agent loop
  api/           FastAPI app (also serves web/)
  mcp_server/    MCP server generated from the same registry
  datagen.py     the seeded synthetic company and the planted three-act story
  scenarios.py   randomised incidents for the eval
web/             no-build UI (Cytoscape.js from a CDN)
scripts/         seed, demo, eval, gen_queries_doc, gen_fixtures, FalkorDB runners
tests/           unit/ (no DB), integration/ (real FalkorDB)
docs/            architecture, data model, queries, eval, MCP, deploy, walkthrough, ADRs, AI usage
```

## More

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): design (HLD/LLD), diagrams, trade-offs
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md): every label and relationship
- [docs/QUERIES.md](docs/QUERIES.md): every Cypher query the product runs (generated)
- [docs/EVAL.md](docs/EVAL.md): graph agent vs baselines on generated incidents
- [docs/MCP.md](docs/MCP.md): use the same tools from any MCP client
- [docs/DEPLOY.md](docs/DEPLOY.md): live deployment (FalkorDB Cloud + Render, or any Docker VM)
- [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md): a 30-minute tour of the code
- [docs/decisions/](docs/decisions/): ADRs, including the idea council
- [docs/AI_USAGE.md](docs/AI_USAGE.md): how AI assistants were used
