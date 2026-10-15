# Before: first-pass product UI, 2026-10-16 ~04:35 IST

Screens captured with Playwright against the live app (Claude Opus 5.5 choosing every step), tenant `shots`,
1440x900 and 390x844. Files 01-11 desktop, 12-18 phone. Reviews by the ux-critic, hackathon-judge and an
accessibility pass are in `REVIEWS.md` next to this file.

## What a first-time on-call engineer would find confusing (my own pass, before the reviewers)

Landing (01, 17)
- "Your AI on-call teammate" says who, not what. Nothing says "tells you what broke, why and who to page".
- The left panel is a void: "No incidents." plus a "Demo alerts" list whose buttons say **Fire** (reads like a weapon,
  and nothing says these are simulations). The brief wants a "Simulate an incident" menu.
- Header chips are jargon: "planner: claude-opus-5-5", "company: shots", "Reset demo" visible to everyone.
- The 3-step "how it works" is wordy; the hero floats in empty space; CLS 0.2 on load because the landing re-renders
  after the API answers.
- Phone: the header wraps to three rows, the hero is below two scrolls of chips and demo cards.

Working (02)
- Stray "null" text under the tiles (bug, fixed in app.js after the shot).
- Raw ids leak everywhere: `svc:checkout`, `chg:pricing-2140`, "REFUTES ...". The tiles mix machine summaries with
  prose.
- "What the agents can see" is filler; the Slack skeleton is good.

Answer (03, 05, 06, 07)
- The root cause is a line inside a Slack message, not the headline. No confidence, no "seen this before" callout
  (act 2 has the numbers but they sit in a small card bottom-right).
- Wall of text: Impact / Context / Ruled out / Paged / Also at risk / Ask / Sources as one dense message.
- "Why this change" shows the raw reason "anomaly propagates payments-gw -> payments -> checkout".
- "Supported but outranked", "ablation"-style wording in the storm text.
- Good: Confirm button, with/without memory numbers, "Without the graph" card.

Show me why (04, 08, 13)
- The whole 25-service graph is drawn and cut off at the edges; the legend is cut off at the right. The brief wants the
  incident subgraph (path + one hop) fit with padding.
- 18 flat step cards; reasons read "LLM chose blast_radius" (no one-line reason), no Triage / Investigator / Comms
  grouping, no model name on the step.
- "Cypher: 4 querys" (plural bug).

Ask (09, 10, 16)
- The answer is one long paragraph ("Most relevant: ... It concerns ... Also: ...") followed by 5 sources and 14 chips.
  Needs a short answer, then source chips, then "more".
- Phone: the chat is squeezed into ~100px above a 60vh graph.

Connect (11, 12)
- Fine; curl line wraps mid-token on phone.

Phone (13, 14, 16, 17)
- Broken: the inbox list is invisible (the demo list takes the panel), the incident header overlaps the demo list,
  nested scroll areas, graph legend overflows.

Other
- favicon 404 on every load.
