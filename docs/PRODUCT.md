# On-call Brain: the product

*Updated 2026-10-16 05:40 IST. The brain is the product; every screen, chat and channel is a window onto it.*

**One line.** An alert fires; On-call Brain tells you what broke, why, who is paged and the fix, with the proof from
your company's graph, and it remembers what you confirmed.

## Who uses it

| Person | Moment | What they need from the brain |
|---|---|---|
| The on-call engineer (20-200 person software company) | 3 AM, paged, five tools open | The likely cause, who else is paged, the fix that worked last time, and enough proof to trust it or reject it in one click |
| The engineer working in Claude Code or Claude Desktop | "checkout is slow, why?" mid-task | The same answer without leaving the editor: an agent that can call the graph tools itself |
| The team lead reading #incidents | Catching up | A status update that names impact, cause, who is on it and its sources |
| Anyone with a company question | "Who owns kafka? Why did we retire legacy-billing?" | A sourced answer from docs, tickets, chat and the service graph, current as of today |

## Where they already work, and how the brain shows up there

| Where they are | How On-call Brain appears | Status |
|---|---|---|
| **Claude Code** (terminal) | A plugin (`plugin/`: `claude --plugin-dir ./plugin`, or `/plugin install oncall-brain --marketplace harz05/oncall-brain`) with the MCP server and three skills: `/oncall-brain:incident <alert>`, `/oncall-brain:who-owns <service>`, `/oncall-brain:ask <question>`. Or the bare server: `claude mcp add ... oncall_brain.mcp_server`. Claude picks the graph tools itself: `respond_to_alert`, `blast_radius`, `dependency_path`, `who_knows`, `ask`, `change_story`, and the write tools (`record_change`, `record_doc`, `record_message`, `record_ticket`, `raise_alert`, `resolve_incident`). | Shipped (`tests/integration/test_plugin.py`) |
| **Claude Desktop / claude.ai** | The same MCP server over Streamable HTTP (`python -m oncall_brain.mcp_server --http`), added as a remote connector, guarded by `API_TOKEN`. | HTTP: shipped. Token on HTTP MCP: this cycle |
| **Their alerting tool** (PagerDuty, Datadog, Grafana, a cron) | A webhook: `POST /api/tenants/{company}/alerts?respond=true` with `service`, `symptom`, `name`. The three agents run headless; the incident, its evidence and the status update land in the graph. | Shipped |
| **Slack** | `/oncall <question>` answers from the graph with sources (follow-ups remember the channel's conversation); `/oncall incident checkout latency` runs the three agents and posts the cause, who is paged and the fix with Confirm cause / Wrong cause buttons that resolve the incident in the graph. Every status update is also posted through an incoming webhook (`SLACK_WEBHOOK_URL`). `docs/SLACK.md` | Shipped (slash command, buttons, webhook) |
| **A browser** | The web UI: an incidents inbox, the answer with Confirm / Wrong cause, "Show me why" (incident subgraph, the three agents' steps, every Cypher query), Ask the brain, Connect. | Shipped; one clarity pass left |
| **Their own code** | The HTTP API (`/api/tenants/{company}/tools/{tool}`) exposes the same registry; every tool is defined once. | Shipped |

The headless path is the one a team would run first: alert in, agents on the graph, answer and update out, nothing
open. The web UI is where a human reviews, confirms or rejects, and where a judge sees the proof.

## The two surfaces we make excellent by Oct 18

1. **The MCP server, installed into Claude Code in one minute.** Tool names, descriptions and argument schemas an
   outside model picks correctly first try (measured: a script gives Claude the tool list and plain questions and
   checks the pick); MCP prompts for the two workflows (work an alert, answer a company question); Streamable HTTP with
   a bearer token for remote clients; the plugin (`plugin.json`, `.mcp.json`, skills, `marketplace.json`) so
   `/oncall-brain:incident alert:checkout-latency` works from a fresh Claude Code.
2. **The headless alert flow with the web inbox as its window.** Webhook in, three agents on the graph, Slack update
   out, and an inbox where the engineer sees the answer first (cause, confidence, impact, who is paged, the fix) and
   can confirm it, with the proof one click away.

Everything else (eval numbers, docs corpus, memory ablation) already exists and is kept green; it is not where the
remaining hours go.

## What the brain is, underneath

One FalkorDB graph per company: services and their dependencies (with `valid_from` / `valid_to`), teams, people and
on-call shifts, deploys and config changes, anomalies, alerts, incidents and what caused and fixed them (memory),
runbooks, docs, tickets and chat. Three agent roles (triage, investigator, comms) hand off through one `Incident`
node; each step re-reads the board from the graph, calls one tool, and is logged as an `AgentStep` with who decided it
(a model, or the rules). Every answer carries its Cypher. Take FalkorDB out and nothing answers.

## Deliberately not built (yet)

- Two-way PagerDuty: the alert webhook in and Slack (`/oncall`, the buttons, the webhook post) cover the loop.
- Per-user authentication: tenants are isolated from each other, not from callers; `API_TOKEN` is the only guard.
- A build step for the UI: one HTML, one CSS, two JS files any judge can read.
