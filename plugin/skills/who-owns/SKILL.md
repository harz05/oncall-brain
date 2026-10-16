---
name: who-owns
description: Find who owns or knows a service with On-call Brain. Use for questions like "who owns kafka", "who should review a change to payments-gw", "who is on call for checkout", or whenever a person or team for a service is needed.
argument-hint: <service> [tenant]
---

Answer who owns or knows the service named in `$ARGUMENTS` from the company graph, with the On-call Brain MCP
tools (server `oncall-brain`, or `oncall-brain-remote` when the plugin points at a deployed instance). The first word is the service (a name like `kafka` or an id like `svc:kafka`;
ids are `svc:<name>`); the second, if present, is the tenant, default `acme`.

1. Call `who_knows` with the tenant and the service id. It ranks people by evidence: owning team, changes they
   made there, incidents they were paged for, docs, tickets and chat they wrote about it.
2. Call `ask` with the tenant and the question "who owns <service>"; it names the owning team and cites sources.
3. If the question is about who is on call now, call `page_on_call` with the service and no incident id: it reads
   the rotation and pages nobody.
4. Answer in one or two sentences: the owning team, the best person to ask and why (the evidence behind their
   rank), then the sources. Use handles and ids exactly as returned. If the service is unknown, say so and call
   `service_map` to list the services that exist.
