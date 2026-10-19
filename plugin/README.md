# On-call Brain, as a Claude Code plugin

Incident agents and a company brain over a FalkorDB graph, inside Claude Code. The plugin ships the On-call Brain
MCP server (33 tools, 2 prompts) and three skills:

| Skill | What it does |
|---|---|
| `/oncall-brain:incident <alert_id> [tenant]` | Runs triage, investigator and comms on the alert and reports the likely cause with its confidence, who is paged and who got a heads-up, the fix, what was ruled out and the status update; then offers to confirm the cause so the fix is remembered. |
| `/oncall-brain:who-owns <service> [tenant]` | The owning team, the best person to ask and why, from `who_knows`, `ask` and the on-call rotation. |
| `/oncall-brain:ask <question> [--tenant <tenant>] [--as <person id>]` | A free-form question over the company's docs, tickets, chat, changes and incidents, answered with sources. With `--as`, the question is kept in that person's session in the graph, so a follow-up can say "it". |

The tenant defaults to `acme`, the demo company. Every service name is resolved against the graph; an unknown one is
refused with the closest real services.

## Setup

The server runs from a checkout of the repository with FalkorDB up:

```bash
git clone https://github.com/harz05/oncall-brain && cd oncall-brain
make setup && make db && make seed      # venv, FalkorDB on localhost:6379, the demo company (tenant acme)
claude --plugin-dir ./plugin            # Claude Code with the plugin, from the checkout
```

Or install it from GitHub and set `ONCALL_BRAIN_HOME=/path/to/checkout`:

```
/plugin marketplace add harz05/oncall-brain
/plugin install oncall-brain@oncall-brain
```

`plugin/bin/oncall-brain-mcp` starts the server over stdio. It finds the checkout as the plugin's parent directory, or
at `ONCALL_BRAIN_HOME`. It runs `ONCALL_BRAIN_PYTHON` if set, else the active venv's interpreter
(`$VIRTUAL_ENV/bin/python`), else the checkout's `.venv` that `make setup` creates. Settings (`.env`) are read from the
checkout: the deterministic planner needs no key, and `LLM_PROVIDER` picks a model for the agents.

## Remote mode: nothing local

`.mcp.json` carries a second server, `oncall-brain-remote`, that connects over Streamable HTTP to a deployed
On-call Brain instead of launching one from a checkout (`docs/DEPLOY.md` for the deploy, `docs/MCP.md` for the
transport):

```bash
export ONCALL_BRAIN_URL=https://13-127-186-74.sslip.io  # the deployment (here the live site); the plugin adds /mcp
export ONCALL_BRAIN_TOKEN=<that deployment's MCP_TOKEN>  # sent as "Authorization: Bearer ..."
claude --plugin-dir ./plugin                            # or install from GitHub as above
```

Claude Code expands `${ONCALL_BRAIN_URL:-http://127.0.0.1:8001}/mcp` and `Bearer ${ONCALL_BRAIN_TOKEN}` from your
environment when it starts the plugin's servers, so with neither variable set the entry reaches a local
`make mcp-http`. Both servers publish the same 33 tools and the skills work with either. With no checkout next to the
plugin, the stdio server `oncall-brain` cannot start; Claude Code reports it as failed and the remote server carries
on. `tests/integration/test_plugin.py` reaches a local `--http` server through the remote entry, and
`tests/integration/test_deploy.py` checks that the deployment app's `/mcp` requires the token.

Try: `/oncall-brain:incident alert:checkout-latency`, then `/oncall-brain:who-owns kafka`.
