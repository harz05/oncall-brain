# After screenshots (Pager rebuild), Oct 18 2026

Captured with headless Chrome (puppeteer-core) against the running server at http://127.0.0.1:8000/web/ by the
scratchpad `after.js` (same state names as `../before/`, plus six new states). Viewports: 1440x900, 768x1024, 390x844.
Files are `<state>-<width>.png` (the first screen). Extras: `-full` = full page at 768/390 when the page scrolls;
`-scrolled` = 1440 scrolled to the bottom. The page now scrolls as a whole on desktop too (the inbox rail stays put).
In `-full` shots the sticky phone/tablet Confirm/Wrong bar shows up halfway down the page. That comes from how
full-page capture works; it is not a layout bug.

Where each state came from:
- `acme` (live, default company): landing, simulate-menu, reset-confirm, keyboard-focus, answer, wrong-cause, why, ask-empty,
  ask-answered, ask-answered-graph (768/390 only), connect.
- `shots` (live, `?tenant=shots`): inbox-with-incidents, answer-confirmed, answer-storm, why-storm.
- `?offline=1&step_ms=1000` (recorded replay, no database): working, working-why, answer-just-confirmed, answer-learned, answer-memory.
  Confirm was clicked only here (fixture `resolve.json`).
- `?tenant=nope` (unknown company): error. `?tenant=uiempty` (a real company with no incidents yet): empty.
- health-down: `acme` with `/api/health` and `/api/tenants/*` answered 503 by request interception (FalkorDB itself stayed up).
- Nothing was confirmed, rejected or reset on a live company. reset-confirm and wrong-cause open the in-place confirm and the
  picker only, then press Escape. The only live model call is Ask ("who owns kafka?"), once per width.

## One line per state

| State | Shows |
|---|---|
| landing | Light Pager page. The open incident "checkout p99 latency above 2s" sits in the ink slab ("Firing", "cause found, fix pending", 09:30 IST) with "Open it and confirm the cause". Under it: the heading with the tagline, the next step as a sentence ("Confirm the cause of … first") above a plain "Simulate an incident: refunds is slow" button, and three ruled how-it-works rows. Rail: "Open 1", with time and date in their own column. At 390 the wordmark stays on one line and the inbox row and status line come before the heading. |
| inbox-with-incidents | `shots`: rail split into "Open 2" (the storm row reads "3 alerts on checkout, refunds and subscriptions, folded into one incident") and "Confirmed 1". Slab: "Open the newest incident". The next step is a sentence ("All 3 demo scenarios have run…"), not a reset button. Facts line: "25 services, 6 teams and 39 dependencies". |
| simulate-menu | Ruled panel (a full-screen sheet at 390): the three scenarios with plain states ("Ran, not confirmed", and why scenario 2 waits), "Raise a custom alert", the planner line, and "Reset demo company" as a quiet text link. |
| reset-confirm | New. Reset asks in place: "Reset the demo company? Every incident, confirmed cause and learned fix on it is deleted…", with "Keep it" filled and focused and "Reset demo company" second. |
| keyboard-focus | New. Six Tabs from the top land on the open incident row, which shows a 3px ink focus outline. |
| answer | Slab: title, tier and owner, and four readout numbers (40 min from change to alert, 4 services hurt, 5 suspects tested, 2 people paged). Tab bar: Answer / Show me why, then Confirm cause / Wrong cause. Ruled rows: Cause ("Very likely" plus the reason), Where (the evidence wire config change pgw-pool-1 → payments-gw → payments → checkout, with times), Since, Who, Do this, Ruled out, Sources, then the status update preview. At 390 the Confirm/Wrong bar is sticky at the bottom. |
| wrong-cause | New. "Which change really caused it?" lists the four other changes with their reason tags and a "This one" button each, plus "None of these? … nothing is saved" and Cancel. |
| answer-confirmed | `shots` stored confirmed incident: "Confirmed" label and "A person confirmed this cause.", no action buttons. Do this reads "The cause is confirmed and the fix is saved to memory as …". The Runbook appears in Sources, and the update reads "resolved, cause confirmed". |
| answer-storm | Storm incident, titled by its alert name, with the storm sentence in the slab ("3 alerts, 1 incident: … fired within 4 minutes and share payments and postgres-orders upstream"). Readout: 21 min from change to first alert, 6 services hurt. The cause is postgres-orders and "explains all 3 alerting services". Since lists the three alert times, and "Also possible: subs-88" has its own row. At 390 the readout label "min from change to first alert" runs into the "6" next to it (see Remaining). |
| why | Light graph fitted around the cause path ("11 of 25 services"), with Show whole company / Zoom out / Zoom in / Fit it all, an evidence-path sentence and a legend in words. Right column: "How the agents got here" ("17 steps and 3 handoffs"), steps grouped by role, each with a question title, "Chosen by Claude Opus 5.5 / the rules", the reason and the result. At 390 the graph is drawn top to bottom with the whole path in view. |
| why-storm | New. Storm subgraph: three alerting services in red, path pg-conn-3 → postgres-orders → payments → subscriptions, subs-88 and search-430 as ruled-out squares, the past incident linked by a memory edge. |
| working | Replay about 6 s in. Slab: "Investigating", the agent's live sentence in plain words ("Investigator: The memory check gave no suspects, so I'm looking at recent changes…"), "Skip the replay", readout 3 / 0 / 1. Below: one ruled row of Triage done / Investigator working (dashed) / Comms waiting, then labelled skeleton rows ("The investigator is testing the suspects. The leading one appears here."). |
| working-why | Show me why while the replay streams: the services touched so far ("12 of 25"), the latest step filled black, untouched services grey, "7 steps and 1 handoff, 0.1 s of graph queries", and Cypher behind "1 query, 1 row, 1.1 ms" rows. |
| answer-just-confirmed | Offline, right after Confirm: the card updates in place ("Confirmed", "You confirmed this cause."), and the inbox moves the row to "Confirmed 1" with "Nothing open right now." |
| answer-learned | The same page scrolled to Do this. "Saved to memory": "Next time a change on payments-gw hurts checkout, 'Revert the config change on payments-gw' is tried first", with the three runbook steps, then Ruled out and Sources. |
| answer-memory | New. Act 2 replayed after act 1 was confirmed. Cause: a payments-gw config change. "Solved from memory": "3 investigator steps instead of 6", "1 suspect tested instead of 4", "Compared with the same alert, run again with memory switched off". Offline, "Confirming this one needs the live server." replaces the buttons. |
| ask-empty | "Ask the brain" heading, a one-line explainer, six example questions as buttons and a labelled "Your question" field. At 1440 the right column holds one line saying the graph appears there. At 390 the page has no empty dark column. |
| ask-answered | "You asked: who owns kafka?", then the lead sentence (time in IST, "20 Oct, 09:30 India Standard Time"), More detail, sources as a dated ruled list (Decision, Runbook, Ticket, Chat, a Decision marked "superseded"), "More linked (9)" and "7 queries, 39 rows, 12 ms". At 1440 the graph on the right is scoped to kafka, its callers, Platform and its people. The follow-up field keeps focus. |
| ask-answered-graph | 768/390. After "Show on graph", the scoped graph opens above the answer and scrolls into view, and the button toggles to "Hide graph". |
| connect | "Connect", with the status as a key/value list (FalkorDB connected, Alert webhook ready, Slack not connected, Claude Opus 5.5, acme). Six numbered steps start with the webhook: curl with Copy command, the Claude Code plugin, Slack, bring your own data, one graph per company with a quiet Reset link, and who decides each step. Code is in Plex Mono blocks. |
| error | `?tenant=nope`: an in-place block, "There is no company called 'nope' here.", with "Open the demo company" and the raw server text behind "What the server said". No toast and no Simulate CTA. The rail says "No incidents to show." and the footer says "Company: none loaded." |
| empty | `?tenant=uiempty`: the rail shows "Open 0" with "No incidents yet. Alerts from your monitoring land here…", and the primary button is "Simulate an incident: checkout is slow". At 390 the rail sits below the hero, so its text is below the fold. |
| health-down | New. Notice at the top: "FalkorDB is not reachable, so incidents cannot load and Simulate is off. Start FalkorDB with `make db`…", plus "Open the replay" and "What the server said". Simulate is disabled, and the footer starts in red with "FalkorDB is not reachable." |

