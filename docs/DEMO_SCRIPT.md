# Demo video script (about 2 minutes)

For Harsh to record. Screen: the web UI at http://localhost:8000 (`make db && make dev`), browser at 1920x1080, zoom 100%.
Before recording: click **Reset demo** once so the graph is pristine. Have a terminal ready with `make demo` output and, optionally, an MCP client (see docs/MCP.md).

Say plain words on camera. Leave jargon (p99, PageRank, episodic) for the README.

| Time | Screen | Say |
|---|---|---|
| 0:00-0:12 | UI, idle graph of 25 services | "It's 9:30 in the morning. Checkout is slow and customers can't pay. An on-call engineer has three questions: who is hurt, what broke it, and what fixed it last time. On-call Brain answers all three from one graph in FalkorDB." |
| 0:12-0:25 | Click **Act 1: checkout is slow**. Triage steps animate. | "Triage walks the dependency graph backwards: four services are hurt. Then it looks up who is on call for checkout right now and pages them. Everything an agent does is written back to the graph, so the next agent picks up from there." |
| 0:25-0:55 | Investigator steps animate; graph lights up suspects. | "The investigator first checks memory: an old checkout incident was caused by inventory, but inventory hasn't changed today, so it moves on. It lists every change in the last two hours on services checkout depends on, plus the newest changes anywhere, which is what a plain change log would blame. Then it tests each one against the graph. Cart: deployed, but healthy. Pricing: rolled back before the alert. Search: the newest change, but checkout doesn't depend on search at all. Legacy billing: checkout stopped using it three days ago, and the graph knows when each dependency was live. Payments-gateway: a config change 40 minutes ago, and the slowdown travels gateway, then payments, then checkout. That's the cause, two hops away." |
| 0:55-1:05 | Expand **Cypher** on the payments-gw check. | "Every step shows the exact Cypher it ran, with row counts and timings. Reads use FalkorDB's read-only query command, so a read tool physically can't write." |
| 1:05-1:15 | Comms steps + outcome panel (status update, sources). | "Comms pages the payments team, warns refunds and subscriptions that they depend on the same gateway, and posts an update citing the change ticket and the chat message where it was announced." |
| 1:15-1:22 | Click **Confirm root cause**. Runbook appears. | "A human confirms the fix. The graph now remembers what caused this incident and the runbook that fixed it." |
| 1:22-1:45 | Click **Act 2: refunds is slow**. | "Three days later refunds slows down. The agent recalls Monday's incident, not because the words match, but because the same gateway sits on refunds' dependency path. It tests the remembered cause first, confirms it in one check and suggests the runbook. Eight investigator steps on Monday, three today." |
| 1:45-1:55 | Terminal: `make eval` table (or docs/EVAL.md); optional MCP client calling `who_knows`. | "On thirty generated incidents with planted decoys, the graph agent finds the cause in N of thirty; the change-log baseline finds it in M. The same tools are available to any MCP client, like this one asking who knows the payments gateway." |
| 1:55-2:00 | UI with the lit path. | "FalkorDB is the context: temporal dependencies, a shared hypothesis board, and memory that makes the next incident faster." |

Fill N and M from docs/EVAL.md before recording.

## Backup take
If the UI misbehaves while recording, `make demo` prints the same two acts with the same numbers in the terminal.
