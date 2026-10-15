# On-call Brain

Incident agents that reason over a FalkorDB graph and remember what fixed things.

**In one breath:** an alert fires; three agent roles (triage, investigator, comms) work the incident through one shared FalkorDB graph and find which change broke it, ruling out the decoys a change log would blame; a human confirms the fix, the graph remembers it, and the next similar incident is solved in half the steps.

- **Problem:** when checkout slows down, the newest deploy is rarely the cause. The cause sits somewhere on the dependency path, and whether a dependency was even live at the time matters.
- **Result:** in the demo, every change-log method blames the wrong change (one blames a service checkout stopped calling three days ago); the graph agent names the payments-gateway config change two hops upstream, with the path and sources.
- **How:** temporal multi-hop Cypher traversals, a hypothesis board the roles hand off through, and episodic + procedural memory, all in one graph per tenant. By default a deterministic planner chooses each step from what the graph returns (no API key needed); an LLM can take its place.

**Tracks entered:** 01 Agents That Act on Connected Data, 02 Agent Memory and Coordination, 03 Company Brain.
Built for Graph Hacks (WeMakeDevs x FalkorDB), October 2026. All data is synthetic (seeded generator, fake names).

<!-- DEMO VIDEO LINK: add after recording -->
<!-- LIVE REPLAY: https://<user>.github.io/<repo>/ once GitHub Pages is enabled (Settings -> Pages -> GitHub Actions) -->

**Try it without installing anything:** the web UI replays all three acts from recorded runs when no backend is reachable, so the GitHub Pages build of `web/` (`.github/workflows/pages.yml`) is a zero-setup look at the product. The recordings come from the real code (`scripts/gen_fixtures.py`); for live runs use the quick start below.

