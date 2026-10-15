# On-call Brain as an MCP server

Every graph tool the agents use is defined once in `agents/registry.py`. `oncall_brain.mcp_server` publishes that
same registry over the [Model Context Protocol](https://modelcontextprotocol.io), so Claude Desktop, Claude Code,
the MCP Inspector or any other MCP client can call the tools directly: 20 registry tools plus two use-case tools,
22 in all.

| Tool | What it does |
|---|---|
| `reset_tenant` | Restore the tenant's pristine seeded graph (`GRAPH.COPY`), seeding it first if there is none. |
| `respond_to_alert` | Run triage -> investigator -> comms on an alert. Returns the incident id, the outcome (root cause, refuted suspects, who was paged, status update, `checks_to_culprit`, `runbook`, `expert`, `storm`) and a short list of steps. |
| agent tools | `open_incident`, `correlate_alerts`, `blast_radius`, `page_on_call`, `recall_similar`, `hypothesize_from_memory`, `propose_hypotheses`, `check_hypothesis`, `post_update`, `resolve_incident` |
| read tools | `dependency_path`, `service_map`, `incident_board`, `who_knows`, `change_story` |
| live events | `record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency`: keep the graph current, then respond to the new alert |

Every tool takes a required `tenant` (`[a-z0-9_]{1,40}`): each tenant is its own FalkorDB graph `tenant_<name>`.
Registry tools return JSON text `{summary, data, queries: [{name, readonly, rows, ms, cypher}]}`, so the client sees
the exact Cypher behind every answer and whether it ran read-only (`GRAPH.RO_QUERY`). Read-only tools carry the
MCP `readOnlyHint` annotation. One exception to know: `who_knows` is marked read-only, but when you pass an
`incident_id` it also records the top person as `CONSULTED` on that incident.

## Run it

FalkorDB must be running (`make db`). Settings come from the environment or `.env` in the working directory
(see `.env.example`). `respond_to_alert` uses the planner chosen by `LLM_PROVIDER` (default: the deterministic one).

```bash
# stdio (what Claude Desktop / Claude Code launch)
python -m oncall_brain.mcp_server          # or: make mcp

# Streamable HTTP at http://127.0.0.1:8001/mcp
python -m oncall_brain.mcp_server --http --port 8001
```

Over HTTP the server checks the `Host` and `Origin` headers against `ALLOWED_HOSTS` (plus the local names) on any
bind address, which blocks DNS rebinding. It has no token and no per-user auth: anyone who can reach it can use any
tenant. Keep it on localhost, or see [DEPLOY.md](DEPLOY.md) before exposing it.

Which Python to use:
- On Harsh's machine, the venv lives on the external drive: `/media/harsh/MyPassport1/devenv/venv/bin/python`.
- Elsewhere, after `make setup`, it is the project venv: `<repo>/.venv/bin/python`.

The commands below use the first. Swap in the second on another machine.

## Claude Code

```bash
claude mcp add --transport stdio --env FALKORDB_HOST=localhost --env FALKORDB_PORT=6379 oncall-brain \
  -- /media/harsh/MyPassport1/devenv/venv/bin/python -m oncall_brain.mcp_server
claude mcp list                        # oncall-brain should show as connected
```

Over HTTP instead (start the server with `--http` first):

```bash
claude mcp add --transport http oncall-brain http://127.0.0.1:8001/mcp
```

Then, in Claude Code, ask e.g. *"Using oncall-brain on tenant demo: reset it, then respond to
alert:checkout-latency and tell me the root cause and which suspects were ruled out."*

## Claude Desktop

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`)
and restart Claude Desktop. Claude Desktop does not start in the repo, so pass the settings as `env`, not `.env`:

```json
{
  "mcpServers": {
    "oncall-brain": {
      "command": "/media/harsh/MyPassport1/devenv/venv/bin/python",
      "args": ["-m", "oncall_brain.mcp_server"],
      "env": {"FALKORDB_HOST": "localhost", "FALKORDB_PORT": "6379", "LLM_PROVIDER": "mock"}
    }
  }
}
```

## MCP Inspector

```bash
# On Harsh's machine, source env.sh first so the npm cache stays on the external drive.
source /media/harsh/MyPassport1/devenv/env.sh
npx @modelcontextprotocol/inspector /media/harsh/MyPassport1/devenv/venv/bin/python -m oncall_brain.mcp_server
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
             "refuted": [...], "baseline_pick": {...}, "baseline_correct": false, "paged": [...],
             "update_text": "...", "investigator_calls": 8, "hypotheses_checked": 5, "checks_to_culprit": 3,
             "runbook": null, "expert": {"name": "Sana Brandt", "handle": "@sana.brandt", ...}, "storm": null, ...},
 "steps": [{"seq": 1, "role": "triage", "tool": "open_incident", "summary": "Opened inc:checkout-latency ..."},
           {"seq": 2, "role": "triage", "tool": "blast_radius", "summary": "3 services depend on svc:checkout ..."},
           {"seq": 3, "role": "triage", "tool": "page_on_call", "summary": "Paged Ravi Moreau (@ravi.moreau, Checkout) ..."},
           {"seq": 4, "role": "triage", "tool": "handoff", "summary": "triage hands off to investigator"},
           {"seq": 5, "role": "investigator", "tool": "recall_similar", "summary": "Recalled inc:0911 ..."}, ...]}

> resolve_incident {"tenant": "demo", "incident_id": "inc:checkout-latency", "change_id": "chg:pgw-pool-1"}
> respond_to_alert {"tenant": "demo", "alert_id": "alert:refunds-latency"}
  ... act 2: recalled from act 1's memory, culprit on check 1, update has a "Next action" line.
```

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
with 421 and a foreign `Origin` with 403.
