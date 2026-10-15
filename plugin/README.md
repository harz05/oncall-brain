# On-call Brain, as a Claude Code plugin

Incident agents and a company brain over a FalkorDB graph, inside Claude Code. The plugin ships the On-call Brain
MCP server (25 tools, 2 prompts) and three skills:

| Skill | What it does |
|---|---|
| `/oncall-brain:incident <alert_id> [tenant]` | Runs triage, investigator and comms on the alert and reports the likely cause with its confidence, who is paged and who got a heads-up, the fix, what was ruled out and the status update; then offers to confirm the cause so the fix is remembered. |
| `/oncall-brain:who-owns <service> [tenant]` | The owning team, the best person to ask and why, from `who_knows`, `ask` and the on-call rotation. |
| `/oncall-brain:ask <question> [--tenant t]` | A free-form question over the company's docs, tickets, chat, changes and incidents, answered with sources. |

## Setup

The server runs from a checkout of the repository with FalkorDB up:

```bash
git clone <this repository> && cd <repository>
make setup && make db && make seed      # venv, FalkorDB on localhost:6379, the demo company (tenant acme)
claude --plugin-dir ./plugin            # or: /plugin install oncall-brain --marketplace <owner>/<repo>
```

`plugin/bin/oncall-brain-mcp` finds the checkout as the plugin's parent directory; when the plugin is installed
from a marketplace instead, set `ONCALL_BRAIN_HOME=/path/to/checkout` in your environment. It runs the active venv's
interpreter (`$VIRTUAL_ENV/bin/python`, or `ONCALL_BRAIN_PYTHON` if set), else the checkout's `.venv` that `make setup`
creates. Settings (`.env`) are read from the checkout; the deterministic planner needs no key, `LLM_PROVIDER` picks a
model for the agents.

Try: `/oncall-brain:incident alert:checkout-latency`, then `/oncall-brain:who-owns kafka`.
