# Demo video script (about 2 minutes 15 seconds)

For Harsh to record. Screen: the web UI at http://localhost:8000 (`make db && make dev`, Anthropic key in `.env`
so the badges say Claude Opus 5.5), browser at 1920x1080, zoom 100%. Before recording: open the **Simulate an
incident** menu and press **Reset demo company** so the inbox is empty. Have Claude Code open in a terminal with
the MCP server added (`claude mcp add --transport stdio oncall-brain -- <venv>/bin/python -m oncall_brain.mcp_server`)
for the last segment.

Say plain words on camera. Leave jargon (p99, episodic, procedural, Cypher) for the README.

| Time | Screen | Say |
|---|---|---|
| 0:00-0:10 | The landing: "What broke, why, who's paged, and the fix." | "It's 3 AM. Checkout is slow and customers can't pay. The on-call engineer has three questions: what broke, why, and what fixed it last time. On-call Brain answers them from one graph in FalkorDB." |
| 0:10-0:18 | Click **Simulate an incident: checkout is slow**. The incident opens; the three agent cells light up. | "An alert fires. Three agents pick it up: triage finds who is hurt and pages the on-call, the investigator tests every recent change against the dependency graph, comms writes the update." |
| 0:18-0:45 | Watch the **Suspects** list on the right flip from ? to ✗ while the live line shows Claude's reasons. | "Claude chooses each step, and says why. Five recent changes are suspects. Pricing: rolled back before the alert, out. Search: the newest change anywhere, but checkout doesn't even depend on search, out. Legacy billing went red first, so a change log that watches dashboards blames it; but checkout stopped calling it three days ago, and only the graph knows when each dependency was live. Cart: deployed, but healthy. Payments gateway: a config change 40 minutes ago, and the slowdown travels gateway, payments, checkout. That's the cause, two hops upstream." |
| 0:45-0:58 | The answer card settles: likely cause, "Very likely, 4 of 5 suspects ruled out", who's paged, sources. Point at **What a change log alone would blame**. | "The answer: the payments gateway pool change, by Sana, forty minutes before the alert. Who's paged, who knows the gateway best, and every source: the ticket, the chat, the design note. Without the graph, both change-log methods blame the wrong thing." |
| 0:58-1:06 | Click **Show me why**. The incident subgraph with the orange path; expand one step's Cypher. | "Every step is on record: which agent, what it asked the graph, the exact query, and why. This is the proof, not a chat transcript." |
| 1:06-1:12 | Back to **Answer**. Click **Confirm cause**. The Fix column turns green: saved to memory. | "I confirm. The graph now remembers what caused this and the fix that worked." |
| 1:12-1:30 | **Simulate an incident → refunds is slow**. The memory banner: "Seen this before… 3 steps instead of 6, 1 suspect instead of 4". | "Three days later refunds slows down. It recalls Thursday's incident, not because the words match, but because the same gateway sits on refunds' dependency path, and tries that fix first. Same incident replayed without the memory: six steps instead of three." |
| 1:30-1:42 | **Simulate → Three alerts at once**. The storm line under the title; the storm card. | "Three services alert in four minutes. It folds them into one incident and keeps the database change that explains all three over the deploy that explains one." |
| 1:42-1:55 | **Ask the brain**: "Who owns kafka?" then "Why was legacy-billing retired?". Source chips; the answer subgraph on the right. | "The same graph holds the company's docs, tickets and chat. Who owns kafka, why a service was retired: answered with sources, current as of today." |
| 1:55-2:10 | Claude Code terminal: *"checkout is slow and alert:checkout-latency just fired on tenant acme, find out why"*; Claude calls `respond_to_alert` and reports the cause. | "And the brain isn't the web page. It's an MCP server: from Claude Code, Claude picks the same tools itself, fourteen out of fourteen in our test, and works the incident without the browser open." |
| 2:10-2:15 | Back on the answer card. | "FalkorDB is the context: temporal dependencies, a shared incident board, memory, and the knowledge around it. Take it out and nothing answers." |

If time runs long, drop the three-alerts row. Check `docs/EVAL.md` (186/200) and `docs/MCP_PICK.md` (14/14) before
recording so the numbers you say match. Do not say the update is posted to Slack unless `SLACK_WEBHOOK_URL` is set.

## Backup take
If the UI misbehaves while recording, `make demo` prints the same three incidents with the same numbers in the
terminal, and `?offline=1` replays recorded runs in the UI with no backend.
