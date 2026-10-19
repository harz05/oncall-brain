# On-call Brain

An AI on-call teammate. When an alert fires, it tells you what broke, why, who is paged and the fix, with the proof
from your company's graph. It remembers the causes you confirm.

When checkout slows down, the newest deploy is rarely the cause. The cause sits somewhere on the dependency path, and
it matters whether that dependency was live at the time. Three agent roles (triage, investigator, comms) work the
incident through one shared FalkorDB graph. They find the change that broke it and rule out the changes a change log
would blame. You confirm the cause, the graph keeps the fix, and the next similar incident takes 3 investigator steps
instead of 6. It is an MCP server first (Claude Code, Claude Desktop, any MCP client), plus Slack, an alert webhook and
a web inbox onto the same graph.

- **Tracks entered:** 01 Agents That Act on Connected Data, 02 Agent Memory and Coordination, 03 Company Brain
  ([how each is covered](docs/TRACKS.md)).
- **Demo video:** https://youtu.be/eriObL8LlsQ
- **Live:** https://13-127-186-74.sslip.io/ (press **Simulate an incident**). One AWS box runs the app, the agents on
  Claude Opus 5.5 and the MCP server at `/mcp`; the graphs live on FalkorDB Cloud.
- **Without a server:** https://harz05.github.io/oncall-brain/ replays recorded runs of all three incidents.
- Built for Graph Hacks (WeMakeDevs x FalkorDB), October 2026. All data is synthetic (seeded generator, fake names).

![The incident answer for "checkout p99 latency above 2s": a readout of 40 min from change to alert, 4 services hurt, 5 suspects tested and 2 people paged; Confirm cause / Wrong cause; the cause, a payments-gw config change by Sana Brandt 40 min before the alert, labelled "Very likely" with "4 of 5 suspects ruled out"; and the evidence path from the change through payments-gw and payments to checkout, with the time each hop slowed down](docs/img/answer.png)

## Architecture

![Architecture: four surfaces (the Claude Code plugin over MCP, Slack /oncall, the alert webhook and the web UI) call one tool registry of 31 graph tools. The registry runs the triage, investigator and comms agents, which ask Claude Opus 5.5 or the rules planner for each next step and share an incident board in the graph. Every tool runs named Cypher against FalkorDB Cloud, which holds one tenant graph per company, a coordination graph for locks, throttles and the LLM budget, and two UDF libraries the queries call, oncall and FLEX](docs/img/architecture.png)

Every surface goes through one tool registry (`agents/registry.py`). Each tool is defined once and runs named,
parameterised Cypher from `queries/*.cypher`, so the MCP server, the HTTP API and the agent loop share it. The agents
keep no incident state in Python: before each step they re-read the incident board from the graph and ask the planner
(Claude, or deterministic rules when no key is set) what to do next. Each company gets its own graph; locks, throttles
and the LLM budget live in a separate coordination graph. Design detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What it does

1. **Act 1, "checkout p99 latency above 2s".** Triage finds what is hurt and pages the on-call. The investigator tests
   every recent change on checkout's live upstream: the newest deploy has no path to checkout, a legacy-billing deploy
   sits on a dependency retired 3 days ago, one was rolled back, one showed no errors. The payments-gw config change
   two hops up is the cause. Comms writes the status update with its sources.
2. **Act 2, three days later, "refunds p99 latency above 2s".** Recall finds act 1 by structure (the same gateway is
   upstream of refunds) and tests its fix first: 3 investigator steps instead of 6.
3. **Act 3, three alerts in 4 minutes.** `algo.WCC` on a projection decides they are one incident, and the change
   that explains all three leads.

Step by step, with every graph fact that decided it: [docs/STORY.md](docs/STORY.md).

