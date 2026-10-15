# Tool pick test: 14/14 on claude-opus-5-5

Run 2026-10-16 04:40 by `python -m scripts.mcp_pick`. The model sees only what an MCP client sees: the server instructions and the tool list (names, descriptions, schemas) from `oncall_brain.mcp_server.catalogue()`. No playbook, no examples. One request, one tool call.

| request | picked | right? | arguments |
|---|---|---|---|
| checkout is slow and alert:checkout-latency just fired. Find out why. | `respond_to_alert` | yes | `{'tenant': 'acme', 'alert_id': 'alert:checkout-latency'}` |
| who owns kafka? | `ask` | yes | `{'tenant': 'acme', 'question': 'who owns kafka?'}` |
| why was legacy-billing retired from the checkout path? | `ask` | yes | `{'tenant': 'acme', 'question': 'why was legacy-billing retired from the checkout path?'}` |
| how do I roll back a bad deploy on cart? | `ask` | yes | `{'tenant': 'acme', 'question': 'how do I roll back a bad deploy on cart?'}` |
| which services would be hurt if payments-gw went down? | `blast_radius` | yes | `{'tenant': 'acme', 'service': 'svc:payments-gw'}` |
| does checkout depend on kafka, directly or through something else? | `dependency_path` | yes | `{'tenant': 'acme', 'from_service': 'svc:checkout', 'to_service': 'svc:kafka'}` |
| who knows payments-gw best? I need someone to review a change there. | `who_knows` | yes | `{'tenant': 'acme', 'service': 'svc:payments-gw'}` |
| where did chg:pgw-pool-1 come from, which ticket and who made it? | `change_story` | yes | `{'tenant': 'acme', 'change_id': 'chg:pgw-pool-1'}` |
| we just deployed cart v3.2.0 (new checkout button), record that. | `record_change` | yes | `{'tenant': 'acme', 'service': 'svc:cart', 'kind': 'deploy', 'summary': 'Deploy cart v3.2.0: new checkout button'}` |
| inc:checkout-latency is confirmed: chg:pgw-pool-1 caused it and reverting it fixed things. | `resolve_incident` | yes | `{'tenant': 'acme', 'incident_id': 'inc:checkout-latency', 'change_id': 'chg:pgw-pool-1'}` |
| show me every service and which team owns it. | `service_map` | yes | `{'tenant': 'acme'}` |
| monitoring says payments p99 latency is 4s since 10:05, note that down. | `record_anomaly` | yes | `{'tenant': 'acme', 'service': 'svc:payments', 'kind': 'latency', 'summary': 'p99 latency 4s since 10:05'}` |
| a new alert: refunds returns 5xx above 1%, on refunds. Register it. | `raise_alert` | yes | `{'tenant': 'acme', 'service': 'svc:refunds', 'symptom': 'errors', 'name': 'refunds returns 5xx above 1%'}` |
| what did the agents do on inc:checkout-latency so far? | `incident_board` | yes | `{'tenant': 'acme', 'incident_id': 'inc:checkout-latency'}` |
