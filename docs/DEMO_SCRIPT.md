# Demo video script (about 2 minutes)

For Harsh to record. Screen: the web UI at http://localhost:8000 (`make db && make dev`), browser at 1920x1080, zoom 100%.
Before recording: click **Reset demo** once so the graph is pristine. Have a terminal ready with `make demo` output and, optionally, an MCP client (see docs/MCP.md).

Say plain words on camera. Leave jargon (p99, episodic, procedural) for the README.

| Time | Screen | Say |
|---|---|---|
| 0:00-0:10 | UI, idle graph of 25 services | "It's 9:30 in the morning. Checkout is slow and customers can't pay. An on-call engineer has three questions: who is hurt, what broke it, and what fixed it last time. On-call Brain answers all three from one graph in FalkorDB." |
| 0:10-0:22 | Click **Act 1: checkout is slow**. Triage steps animate. | "Triage walks the dependency graph backwards: four services are hurt. Then it looks up who is on call for checkout right now and pages them. Everything an agent does is written back to the graph, so the next agent picks up from there." |
| 0:22-0:50 | Investigator steps animate; graph lights up suspects. | "The investigator first checks memory: an old checkout incident was caused by inventory, but inventory hasn't changed today, so it moves on. It lists every change in the last two hours on services checkout depends on, plus the newest changes anywhere, which is what a plain change log would blame. Then it tests each one against the graph. Cart: deployed, but healthy. Pricing: rolled back before the alert. Search: the newest change, but checkout doesn't depend on search at all. Legacy billing went red first, so even a change log that watches anomalies blames it; but checkout stopped calling it three days ago, and the graph knows when each dependency was live. Payments-gateway: a config change 40 minutes ago, and the slowdown travels gateway, then payments, then checkout. That's the cause, two hops away." |
| 0:50-0:56 | Expand **Cypher** on the payments-gw check; point at the planner badge top right. | "Every step shows the exact Cypher it ran. The planner is rules, not a language model: it picks each step from what the graph returns, and the badge says so." |
| 0:56-1:04 | Comms steps + the **Status update for #incidents** card (Ruled out line, Ask line, sources). | "Comms pages the payments team, names who knows the gateway best, and writes the status update: the likely cause and who made it, what was ruled out and why, and its sources: the ticket, the chat and the design note behind the change." |
| 1:04-1:09 | Click **Confirm root cause**. Runbook appears. | "A human confirms the fix. The graph now remembers what caused this incident and the runbook that fixed it." |
| 1:09-1:25 | Click **Act 2: refunds is slow**. Point at the memory card ("Act 2: same incident", "without → with memory": 6 → 3 investigator calls, 4 → 1 hypotheses checked, culprit on check 2 → check 1) and the Next action line. | "Three days later refunds slows down. The agent recalls Thursday's incident, not because the words match, but because the same gateway sits on refunds' dependency path, and tests the new gateway config change first. This card replays the same incident on the graph without that memory: six calls instead of three." |
| 1:25-1:35 | Optional: click **Act 3: three alerts at once**. Point at the "shared by all 3 alerting services" label. | "Three services alert at once. The agent folds them into one incident and keeps the database config change, which explains all three alerts, over the subscriptions deploy, which explains one." |
| 1:35-1:43 | Terminal: the accuracy table from `make eval` (or docs/EVAL.md). | "On two hundred generated incidents with decoys, noise, missing telemetry and innocent deploys, the graph agent finds the cause in 184. A change log that watches anomalies finds 134. Every miss is listed with the agent's own reasons." |
| 1:43-1:55 | **Ask the brain** tab: type "Why was the payments gateway pool lowered?" and press Enter. Point at the first source and the "Related" list. | "The same graph holds the company's docs, tickets and chat. Ask why the pool was lowered: it finds the cost review that decided it, who wrote it, the change it led to, and the postmortem that warned against it, with every source cited." |
| 1:55-2:02 | UI with the lit path. | "FalkorDB is the context: temporal dependencies, a shared hypothesis board, memory, and the knowledge around it." |

If time runs long, drop the act 3 row: everything else stands without it. Check the eval numbers against docs/EVAL.md before recording. Do not say the update is posted to Slack: it is stored on the incident.

## Backup take
If the UI misbehaves while recording, `make demo` prints the same acts with the same numbers in the terminal.