![The second incident, refunds p99 latency above 2s: a new payments-gw config change named as the cause, and "Solved from memory": checkout's confirmed fix ("Revert the config change on payments-gw") was tested first, so 3 investigator steps instead of 6 and 1 suspect tested instead of 4](docs/img/memory.png)

On 200 generated incidents ([docs/EVAL.md](docs/EVAL.md)):

| Method | Uses the graph | Found the planted cause |
|---|---|---|
| **On-call Brain** (deterministic planner) | yes | **186/200** |
| Change log that also watches anomalies | no | 134/200 |
| Keyword match on the alert name | no | 57/200 |
| Newest change in the window | no | 0/200 |

The scenarios are synthetic and I wrote both them and the checks, so read this as "the checks hold up on this data",
not as a blind test.

## Why the graph is not decoration

| What the agents do | FalkorDB doing the work | Without it |
|---|---|---|
| Blast radius, suspects, recall | Variable-length `DEPENDS_ON` walks over edges live at alert time, run as JavaScript UDFs inside FalkorDB (`oncall.live_upstream`, `oncall.live_reach`) | retired dependencies get blamed |
| Refute "no path" suspects | `shortestPath` over live edges | the change log's wrong answer stands |
| Alert storms | `algo.WCC` on a projection of the alerting services and their red upstreams | each alert investigated alone, wrong cause |
| Who gets warned first | `algo.pageRank` on a point-in-time projection | heads-ups in random order |
| A way around a service? | `algo.maxFlow` on the live projection | no answer to "will traffic go around it" |
| Shared state and handoffs | the `Incident` board (`Hypothesis`, `Evidence`, `AgentStep`), re-read before every step | agents can't coordinate |
| Memory | `RECALLS` -> `FIXED_WITH` -> `Runbook`, per tenant | act 2 takes 6 steps, not 3 |
| Company brain | full-text indexes, then `MENTIONS`, `DECIDES`, `SUPERSEDES`, `OWNS` for owners, sources and what is current | keyword hits with no owner or currency |
| Locks and budgets | `Lease` and `Counter` nodes; a UNIQUE constraint is the mutex | no shared limits on FalkorDB Cloud |
| Safety | `GRAPH.RO_QUERY` reads, one graph per tenant, UNIQUE and MANDATORY constraints | duplicates, undated edges, cross-tenant leaks |

The full mapping to the tracks, the hackathon brief and FalkorDB's own checklists is in
[docs/TRACKS.md](docs/TRACKS.md). The FalkorDB behaviour behind each design choice is in
[docs/FALKORDB_NOTES.md](docs/FALKORDB_NOTES.md).

## Graph data model

![Graph model: Person ON_CALL Team; Team OWNS Service with valid_from/valid_to; Service DEPENDS_ON Service with a key and valid_from/valid_to; Change, with at and recorded_at, CHANGED Service; Alert FIRED_ON Service; Incident TRIGGERED_BY Alert, HAS_HYPOTHESIS Hypothesis, CAUSED_BY Change, FIXED_WITH Runbook, RECALLS Incident; Hypothesis SUSPECTS Change; Evidence SUPPORTS or REFUTES Hypothesis; Doc MENTIONS or DECIDES Service and SUPERSEDES Doc](docs/img/graph-model.png)

- **Edges carry time.** `DEPENDS_ON`, `OWNS` and `ON_CALL` have validity windows and are closed, never deleted, so
  every query asks what was true at alert time. Facts a tool writes also carry `recorded_at`, when the graph learned
  them.
- **Memory is graph-shaped.** Episodic: `Incident`, `CAUSED_BY` and its `AgentStep` history. Semantic: the org,
  ownership and dependencies, plus docs, tickets and chat. Procedural: `Runbook` and `FIXED_WITH`, with use and success
  counts. Conversation memory: `Session` and `Question`.
- **One graph per company** (`tenant_<name>`), a pristine copy for resets, and the shared `oncall_brain_coord` graph
  for leases and counters.
- **The database enforces it.** UNIQUE `id` on every label, a UNIQUE and MANDATORY `key` on `DEPENDS_ON`, MANDATORY
  `valid_from` on `DEPENDS_ON` and `OWNS`, range indexes on event times, full-text indexes on docs, tickets and chat.

Every label, relationship, property, index and constraint, with the full diagram: [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

## The queries it depends on

Each agent step is one tool, and each tool runs named Cypher from `src/oncall_brain/adapters/falkordb/queries/*.cypher`.
All 120 queries, with parameters and purpose: [docs/QUERIES.md](docs/QUERIES.md).

| Step | Query | Graph feature |
|---|---|---|
| Triage: blast radius | `blast_radius`, `criticality` | `oncall.live_upstream` UDF; `algo.pageRank` on a projection |
| Triage: page | `on_call_for` | `OWNS` and `ON_CALL` validity windows |
| Triage: storm | `storm_upstream`, `storm_components` | shared red upstreams; `algo.WCC` on a projection |
| Investigator: recall | `recall_similar`, `memory_suspects` | `CAUSED_BY` and `FIXED_WITH`; `oncall.live_reach` |
| Investigator: suspects | `path_suspects` | `Change.at` range index, then `oncall.live_reach` |
| Investigator: check | `live_paths`, `anomalies_between`, `red_before` | `shortestPath` over live edges |
| Comms: heads-up and update | `warn_candidates`, `update_facts`, `post_update` | PageRank rank; `CITES` edges to every source |
| Ask the brain | `ownership`, `who_knows`, `initiative_story`, `session_context` | full-text search, `DECIDES`/`SUPERSEDES`, session memory |

![Show me why for act 1: the part of the company graph the incident touched, with the evidence path from the payments-gw change through payments to checkout in red, and on the right each agent step, who chose it (Claude Opus 5.5), its reason and its queries](docs/img/why.png)

## Quick start (local, no Docker)

Needs Python 3.12 (or `uv`, which fetches it), `make`, and either glibc >= 2.39 (uses the `falkordblite` wheel) or gcc
(builds redis and fetches the official FalkorDB module).

```bash
make setup     # venv + deps; FalkorDB binaries via falkordblite or scripts/falkordb_bin.sh
make db        # FalkorDB on :6379 (make db-stop saves and stops it)
make seed      # build graph tenant_acme with the synthetic company (+ a pristine copy for resets)
make demo      # all three acts in the terminal, with the trace; exits non-zero if the story breaks
make dev       # API + web UI on http://localhost:8000
make test      # unit + integration tests (integration tests skip if FalkorDB is not running)
```

No LLM key is needed: a deterministic planner plays all three roles. To let Claude choose each step, set
`LLM_PROVIDER=anthropic` and a key in `.env` (see `.env.example`).

## Docker

```bash
docker compose up --build    # falkordb/falkordb:v4.22.0 + the app on :8000 (+ FalkorDB Browser on :3000)
```

The app seeds the demo company if its graph is missing, then serves the UI, the API and `/mcp` from one process.
Queries to paste into FalkorDB Browser: [docs/USAGE.md](docs/USAGE.md#look-at-the-graph-in-falkordb-browser).
Live deployment (the AWS box with FalkorDB Cloud, Render, or any Docker VM): [docs/DEPLOY.md](docs/DEPLOY.md).

## Use it from Claude Code

```bash
make setup && make db && make seed
claude --plugin-dir ./plugin
```

Then ask: *"checkout is slow and alert:checkout-latency just fired on tenant acme. Find out why."* The plugin ships the
MCP server (33 tools) and three skills. To install it from the marketplace, or to point it at the live server instead
of a local one, see [plugin/README.md](plugin/README.md). For Claude Desktop and other MCP clients:
[docs/MCP.md](docs/MCP.md). Slack: [docs/SLACK.md](docs/SLACK.md). The web inbox, the HTTP API, headless alerts and
live events: [docs/USAGE.md](docs/USAGE.md).

## Runs on FalkorDB Cloud

The live site's graphs are on FalkorDB Cloud (Free tier, ap-south-1, next to the app box); the app needs only
`FALKORDB_URL`. Cloud allows graph commands but not Redis's `SET`, `INCR` or `EVAL`, so locks, throttles and the LLM
budget are nodes in a coordination graph. A watchdog puts back what a Free-tier restart loses: the constraints, the
UDF libraries and the demo company. Details: [docs/FALKORDB_NOTES.md](docs/FALKORDB_NOTES.md) and
[docs/DEPLOY.md](docs/DEPLOY.md).

## Docs

- [docs/STORY.md](docs/STORY.md): the three incidents, step by step
- [docs/TRACKS.md](docs/TRACKS.md): how each track and the hackathon brief are covered, with the tests
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): design, diagrams, the package map, trade-offs
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md): every label and relationship
- [docs/QUERIES.md](docs/QUERIES.md): every Cypher query the product runs (generated)
- [docs/FALKORDB_NOTES.md](docs/FALKORDB_NOTES.md): the FalkorDB behaviour behind each design choice
- [docs/EVAL.md](docs/EVAL.md): the graph agent against baselines on 200 generated incidents
- [docs/PERF.md](docs/PERF.md): query timings up to 2,500 services, and concurrency
- [docs/USAGE.md](docs/USAGE.md): the web inbox, Slack, headless alerts, the HTTP API, MCP and live events
- [docs/MCP.md](docs/MCP.md), [docs/SLACK.md](docs/SLACK.md), [plugin/README.md](plugin/README.md): the integrations
- [docs/DEPLOY.md](docs/DEPLOY.md): live deployment
- [docs/SECURITY.md](docs/SECURITY.md): what protects a public deployment, and the limits
- [docs/AI_USAGE.md](docs/AI_USAGE.md): how AI assistance was used