![Act 2: the refunds incident solved from act 1's memory. Same incident without that memory: 6 investigator calls, culprit on check 2; with it: 3 calls, check 1](docs/img/act2.png)

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

- Both change logs without the graph get it wrong. The flat one blames the newest change (search). One that also watches anomalies blames legacy-billing: it deployed at 08:40 and threw errors at 08:45, before payments-gw went red. But checkout stopped calling legacy-billing 3 days ago, and only the temporal edge knows that.
- Comms pages the payments team, asks the graph who knows payments-gw best (`who_knows`, recorded as `CONSULTED`), warns refunds and subscriptions (they depend on the same gateway), and writes the status update for #incidents. It is stored on the incident as a `Message` that `CITES` its sources; nothing is sent to Slack. From `make demo`:

```text
[checkout p99 latency above 2s] status: cause identified, fix pending
Impact: api-gateway, checkout, mobile-bff, web-frontend
Likely cause: config change on payments-gw by Sana Brandt: "Lower payments-gw HTTP pool max_connections 200 -> 20 (cost cleanup)"
Ruled out: legacy-193 (dependency retired), search-420 (no dependency path), pricing-2140 (rolled back), cart-310 (no anomaly after it)
Paged: @asha.nakamura (Payments), @ravi.moreau (Checkout)
Also at risk: refunds, subscriptions
Ask: Sana Brandt (@sana.brandt, Payments) knows payments-gw best
Sources: msg:pay-deploys-1, ticket:CR-881, doc:cost-review-pgw
```

- A human confirms. The incident gets `CAUSED_BY` the change, a `Runbook` is learned for (payments-gw, config), and the update is rewritten as "resolved, cause confirmed". The human's call wins: confirming a different change than the agents picked makes that change the cause and outranks theirs.

**Act 2, three days later: "refunds p99 latency above 2s".**
Recall finds act 1 by structure, because payments-gw is on refunds' live dependency path and the symptom is the same. Text similarity plays no part. The runbook that fixed act 1 is for config changes on payments-gw, so the investigator suspects the new payments-gw config change first and confirms it in one check. **The same incident replayed without act 1's memory takes 6 investigator calls and finds the culprit on check 2; with the memory it takes 3 calls and finds it on check 1** (the UI shows both, via `?compare=memory`). The update adds "Next action: Revert the config change on payments-gw (this runbook worked 1 of 1 times)". Without the memory, nearest-first checking tries a newer, healthy payments deploy (`chg:pay-77`, 1 hop away) before the culprit. An anomaly-aware change log also gets act 2 right (the payments-gw change is the first to go red), so act 2 shows memory making the investigation shorter, not beating that baseline.

**Act 3, two days later: three alerts in 4 minutes** (checkout, refunds, subscriptions).
- Triage sees other recent alerts on the board and calls `correlate_alerts` first. It walks each alerting service's upstream services over edges live at alert time, notes which went red, and folds in the alerts that share a red upstream service with this one (`CORRELATED_WITH`). An alert that only shares a quiet cache stays its own incident.
- The services all three reach are the shared upstream, ranked by convergence, the fewest total hops from the alerting services (payments 3, postgres-orders 5, ...), stored as `SHARED_UPSTREAM {rank, hops}`. The investigator checks suspects there first.
- The postgres-orders config change (max_connections 500 -> 150) is supported on check 1 and explains all 3 alerting services. The subscriptions deploy 30 minutes earlier is supported too (subscriptions blipped right after it), but explains only subscriptions. `conclude` keeps one leading cause and records the other as outranked: "chg:pg-conn-3 explains every alerting service this change does (1) and 2 more".
- Related alerts need not share one cause: a suspect that explains an alerting service the leader cannot is kept as a co-cause (its team is paged, the update says "Also contributing"), not ruled out (`tests/integration/test_storms.py`).
- Both change logs are wrong here: the flat one blames a search deploy, the anomaly-aware one blames the subscriptions deploy because it went red first. Without correlation, the same planner blames the subscriptions deploy too (`make demo` prints this ablation).

![Act 3: three alerts folded into one incident; the shared upstream ranked by convergence; the postgres-orders change found on check 1 and the subscriptions deploy outranked](docs/img/act3.png)

## Why the graph is not decoration

| What the agents do | FalkorDB feature doing the work | Without it |
|---|---|---|
| Blast radius, suspects, recall | variable-length `DEPENDS_ON*` traversals filtered per relationship by `valid_from`/`valid_to` at alert time | no multi-hop suspects; retired dependencies blamed |
| Refute "no path" suspects | `shortestPath` in `WITH` | the flat baseline's wrong answer stands |
| Alert storms | each alerting service's upstream closure over live edges, intersected; alerts are folded in only if they share a red upstream with this one; ranked by total hops; each suspect records which alerting services it can reach | each alert is investigated alone, and act 3 blames the subscriptions deploy |
| Cascade victim vs cause | `depends_among`: live `DEPENDS_ON*` among the supported suspects' services; an upstream suspect already red when a nearer change landed takes the lead | a deploy on a service that was already failing from upstream gets blamed because it is nearest |
| Shared state and handoffs | the `Incident` board: `Hypothesis`, `Evidence` (`SUPPORTS`/`REFUTES`), `AgentStep` nodes, re-read before every decision | agents can't coordinate; the planner has nothing to decide from |
| Memory | `RECALLS` -> `FIXED_WITH` -> `Runbook` -`FOR_SERVICE`-> service picks the first suspects; `uses`/`successes` set the runbook's confidence; persisted per tenant | the same incident takes 6 investigator calls instead of 3 |
| Company brain | `ask`: FalkorDB full-text indexes on `Doc`, `Ticket` and `Message` find the sources, then `MENTIONS` / `DECIDES` / `SUPERSEDES` / `AUTHORED_BY` / `CHANGED` / `OWNS` name the services, changes, teams and people, and flag docs a newer one superseded; `who_knows` (ownership + authored changes + incidents paged for + docs written, capped); `change_story` (ticket, chat, docs, author, incidents) | keyword hits with no owner, no "is this still current?", nobody to ask |
| Keeping knowledge current | event tools write changes, anomalies, alerts and dependency start/end (`valid_from`/`valid_to`) as they happen | the next investigation works from stale facts |
| Safety, multi-tenancy, repeatable demo | `GRAPH.RO_QUERY` for every read, one graph per tenant, `GRAPH.COPY` for resets | |

All of this is Cypher traversal: temporal variable-length paths, `shortestPath`, and intersecting upstream closures. We tried FalkorDB's `algo.betweenness` for ranking the storm's shared upstream and dropped it for two reasons. Its scores are sampled: on the demo graph, changing `samplingSeed` reorders the services even with `samplingSize` above the node count (api-gateway jumps from outside the top 6 to third). And it cannot filter `DEPENDS_ON` by `valid_from`/`valid_to`, so retired dependencies count. Neither is acceptable for a score that drives a decision.

The full query catalogue is in [docs/QUERIES.md](docs/QUERIES.md); the data model in [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

### Measured, not just claimed

On 200 generated incidents (random alert service, random cause 0-3 hops upstream, planted decoys of every kind above, plus noise anomalies in the window, a silent middle hop in some seeds and a cascade victim that deploys after the cause went red in others), from [docs/EVAL.md](docs/EVAL.md):

These scenarios are synthetic and written by the same team as the checks, so read the graph agent's score as "the checks hold up on this data", and the baselines' scores as what each shortcut gets wrong. The perturbations were added after mock judges called the first version (200/200) built to be passed, and the agent's ranking changed in the same round, by people who knew the perturbations: this is not a blind test. [docs/EVAL.md](docs/EVAL.md) has the per-perturbation table and every miss in the agent's own words.

| method | uses the graph | correct |
|---|---|---|
| **On-call Brain** (deterministic planner) | yes | **184/200 (92%)** |
| anomaly-aware change log: change behind the first service to go red | no | 134/200 (fooled by the retired-dependency decoy *d* 55 times, by decoy *c* made red by noise 11 times) |
| keyword match: change summary vs alert name | no | 57/200 |
| flat change log: newest change in the window | no | 0/200 (its pick is always a planted decoy) |

What fails: all 16 graph-agent misses are seeds where a random blip landed on decoy *c*'s service after its change, so *c* looks like a real, supported cause (22/38 correct on those seeds). On the 66 seeds with only the planted story it is 66/66; with a silent middle hop 11/13; with a cascade victim 48/51.

The eval has single-alert incidents only; act 3's storm is checked by `make demo` and `test_act3_alert_storm_is_correlated_and_only_then_solved`, five more storms (two independent causes, alerts on one service, a quiet shared cache, memory that explains part of a storm, two changes on one service) by `tests/integration/test_storms.py`, and a cascade victim and a monitoring gap by `tests/integration/test_causality.py`. A whole incident (three agent roles, all reads and writes) takes about 85 ms (median over the eval, p95 126 ms) on the deterministic planner; a single tool's queries take 1-8 ms. At scale, the hot traversals avoid enumerating paths (candidates from the time indexes, `shortestPath` checked against edge validity, per-hop-filtered fallbacks, breadth-first closures with `CALL {}`): on a hub-heavy 1,000-service graph, `blast_radius` on the hub went from 2.6 s to 45 ms with identical results ([docs/PERF.md](docs/PERF.md)).

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
  Doc -- "MENTIONS (services, changes, incidents)" --> Service
  Doc -- DECIDES --> Service
  Doc -- SUPERSEDES --> Doc
  Doc -- AUTHORED_BY --> Person
  Ticket -- MENTIONS --> Doc
  Anomaly -- ON --> Service
  Alert -- FIRED_ON --> Service
  Incident -- TRIGGERED_BY --> Alert
  Incident -- CORRELATED_WITH --> Alert
  Incident -- "SHARED_UPSTREAM {rank,hops}" --> Service
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
  Incident -- HAS_UPDATE --> Message
  Message -- "CITES (change, ticket, chat, doc, runbook, person)" --> Change
  Meta["Meta {version, seed}: data fingerprint"]
```

- **Episodic memory:** `Incident` + `CAUSED_BY` + its `AgentStep` history. **Semantic:** the org, ownership and dependency facts, with `valid_from`/`valid_to` so the agents use what was true at alert time, plus the docs, tickets and chat about them. **Procedural:** `Runbook` + `FIXED_WITH`, with `uses`/`successes` counts.
- One graph per tenant (`tenant_<name>`), plus `pristine_<name>` for resets. The single `Meta` node fingerprints the seed data, so a reset never restores a copy made by an older generator.
- Every label except `Meta` is indexed on `id`; `Change.at` and `Anomaly.at` have range indexes for the alert-window filters; `Doc(title, text)`, `Ticket(title, text)` and `Message(text)` have FalkorDB full-text indexes for `ask`.
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

No LLM key is needed: by default one deterministic planner plays all three roles, choosing each step by fixed rules from what the graph returns. To let an LLM choose the tools instead, set `LLM_PROVIDER` (gemini, openai, groq, openrouter, ollama, anthropic) and a key in `.env` (see `.env.example`). If the model picks an unknown tool, invalid arguments or a repeated step, or the API fails, that step falls back to the deterministic planner and the trace says so. Plainly: the LLM adapters are tested only against canned HTTP replies and have not been run against a live model in this project; every number in this repo comes from the deterministic planner.

## Using it

- **Web UI** (`make dev`, then http://localhost:8000): click 0 Reset, 1 Act 1, 2 Confirm root cause, 3 Act 2, 4 Act 3 (three alerts at once). The trace plays step by step; every card shows why the planner chose that tool and the exact Cypher it ran; clicking a card lights up its evidence in the graph. The outcome panel shows "culprit on check N", the next action, who to ask, the status update for #incidents, and what both change logs without the graph would have blamed; in act 2 the memory card compares the same incident without and with memory. The **Ask the brain** tab takes a free-text question (`ask`) and has `who_knows` / `change_story` as quick actions, all live. `?offline=1` (or no reachable API) replays recorded fixtures; the header then says "recorded replay" and the Ask tab only lists example questions.
- **HTTP API:** `GET /api/tools` lists every tool with its JSON schema; `POST /api/tenants/{tenant}/tools/{name}` runs one. Use-case endpoints: `POST /api/tenants/{t}/reset`, `POST /api/tenants/{t}/alerts/{alert_id}/respond` (add `?compare=memory` to also get `ablation.without_memory`: the same alert replayed on a scratch copy of the pristine graph, dropped afterwards), `POST /api/tenants/{t}/incidents/{id}/resolve`.
- **MCP:** the same 22 registry tools, plus `respond_to_alert` and `reset_tenant` (24 in all), for any MCP client. Agent runs are offered 16 of the registry tools: `resolve_incident` and the five event tools are for humans and outside clients only, so an agent can neither confirm its own fix nor invent graph facts (the agent loop also refuses them if a planner names one). Run `make mcp` for stdio, or `python -m oncall_brain.mcp_server --http --port 8001`. For Claude Code: `claude mcp add --transport stdio oncall-brain -- <venv>/bin/python -m oncall_brain.mcp_server`. Details in [docs/MCP.md](docs/MCP.md).
- **Company brain** questions, as tools: `ask` (a free-form question answered from docs, tickets and chat: full-text search, then the graph around the hits, then an answer assembled from those facts with every source cited; no LLM), `who_knows` (who knows a service, ranked by ownership, changes they authored, incidents they were paged for and, capped at 3, docs, tickets and chat they wrote about it) and `change_story` (trace a change to its ticket, chat, docs, author and the incidents it caused). For example, `ask` "Why was the payments gateway pool lowered?" leads with the Q4 cost review design note by Sana Brandt ("Decision: lower the pool max_connections from 200 to 20, which cuts the gateway bill by about 40%"), links `chg:pgw-pool-1`, and lists the peak load test postmortem that warned against it among its sources.
- **Live events**, as tools: `record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency`. Push a change and an anomaly, raise an alert, then respond to it: the agents use the new facts at once.
- **Exposure:** the API checks the `Host` header (`ALLOWED_HOSTS`) and refuses cross-origin POSTs. `API_TOKEN` optionally requires a bearer token on `/api/*` (not `/api/health`; the bundled UI does not send it). There is no per-user auth: anyone who can reach the API can address any tenant. Keep it on localhost unless you set these.

![The Ask the brain tab answering "Why was the payments gateway pool lowered?": the Q4 cost review design note by Sana Brandt first, quoted, then the chat proposing the change and act 1's status update as sources. Taken after acts 1 to 3 had run, so that status update exists; on a fresh graph the other sources are the load-test postmortem and two tickets](docs/img/ask.png)

## Docker

```bash
docker compose up --build    # falkordb/falkordb:v4.22.0 + the app on :8000 (+ FalkorDB Browser on :3000)
```

Ports are published on 127.0.0.1 only. The app container seeds the default tenant if its graph is missing, then serves on `$PORT` (default 8000). For a live deployment (FalkorDB Cloud + Render via `render.yaml`, or any Docker VM), see [docs/DEPLOY.md](docs/DEPLOY.md).

## How each track is covered

| Track | What to look at |
|---|---|
| 01 Agents That Act on Connected Data | multi-hop `DEPENDS_ON*` suspects with temporal edge filters; `shortestPath` refutations; alert-storm correlation: related alerts share a red upstream, the shared upstream is ranked by convergence, and `conclude` keeps the cause that explains the most alerting services plus any co-cause (`test_act3_alert_storm_is_correlated_and_only_then_solved`, `tests/integration/test_storms.py`); a deploy on a cascade victim loses to the upstream change that was already red when it landed, and a silent middle hop is weaker support named as a monitoring gap, not a refutation (`tests/integration/test_causality.py`); the planner branches on what each query returns; actions written back (incident, impacts, pages, hypotheses, evidence, the consulted expert, status update); live events written through tools (`record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency`); tools exposed via MCP; every step's Cypher in the trace |
| 02 Agent Memory and Coordination | three roles hand off through the shared `Incident` board (no in-process state; by default one deterministic planner plays all three roles); same-incident memory ablation: act 2 replayed on a copy of the pristine graph takes 6 investigator calls and finds the culprit on check 2, with memory 3 calls and check 1 (`?compare=memory`, shown in the UI); `AgentStep` history persisted per incident; episodic + semantic + procedural memory, where the runbook decides what memory suspects and loses confidence when refuted; act 2 recalls act 1; one graph per tenant (`test_tenants_are_isolated`); concurrent responders on one tenant are serialised by a per-tenant Redis lock, so they never duplicate work or edges (`test_concurrent_responders_do_not_duplicate_work_or_edges`); different tenants run in parallel |
| 03 Company Brain | a small synthetic corpus in the same graph as the services and incidents: 34 docs (postmortems, design notes, decision records, runbook pages), 41 chat messages and 21 tickets, linked by `MENTIONS`, `AUTHORED_BY`, `DECIDES` and `SUPERSEDES`; `ask` answers a free-form question from FalkorDB full-text search plus graph expansion, puts a current doc before the one it superseded, and cites every source (`tests/integration/test_brain.py`); `who_knows` / `change_story` also count docs; all three in the UI's Ask tab; every status update cites its sources and the person to ask (`CITES` edges); keeping knowledge current: temporal dependencies, plus event tools that record changes, anomalies, alerts and retired dependencies as they happen (`test_live_events_drive_a_new_investigation`). Answers are assembled from graph facts and quoted sentences, not written by an LLM |

## Repo layout

```
src/oncall_brain/
  domain/        pure logic: planner, hypothesis verdicts, update templates, models
  ports/         Protocols: GraphRepository, GraphStore, LLMProvider
  adapters/      falkordb/ (repository + queries/*.cypher), llm/ (mock, openai_compat, anthropic)
  services/      use cases: respond, resolve, seeding, the tool implementations, board loader, brain (`ask`)
  agents/        tool registry and the agent loop
  api/           FastAPI app (also serves web/)
  mcp_server/    MCP server generated from the same registry
  datagen.py     the seeded synthetic company, its docs, tickets and chat, and the planted three-act story
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
- [docs/PERF.md](docs/PERF.md): query timings from 25 to 1,000 services, before and after the traversal rewrite
- [docs/MCP.md](docs/MCP.md): use the same tools from any MCP client
- [docs/DEPLOY.md](docs/DEPLOY.md): live deployment (FalkorDB Cloud + Render, or any Docker VM)
- [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md): a 30-minute tour of the code
- [docs/decisions/](docs/decisions/): ADRs, including the idea council
- [docs/AI_USAGE.md](docs/AI_USAGE.md): how AI assistants were used
