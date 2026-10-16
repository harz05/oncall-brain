# On-call Brain as an MCP server

Every graph tool the agents use is defined once in `agents/registry.py`. `oncall_brain.mcp_server` publishes that
same registry over the [Model Context Protocol](https://modelcontextprotocol.io), so Claude Desktop, Claude Code,
the MCP Inspector or any other MCP client can call the tools directly: 26 registry tools plus two use-case tools,
28 in all.

| Tool | What it does |
|---|---|
| `reset_tenant` | Restore the tenant's pristine seeded graph (`GRAPH.COPY`), seeding it first if there is none. |
| `respond_to_alert` | Run triage -> investigator -> comms on an alert. Returns the incident id, the outcome (root cause, `co_causes`, ruled-out suspects with their tags, both no-graph baselines, who was paged, the status update text, `checks_to_culprit`, `runbook`, `expert`, `storm`) and a short list of steps. The same-incident memory ablation (`?compare=memory`) is on the HTTP endpoint only. |
| agent tools | `open_incident`, `correlate_alerts`, `blast_radius`, `page_on_call`, `recall_similar`, `hypothesize_from_memory`, `propose_hypotheses`, `check_hypothesis`, `conclude`, `post_update` (writes the update for #incidents onto the incident; nothing is sent to Slack) |
| human step | `resolve_incident`: confirm the cause and learn the runbook. The confirmed change becomes the incident's cause even if the agents picked another (theirs is outranked). It also rewrites the status update ("status: resolved, cause confirmed"), on every surface. Our own agent runs are never offered it. |
| company brain | `ask` (a free-form question over docs, tickets and chat: FalkorDB full-text search, then the graph around the hits, then an answer with every source cited; no LLM. With a `user` and a `session` key the question is remembered in that person's session in the graph, a follow-up can say "it" or "them", and "what did I ask about payments-gw" is answered from it; "what is the Q4 cost review changing and who is on it" walks the `Initiative` behind the tickets), `my_questions` (the same recall as a tool: a user's earlier questions, newest first, with what each was about and the sources it cited, by subject or session), `who_knows`, `change_story` |
| read tools | `dependency_path`, `service_map`, `incident_board` |
| live events | `record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency`, `record_doc` (a decision record, design note, postmortem or runbook page, with the service it decides for and the doc it supersedes; `ask` answers from it at once and flags the old decision), `transfer_ownership` (a team takes over a service: the old owner's `OWNS` edge is closed, never deleted, so an alert from before the handover still pages the old team and "who owned payments-gw at the time of inc:0911" still names it): keep the graph current, then respond to the new alert. Like `resolve_incident`, never offered to our own agent runs. |

Every tool takes a required `tenant` (`[a-z0-9_]{1,40}`): each tenant is its own FalkorDB graph `tenant_<name>`.
Registry tools return JSON text `{summary, data, queries: [{name, readonly, rows, ms, cypher}]}`, so the client sees
the exact Cypher behind every answer and whether it ran read-only (`GRAPH.RO_QUERY`). Read-only tools carry the
MCP `readOnlyHint` annotation. `who_knows` counts as a write tool: with an `incident_id` it records the top
person as `CONSULTED` on that incident. Write tools take the tenant lock, so they cannot race an agent run.

## Run it

FalkorDB must be running (`make db`). Settings come from the environment or `.env` in the working directory
(see `.env.example`). `respond_to_alert` uses the planner chosen by `LLM_PROVIDER` (default: the deterministic one).

```bash
# stdio (what Claude Desktop / Claude Code launch)
python -m oncall_brain.mcp_server          # or: make mcp

# Streamable HTTP at http://127.0.0.1:8001/mcp
python -m oncall_brain.mcp_server --http --port 8001
```

Over HTTP the server checks the `Host` and `Origin` headers against `ALLOWED_HOSTS` (plus the local names and the
hostname Render or Railway set) on any bind address, which blocks DNS rebinding. Set `MCP_TOKEN` (or `API_TOKEN`,
which also guards the HTTP API) and every request must carry `Authorization: Bearer <token>`, which is what a remote
client needs. A deployment ([DEPLOY.md](DEPLOY.md)) serves the same endpoint at `https://<host>/mcp` from the one app
container (`oncall_brain.serve`, also `make serve`), where the token is required: without one `/mcp` answers 401
while the UI and API keep working. There is no per-user auth: anyone with the token can use any tenant.

`<venv>/bin/python` below is the interpreter `make setup` created (`<repo>/.venv/bin/python`, or wherever your
`VIRTUAL_ENV` points).

## What an outside model sees, and whether it picks right

The server publishes `instructions` (the three ways to use it and what ids look like), 28 tools with a description
and a described argument schema each (`tests/unit/test_mcp_surface.py` fails the build if any argument lacks one),
`readOnlyHint` annotations, and two prompts:

| Prompt | Arguments | Expands to |
|---|---|---|
| `work_alert` | `tenant`, `alert_id` | "Call respond_to_alert ... report the likely cause with its confidence, who is paged, the fix, what was ruled out, the update; then offer resolve_incident" |
| `company_question` | `tenant`, `question`, optional `user` and `session` | "Call ask (with user and session when given, so the question is remembered and a follow-up can say 'it') ... lead with the answer, then the sources; who_knows / change_story when they add something" |

`python -m scripts.mcp_pick` gives Claude only what an MCP client gets (instructions + tool list) and 14 plain
requests ("who owns kafka?", "we just deployed cart v3.2.0, record that", "inc:checkout-latency is confirmed:
chg:pgw-pool-1 caused it"...). Result: **14/14 right on claude-opus-5-5**, table in [MCP_PICK.md](MCP_PICK.md).

## Headless: alert in, answer and update out, no UI open

```bash
curl -X POST 'http://localhost:8000/api/tenants/acme/alerts?respond=true' \
  -H 'content-type: application/json' \
  -d '{"service": "svc:checkout", "symptom": "latency", "name": "checkout p99 latency above 2s"}'
```

records the alert (`raise_alert`), runs the three agents, writes the incident, its evidence and the status update
into the graph, and, with `SLACK_WEBHOOK_URL` set, posts the update to your channel. The response is the same run
object the UI shows; the inbox lists the incident the next time anyone opens it. Over MCP the equivalent is
`raise_alert` then `respond_to_alert`.

## Claude Code

```bash
claude mcp add --transport stdio --env FALKORDB_HOST=localhost --env FALKORDB_PORT=6379 oncall-brain \
  -- <venv>/bin/python -m oncall_brain.mcp_server
claude mcp list                        # oncall-brain should show as connected
```

Over HTTP instead (start the server with `--http` first):

```bash
claude mcp add --transport http oncall-brain http://127.0.0.1:8001/mcp
```

Then, in Claude Code, ask e.g. *"Using oncall-brain on tenant demo: reset it, then respond to
alert:checkout-latency and tell me the root cause and which suspects were ruled out."*, or use the server's prompts
(`/mcp` lists them as `/oncall-brain:work_alert` and `/oncall-brain:company_question`).

### The Claude Code plugin

`plugin/` packages the same server for a one-minute install:

| File | What it is |
|---|---|
| `plugin/.claude-plugin/plugin.json` | The manifest: name `oncall-brain`, points at `.mcp.json`. |
| `plugin/.mcp.json` | Two MCP server entries: `oncall-brain` (stdio: `${CLAUDE_PLUGIN_ROOT}/bin/oncall-brain-mcp`) and `oncall-brain-remote` (`type: http`, `${ONCALL_BRAIN_URL:-http://127.0.0.1:8001}/mcp` with `Authorization: Bearer ${ONCALL_BRAIN_TOKEN}`). Claude Code expands `${VAR}` and `${VAR:-default}` in a plugin server's `url` and `headers`, so a deployed instance needs nothing local; with neither variable set the entry reaches a local `make mcp-http`. |
| `plugin/bin/oncall-brain-mcp` | Launcher: runs `<checkout>/.venv/bin/python -m oncall_brain.mcp_server` from the checkout (the plugin's parent directory, or `$ONCALL_BRAIN_HOME`), so `.env` is found. Arguments pass through (`--http --port 8001`). |
| `plugin/skills/incident/SKILL.md` | `/oncall-brain:incident <alert_id> [tenant]`: the `work_alert` flow, with the heads-up and the confirm step. |
| `plugin/skills/who-owns/SKILL.md` | `/oncall-brain:who-owns <service> [tenant]`: `who_knows`, then `ask`, then the rotation. |
| `plugin/skills/ask/SKILL.md` | `/oncall-brain:ask <question> [--tenant t] [--as person:...]`: the `company_question` flow, with the asker's session when `--as` is given (a follow-up can say "it"; "what did I ask about X" recalls), plus `change_story` / `dependency_path` when they add something. |
| `.claude-plugin/marketplace.json` (repo root) | A one-plugin marketplace, so `/plugin install oncall-brain --marketplace <owner>/<repo>` works once the repo is on GitHub. |

From the checkout: `claude --plugin-dir ./plugin`. From GitHub: `/plugin install oncall-brain --marketplace <owner>/<repo>`
(Claude Code 2.1.275 or later). `claude plugin validate --strict plugin`, `... .claude-plugin/marketplace.json` and
`... plugin/skills` all pass; `tests/integration/test_plugin.py` runs them when the CLI is installed and then drives
the server through the launcher with an MCP client: 28 tools, 2 prompts, and the who-owns skill's three calls on a
freshly reset tenant, every answer carrying its Cypher. Remote mode is tested the same way: the `oncall-brain-remote`
entry, expanded as Claude Code expands it, reaches a local `--http` server started with `API_TOKEN`, lists the 28 tools
and answers `ask`; a wrong token gets 401
(`test_the_remote_entry_reaches_a_deployed_server_with_the_token_and_nothing_local`). Claude Code itself agrees:
`claude --plugin-dir ./plugin mcp list` (2.1.301) shows `plugin:oncall-brain:oncall-brain` Connected over stdio and,
with `ONCALL_BRAIN_URL` and `ONCALL_BRAIN_TOKEN` pointing at a `--http` server started with `API_TOKEN`,
`plugin:oncall-brain:oncall-brain-remote` Connected too; with a wrong token it reports the server's 401 ("missing or
wrong API token"); with neither variable set it tries `http://127.0.0.1:8001/mcp`, which is `make mcp-http`.

## Claude Desktop

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`)
and restart Claude Desktop. Claude Desktop does not start in the repo, so pass the settings as `env`, not `.env`:

```json
{
  "mcpServers": {
    "oncall-brain": {
      "command": "<venv>/bin/python",
      "args": ["-m", "oncall_brain.mcp_server"],
      "env": {"FALKORDB_HOST": "localhost", "FALKORDB_PORT": "6379", "LLM_PROVIDER": "mock"}
    }
  }
}
```

## MCP Inspector

```bash
npx @modelcontextprotocol/inspector <venv>/bin/python -m oncall_brain.mcp_server
```

Or start the server with `--http` and point the Inspector at `http://127.0.0.1:8001/mcp` (transport: Streamable
HTTP).

## Example session

The responses below are real (the Cypher is trimmed).

```text
> blast_radius {"tenant": "demo", "service": "svc:payments-gw"}
ValueError: tenant 'demo' has no graph yet; call reset_tenant first          (isError: true)

> reset_tenant {"tenant": "demo"}
{"tenant": "demo", "graph": "seeded"}

> blast_radius {"tenant": "demo", "service": "svc:payments-gw"}
{"summary": "7 services depend on svc:payments-gw (5 tier-1)",
 "data": [{"service": "svc:payments", "tier": 1, "hops": 1, "team": "Payments",
           "path": ["svc:payments", "svc:payments-gw"]},
          {"service": "svc:checkout", "tier": 1, "hops": 2, "team": "Checkout",
           "path": ["svc:checkout", "svc:payments", "svc:payments-gw"]}, ...],
 "queries": [{"name": "blast_radius", "readonly": true, "rows": 7, "ms": 3.23, "cypher": "MATCH ..."}]}

> respond_to_alert {"tenant": "demo", "alert_id": "alert:checkout-latency"}
{"incident_id": "inc:checkout-latency", "planner": "deterministic planner",
 "outcome": {"root_cause": {"change": "chg:pgw-pool-1", "service": "svc:payments-gw",
                            "summary": "Lower payments-gw HTTP pool max_connections 200 -> 20 (cost cleanup)",
                            "verdict": "supports", "reason": "anomaly propagates payments-gw -> payments -> checkout",
                            "live_path": ["svc:checkout", "svc:payments", "svc:payments-gw"]},
             "refuted": [...], "baseline_pick": {...}, "baseline_correct": false,
             "anomaly_baseline_pick": {"change": "chg:legacy-193", ...}, "anomaly_baseline_correct": false, "paged": [...],
             "co_causes": [],
             "update_text": "...", "investigator_calls": 8, "hypotheses_checked": 5, "checks_to_culprit": 3,
             "runbook": null, "expert": {"name": "Sana Brandt", "handle": "@sana.brandt", ...}, "storm": null, ...},
 "steps": [{"seq": 1, "role": "triage", "tool": "open_incident", "summary": "Opened inc:checkout-latency ..."},
           {"seq": 2, "role": "triage", "tool": "blast_radius", "summary": "3 services depend on svc:checkout ..."},
           {"seq": 3, "role": "triage", "tool": "page_on_call", "summary": "Paged Ravi Moreau (@ravi.moreau, Checkout) ..."},
           {"seq": 4, "role": "triage", "tool": "handoff", "summary": "triage hands off to investigator"},
           {"seq": 5, "role": "investigator", "tool": "recall_similar", "summary": "Recalled inc:0911 ..."}, ...]}

> resolve_incident {"tenant": "demo", "incident_id": "inc:checkout-latency", "change_id": "chg:pgw-pool-1"}
  ... runbook learned; the stored update now starts "[checkout p99 latency above 2s] status: resolved, cause confirmed".
> respond_to_alert {"tenant": "demo", "alert_id": "alert:refunds-latency"}
  ... act 2: recalled from act 1's memory, culprit on check 1, update has a "Next action" line.
```

## Example: ask the company brain

`ask` reads only (two `GRAPH.RO_QUERY` calls; given a `user` it also appends the question to that person's session), so it needs no incident. Response from a freshly reset tenant, trimmed:

```text
> ask {"tenant": "demo", "question": "Why was the payments gateway pool lowered?"}
{"summary": "5 sources for 'payments gateway pool lowered'; most relevant doc:cost-review-pgw",
 "data": {"answer": "Most relevant: Q4 cost review: payments gateway idle connections (design note, by Sana Brandt,
            2026-10-06): \"payments-gw (the payments gateway) keeps a pool of 200 connections but uses fewer than 20
            overnight. Decision: lower the pool max_connections from 200 to 20, which cuts the gateway bill by about
            40%.\" It concerns payments-gw, payments; related changes: chg:pgw-pool-1 'Lower payments-gw HTTP pool
            max_connections 200 -> 20 (cost cleanup)'; people who know: Sana Brandt, Quinn Tanaka. It is the decision
            of record for payments-gw. Also: ...",
          "hits": [{"id": "doc:cost-review-pgw", "kind": "design", "matched": 4, "superseded_by": null, ...}, ...],
          "related": [{"id": "svc:payments-gw", "kind": "service", "via": "doc:cost-review-pgw DECIDES svc:payments-gw"},
                      {"id": "team:payments", "kind": "team", "via": "team:payments OWNS svc:payments-gw"}, ...],
          "sources": ["doc:cost-review-pgw", "msg:chat-008", "doc:pm-load-test-pgw", "ticket:PAY-388", "ticket:CR-881"]},
 "queries": [{"name": "search_knowledge", "readonly": true, ...}, {"name": "knowledge_context", "readonly": true, ...}]}
```

Ask with a few content words: stopwords and one-letter words are dropped and only `[a-z0-9]` survives, so a question
like "why was it?" returns a plain "Ask with a few content words" answer without querying the index.

## Example: push your own events, then respond

The event tools let a client keep the graph current and start a new investigation. Times are epoch seconds
(default: now); here they sit on a quiet day of the seeded history.

```text
> record_change {"tenant": "demo", "service": "svc:inventory", "kind": "deploy", "summary": "Deploy inventory v9", "at": 1792121400}
{"summary": "Recorded deploy chg:inventory-1792121400 on svc:inventory", ...}

> record_anomaly {"tenant": "demo", "service": "svc:inventory", "kind": "errors", "summary": "5xx up", "at": 1792121500}
> record_anomaly {"tenant": "demo", "service": "svc:checkout", "kind": "errors", "summary": "5xx up", "at": 1792122600}

> raise_alert {"tenant": "demo", "service": "svc:checkout", "symptom": "errors", "name": "checkout 5xx", "at": 1792123200}
{"summary": "Alert alert:checkout-errors-1792123200 raised on svc:checkout",
 "data": {"alert": "alert:checkout-errors-1792123200", "incident": "inc:checkout-errors-1792123200", "at": 1792123200}, ...}

> respond_to_alert {"tenant": "demo", "alert_id": "alert:checkout-errors-1792123200"}
  ... root cause chg:inventory-1792121400: "anomaly propagates inventory -> checkout"
```

`add_dependency` and `retire_dependency` change the dependency map the same way. A dependency retired before the
alert makes the agents refute suspects behind it ("checkout no longer depends on cart"; see
`test_live_events_drive_a_new_investigation`).

## Tests

`tests/integration/test_mcp.py` drives the server in-process with the SDK's own `mcp.Client`. It lists the tools,
seeds a throwaway tenant through `reset_tenant` and calls `blast_radius` on it; it is skipped when FalkorDB is not
reachable. `test_mcp_over_http_refuses_foreign_host_and_origin` checks that MCP over HTTP answers a foreign `Host`
with 421 and a foreign `Origin` with 403. `tests/unit/test_mcp_surface.py` checks every tool and argument is
described, the prompts render, and the remote transport refuses requests without the token when `API_TOKEN` is set.
`tests/unit/test_serve.py` covers the deployment app: `/mcp` refused until a token is set while the API stays open,
opened by `MCP_TOKEN` at the exact path, one `API_TOKEN` guarding both halves, the platform hostnames accepted;
`tests/integration/test_deploy.py` starts it as the Dockerfile does and drives it from outside (`/health`, the UI,
the Host checks, 28 tools and an `ask` over `/mcp`, 401 on a wrong token).
