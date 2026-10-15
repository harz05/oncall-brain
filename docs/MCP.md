# On-call Brain as an MCP server

Every graph tool the agents use is defined once in `agents/registry.py`. `oncall_brain.mcp_server` publishes that
same registry over the [Model Context Protocol](https://modelcontextprotocol.io), so Claude Desktop, Claude Code,
the MCP Inspector or any other MCP client can call the tools directly. Two use-case tools sit on top:

| Tool | What it does |
|---|---|
| `reset_tenant` | Restore the tenant's pristine seeded graph (`GRAPH.COPY`), seeding it first if there is none. |
| `respond_to_alert` | Run triage -> investigator -> comms on an alert. Returns the incident id, the outcome (root cause, refuted suspects, who was paged, status update) and a short list of steps. |
| every registry tool | `blast_radius`, `page_on_call`, `recall_similar`, `propose_hypotheses`, `check_hypothesis`, `dependency_path`, `service_map`, `incident_board`, `resolve_incident`, ... (the server lists them all, generated from the registry). |

Every tool takes a required `tenant` (`[a-z0-9_]{1,40}`): each tenant is its own FalkorDB graph `tenant_<name>`.
Registry tools return JSON text `{summary, data, queries: [{name, readonly, rows, ms, cypher}]}`, so the client sees
the exact Cypher behind every answer and whether it ran read-only (`GRAPH.RO_QUERY`). Read-only tools carry the
MCP `readOnlyHint` annotation.

## Run it

FalkorDB must be running (`make db`). Settings come from the environment or `.env` in the working directory
(see `.env.example`). `respond_to_alert` uses the planner chosen by `LLM_PROVIDER` (default: the deterministic one).

```bash
# stdio (what Claude Desktop / Claude Code launch)
python -m oncall_brain.mcp_server          # or: make mcp

# Streamable HTTP at http://127.0.0.1:8001/mcp
python -m oncall_brain.mcp_server --http --port 8001
```

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
             "update_text": "...", "investigator_calls": ..., "hypotheses_checked": ...},
 "steps": [{"seq": 1, "role": "triage", "tool": "open_incident", "summary": "Opened inc:checkout-latency ..."},
           {"seq": 2, "role": "triage", "tool": "blast_radius", "summary": "3 services depend on svc:checkout ..."},
           {"seq": 3, "role": "triage", "tool": "page_on_call", "summary": "Paged Ravi Moreau (@ravi, Checkout) ..."},
           {"seq": 4, "role": "triage", "tool": "handoff", "summary": "triage hands off to investigator"},
           {"seq": 5, "role": "investigator", "tool": "recall_similar", "summary": "Recalled inc:0911 ..."}, ...]}

> resolve_incident {"tenant": "demo", "incident_id": "inc:checkout-latency", "change_id": "chg:pgw-pool-1"}
> respond_to_alert {"tenant": "demo", "alert_id": "alert:refunds-latency"}
  ... act 2: recalled from act 1's memory and confirmed in far fewer checks.
```

## Tests

`tests/integration/test_mcp.py` drives the server in-process with the SDK's own `mcp.Client`. It lists the tools,
seeds a throwaway tenant through `reset_tenant` and calls `blast_radius` on it. It is skipped when FalkorDB is not
reachable.
