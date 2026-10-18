# ADR-006: The MCP server is the product; every other surface is a window onto it

Status: accepted, 2026-10-16 (Harsh's direction at 05:20 IST). Complements ADR-005 (the web UI).

## Context

A team would not adopt a new web page for incidents; they would adopt something that shows up where they already
work: Claude Code, Claude Desktop, Slack, their alerting tool. The brain (the graph, the three agents, the memory, the
company-brain tools) is the valuable part; the web inbox is one way to look at it. The hackathon's Track 01 also names
"tool selection via MCP" explicitly.

## Decision

1. **One registry, published as MCP without translation.** `oncall_brain.mcp_server.catalogue()` builds the MCP
   tools from `agents.registry` (docstring, pydantic schema, `writes` -> `readOnlyHint`) plus two use cases
   (`respond_to_alert`, `reset_tenant`). Nothing is defined twice; a tool added to the registry appears in the agent
   loop, the HTTP API and MCP at once.
2. **The schema is the documentation.** An outside model has only the tool list, so every argument carries a
   description with an example id, the server publishes `instructions` (the three workflows and the id formats), and
   `tests/unit/test_mcp_surface.py` fails the build if an argument lacks a description.
3. **Measure the thing that matters: does a model pick the right tool from the list alone?** `scripts/mcp_pick.py`
   gives Claude the instructions and the tool list, nothing else, and 14 plain requests; the result is written to
   `docs/MCP_PICK.md` (14/14 on Opus 5.5 at the time of writing). It is rerun whenever a tool description changes.
4. **Two prompts for the two workflows.** `work_alert(tenant, alert_id)` and `company_question(tenant, question)`
   expand to the user message a skilled operator would type; the Claude Code plugin's skills send the same text, so
   the prompt and the skill cannot drift apart (`prompt_text()` is the single source).
5. **Remote use is guarded.** Streamable HTTP with DNS-rebinding protection on any bind address and, when
   `API_TOKEN` is set, a bearer token on every request; the same token guards the HTTP API.
6. **Headless is a first-class path.** `POST /api/tenants/{t}/alerts?respond=true` (an alerting tool's webhook) runs
   the agents and stores the incident; `SLACK_WEBHOOK_URL` posts the update. `make headless` demonstrates it with
   nothing open. Over MCP the equivalent is `raise_alert` then `respond_to_alert`.
7. **Agents keep their limits on every surface.** `resolve_incident` and the event tools are `agent=False`: an outside
   client (a human in Claude Code) may call them; the product's own agent runs never see them.
8. **A Claude Code plugin packages the install** (`plugin/`: `.claude-plugin/plugin.json`, `.mcp.json`, skills,
   `marketplace.json`), so "install it into Claude Code in one minute" is literal.

## Consequences

- Tool and argument descriptions are product copy now: changing them is a product change and `scripts/mcp_pick.py`
  is the regression test.
- Results returned over MCP include every Cypher statement run, so an outside agent can show its proof the same way
  the web UI does.
- Rejected: a separate "MCP-friendly" tool set with coarser tools. The agents' own tools are already the right
  granularity (one graph question each), and a second set would drift.
- Rejected: MCP resources for the service map and the incident board. Useful, but the same facts are one `service_map`
  / `incident_board` call away; revisit if a client wants to subscribe to board changes.