## The 9 before bugs, checked in these shots

1. Offline Confirm left the card unchanged: fixed (answer-just-confirmed).
2. "2 alerts, 1 incident" title and "1 alerts" storm line: fixed (answer: the title is the alert name; answer-storm: storm wording only for 3 distinct services).
3. Truncated inbox subtitle: fixed (inbox-with-incidents: wrapping text, time and date column).
4. Wrong plurals ("1 teams", "1 alerts"): fixed ("6 teams", "1 person paged", "1 suspect tested").
5. Confirmed incident said "No runbook for this yet": fixed (answer-confirmed: Do this reads the confirmed state).
6. Unknown-company toast over the headline: fixed (error: in-place block, plain words, raw text in details).
7. Landing primary became "All demo incidents handled. Reset demo company": fixed (inbox-with-incidents: a sentence; reset only via reset-confirm).
8. Phone "Show on graph" opened off-screen: fixed (ask-answered-graph).
9. snake_case tool names in the live line: fixed (working: "The memory check gave no suspects…").

## Console errors

Every state at every width: no page errors and no unexpected console errors ("unexpected: 0" at 1440, 768 and 390). The only
console errors are the expected 404 on `?tenant=nope` (GET /api/tenants/nope/alerts) and the two 503s the health-down state
injects on purpose. No horizontal scroll at any width.

## Remaining (seen while capturing, not fixed here)

- 390, answer-storm: in the slab readout, "21 min from change to first alert" is wider than its half of the grid, so "first alert"
  runs under the "6" of "6 services hurt". On answer and answer-memory at 390, "…to alert" also touches the "4" next to it.
- 1440, connect: the webhook curl line runs past the code block's right edge. It scrolls sideways; scrollbars are hidden in these captures.
