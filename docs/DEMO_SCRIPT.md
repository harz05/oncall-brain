# Demo video script (about 2 minutes)

For Harsh to record. Screen: the web UI at http://localhost:8000 (`make db && make dev`), browser at 1920x1080, zoom 100%.
Before recording: click **Reset demo** once so the graph is pristine. Have a terminal ready with `make demo` output and, optionally, an MCP client (see docs/MCP.md).

Say plain words on camera. Leave jargon (p99, PageRank, episodic) for the README.

| Time | Screen | Say |
|---|---|---|
| 0:00-0:10 | UI, idle graph of 25 services | "It's 9:30 in the morning. Checkout is slow and customers can't pay. An on-call engineer has three questions: who is hurt, what broke it, and what fixed it last time. On-call Brain answers all three from one graph in FalkorDB." |
| 0:10-0:22 | Click **Act 1: checkout is slow**. Triage steps animate. | "Triage walks the dependency graph backwards: four services are hurt. Then it looks up who is on call for checkout right now and pages them. Everything an agent does is written back to the graph, so the next agent picks up from there." |
| 0:22-0:50 | Investigator steps animate; graph lights up suspects. | "The investigator first checks memory: an old checkout incident was caused by inventory, but inventory hasn't changed today, so it moves on. It lists every change in the last two hours on services checkout depends on, plus the newest changes anywhere, which is what a plain change log would blame. Then it tests each one against the graph. Cart: deployed, but healthy. Pricing: rolled back before the alert. Search: the newest change, but checkout doesn't depend on search at all. Legacy billing went red first, so even a change log that watches anomalies blames it; but checkout stopped calling it three days ago, and the graph knows when each dependency was live. Payments-gateway: a config change 40 minutes ago, and the slowdown travels gateway, then payments, then checkout. That's the cause, two hops away." |
| 0:50-0:58 | Expand **Cypher** on the payments-gw check. | "Every step shows the exact Cypher it ran, with row counts and timings. Reads use FalkorDB's read-only query command, so a read tool can't write." |
| 0:58-1:08 | Comms steps + outcome panel (status update, Ask line, sources). | "Comms pages the payments team, asks the graph who knows the gateway best and names that person in the update, warns refunds and subscriptions, and cites the change ticket and the chat message where it was announced." |
| 1:08-1:14 | Click **Confirm root cause**. Runbook appears. | "A human confirms the fix. The graph now remembers what caused this incident and the runbook that fixed it." |
| 1:14-1:32 | Click **Act 2: refunds is slow**. Point at "culprit on check 1" and the Next action line. | "Three days later refunds slows down. The agent recalls Thursday's incident, not because the words match, but because the same gateway sits on refunds' dependency path. The runbook that fixed it points at gateway config changes, so it tests the new one first, confirms it in one check and says what to do next. Eight investigator steps on Thursday, three today." |
| 1:32-1:42 | Optional: click **Act 3: three alerts at once**. Point at the shared upstream. | "Two days later, three services alert at once. The agent folds them into one incident and finds where their dependencies meet. Two changes look guilty; it keeps the database config change, which explains all three alerts, over the subscriptions deploy, which explains one." |
| 1:42-1:52 | Terminal: `make eval` table (or docs/EVAL.md); then the UI's **Ask the brain** tab, or an MCP client calling `who_knows`. | "On two hundred generated incidents with planted decoys, the graph agent finds the cause in all 200; a change log that also watches anomalies finds 141, keyword matching 59, and the newest-change log none. You can ask the same graph who knows a service, here or from any MCP client." |
| 1:52-2:00 | UI with the lit path. | "FalkorDB is the context: temporal dependencies, a shared hypothesis board, and memory that makes the next incident faster." |

If time runs long, drop the act 3 row: everything else stands without it. Check the eval numbers against docs/EVAL.md before recording.

## Backup take
If the UI misbehaves while recording, `make demo` prints the same acts with the same numbers in the terminal.
