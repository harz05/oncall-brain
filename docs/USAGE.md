# Using it

Every way to use On-call Brain: the web inbox, Slack, headless alerts, the HTTP API, MCP, the company brain and live
events. Setup is in the [README](../README.md); MCP clients in [MCP.md](MCP.md); Slack in [SLACK.md](SLACK.md).

## Who chooses each step

No LLM key is needed: by default one deterministic planner plays all three roles, choosing each step by fixed rules
from what the graph returns. To let an LLM choose the tools, set `LLM_PROVIDER` (anthropic, openai, gemini, groq,
openrouter, ollama) and a key in `.env` (see `.env.example`). If the model picks an unknown tool, invalid arguments or
a repeated step, or the API fails, that step falls back to the deterministic planner and the trace says so.
The 200-incident eval numbers come from the deterministic planner.

## Surfaces

- **Web inbox** (`make dev`, then http://localhost:8000): the inbox lists each alert with its state (Investigating, Firing: cause found, Needs a human, Confirmed). **Simulate an incident** runs one of the three scripted alerts, or a custom alert on any service, with the agents working live. The incident leads with the answer: the cause with a confidence label, **Confirm cause** / **Wrong cause**, where it travelled, who is paged, the fix, what was ruled out and why, facts learned late, what a change log alone would have blamed, the sources and the status update. **Show me why** is the proof: the incident subgraph (or the whole company), and the steps grouped by agent (Triage, Investigator, Comms), each with who chose it (Claude or the rules), its one-line reason and the exact Cypher, with FalkorDB's execution time and a **Plan** button per query. Act 2 shows the memory moment ("Solved from memory": 3 investigator steps instead of 6). **Ask the brain** is a chat with sources; **Connect** shows the webhook, MCP, Slack and your-own-data hooks. With no reachable API (`?offline=1`, or the GitHub Pages build) the UI replays recorded runs. Asset URLs carry a version, so a redeploy is never served from a stale browser cache.
- **Headless:** `POST /api/tenants/{t}/alerts?respond=true` with `{service, symptom, name}` records an alert, runs the agents, stores the incident and its update in the graph and, with `SLACK_WEBHOOK_URL`, posts the update to Slack. `POST .../alerts/{alert_id}/respond/stream` streams the run step by step (NDJSON); `GET .../incidents/{id}` returns a stored incident with its outcome and steps, each step with the named queries it ran (`GET /api/queries/{name}` serves a query's Cypher).
- **Slack:** `/oncall <question>` asks the brain; `/oncall incident checkout latency` runs the agents and posts the answer with **Confirm cause** and **Wrong cause** buttons that write back to the graph ([SLACK.md](SLACK.md)).
- **HTTP API:** `GET /api/tools` lists every tool with its JSON schema; `POST /api/tenants/{tenant}/tools/{name}` runs one. Use-case endpoints: `POST /api/tenants/{t}/reset`, `POST /api/tenants/{t}/alerts/{alert_id}/respond` (add `?compare=memory` to also get `ablation.without_memory`: the same alert replayed on a scratch copy of the pristine graph, dropped afterwards), `POST /api/tenants/{t}/incidents/{id}/resolve`.
- **MCP:** the same 31 registry tools, plus `respond_to_alert` and `reset_tenant` (33 in all), every argument described, two prompts, for any MCP client. Agent runs are offered 17 of the registry tools: `resolve_incident`, `my_questions`, `list_incidents`, `query_plan`, `independent_routes` and the nine event tools are for humans and outside clients only, so an agent can neither confirm its own fix nor invent graph facts (the agent loop also refuses them if a planner names one). Run `make mcp` for stdio, or `make mcp-http` for Streamable HTTP on :8001 (bearer token when `MCP_TOKEN` or `API_TOKEN` is set). Details in [MCP.md](MCP.md).
- **Company brain** tools: `ask` answers a free-form question from docs, tickets and chat (full-text search, then the graph around the hits, then an answer assembled from those facts with every source cited; no LLM). `who_knows` ranks who knows a service by ownership, changes they authored, incidents they were paged for and, capped at 3, docs, tickets and chat they wrote about it. `change_story` traces a change to its ticket, chat, docs, author and the incidents it caused. For example, `ask` "Why was the payments gateway pool lowered?" leads with the Q4 cost review design note by Sana Brandt ("Decision: lower the pool max_connections from 200 to 20, which cuts the gateway bill by about 40%"), links `chg:pgw-pool-1`, and lists the peak load test postmortem that warned against it among its sources. Given a `user`, `ask` remembers each question in that person's session: "and who is on call for it?" is read as the previous question's service, and `my_questions` (or asking "what did I ask about payments-gw") lists earlier questions with their sources.
- **Live events**, as tools: `record_change`, `record_anomaly`, `raise_alert`, `add_dependency`, `retire_dependency`, `record_doc`, `record_message`, `record_ticket`, `transfer_ownership`. Push a change and an anomaly, raise an alert, then respond to it: the agents use the new facts at once. A recorded doc, message or ticket is in the next `ask` answer (`test_a_recorded_ticket_shows_in_its_change_and_initiative_stories`). After `transfer_ownership`, an alert pages the team that owned the service at the alert's time (`tests/integration/test_ownership.py`).
- **Exposure:** the API checks the `Host` header (`ALLOWED_HOSTS`) and refuses cross-origin POSTs. `API_TOKEN` optionally requires a bearer token on `/api/*` (not `/api/health`; the bundled UI does not send it). There is no per-user auth: anyone who can reach the API can address any tenant. Keep it on localhost unless you set these.

![Ask the brain answering "Who owns kafka?": the Platform team and who is on call, then its sources (the Kafka retention decision record, the consumer-lag runbook, a ticket, a chat, and the older decision marked superseded), with the answer's subgraph (Platform team, its people, kafka and the services that use it) on the right](img/ask.png)

## Look at the graph in FalkorDB Browser

With `docker compose up`, open FalkorDB Browser at http://localhost:3000 (no login), pick `tenant_acme` and paste:

```cypher
// act 1's live path: checkout -> payments -> payments-gw, every edge live
MATCH p = (:Service {id: 'svc:checkout'})-[:DEPENDS_ON*1..3]->(:Service {id: 'svc:payments-gw'})
WHERE all(r IN relationships(p) WHERE r.valid_to IS NULL) RETURN p
// the dependency checkout stopped calling three days before the alert (a change log still blames it)
MATCH p = (:Service {id: 'svc:checkout'})-[d:DEPENDS_ON]->(:Service {id: 'svc:legacy-billing'}) RETURN p, d.valid_to
// after act 1 has run: the incident board, every hypothesis with the evidence for or against it
MATCH p = (:Incident {id: 'inc:checkout-latency'})-[:HAS_HYPOTHESIS]->(:Hypothesis)<-[:SUPPORTS|REFUTES]-(:Evidence)
RETURN p
```
