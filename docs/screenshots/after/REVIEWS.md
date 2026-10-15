# Reviews of the after screenshots (round 2)

## UX critic

### Landing / empty inbox (05-landing-empty-1440.png)
**Score: 8/10**
**10-second test:** Dark incident tool. "What broke, why, who's paged, and the fix." plus three numbered cards and one orange button. I know it triages alerts with agents over a service graph, it is for on-call engineers, and I would click the orange button. Matches the purpose.
**Blockers:** none.
**Major:**
- M1 Footer, bottom-left (y≈863–881): "FalkorDB connected · steps chosen by Claude Opus 5.5 · company: after1". "after1" is a test-fixture name leaking into the product (same class of bug as "shots390" last round). Show a display name ("Demo company") or nothing.
**Minor:**
- m1 Cards 1 and 3 are 60% empty because card 2 sets the row height (y 335–520). Let the cards size to content or shorten card 2.
- m2 Header right: "Simulate an incident ▾" and an unlabeled "···" button. I have no idea what "···" opens.
- m3 Two entry points for the same action (header dropdown and hero button). Fine, but the hero button says "checkout is slow" while the dropdown says the same thing only after opening it.
**What works:** The headline is a plain promise and the three cards explain the product better than most landing pages. Sidebar empty state ("No open incidents. Alerts from your monitoring land here. Simulate one, or connect your alerts.") is exactly right.

### Simulate menu (06-simulate-menu-1440.png)
**Score: 8/10**
**10-second test:** A dropdown with three scenarios, each with a one-line hook and a "Simulate" button, a "Raise a custom alert" expander, and "Reset demo company". I know these are canned alerts and that the agents are real ("Synthetic company, real agents"). I would click the first Simulate. Matches.
**Blockers:** none.
**Major:**
- M1 "This company: after1" (y≈394) again, the test tenant id in a user-facing menu.
**Minor:**
- m1 Inconsistent casing: "checkout is slow", "refunds is slow", "Three alerts at once".
- m2 "Reset demo company" is destructive and sits one click away with no hint of what it wipes.
- m3 The dropdown paints over the hero headline; expected, but the right edge at x≈1378 is 60px from the viewport edge with the "···" button orphaned beside it.
**What works:** Each scenario tells me why it is interesting in one line ("One shared cause, or three?"). "Synthetic company, real agents" is the honest tag a judge wants to see.

### Incident while the agents work (07-act1-working-1440.png)
**Score: 7/10**
**10-second test:** Investigating pill, three agent tiles (Triage done, Investigator working with a yellow outline, Comms waiting), a live sentence from the investigator, a leading suspect filling in, and a Suspects list on the right with open / ruled out / supported states. I know agents are working on a checkout latency alert and what they are checking right now. Matches. The "null" is gone.
**Blockers:** none.
**Major:**
- M1 Likely-cause title (y 418–445): "max_connections 200 -\n> 20 (cost cleanup)". The ASCII "->" breaks across lines, leaving "-" at the end of one line and "> 20" starting the next. Use "→" or a non-breaking arrow. Appears on 07, 08 and 09.
- M2 Live line (y≈265): "There are still two open hypotheses". The panel to the right says "SUSPECTS". Still "hypotheses" (flagged last round). Use one word.
- M3 Card header says "Likely cause" while the suspects list still shows cart-310 as "open". Call it "Leading suspect" until the investigator finishes, then "Likely cause".
**Minor:**
- m1 "Seen something like this: 'Checkout slow during flash sale' (0911)" — "(0911)" is an id. Drop it or make it a link.
- m2 FIX tile shows a grey skeleton bar with no label; say "waiting for the cause".
**What works:** The agent strip with the yellow working outline and the Suspects panel with per-suspect verdicts is a real "watch it think" view; "Ruled out: pricing-2140 on pricing · change was rolled back before the alert fired" is the right sentence.

### Incident answer (08-act1-answer-1440.png)
**Score: 8/10**
**10-second test:** "Cause found". A boxed likely cause with the change, the author, "40 min before the alert", a green "Very likely · 4 of 5 suspects ruled out" pill, then Confirm cause / Wrong cause / Show me why. Below: What broke, Who's paged, Fix; Ruled out with one reason each; the path. Right rail: what a change log alone would blame, Sources with types and titles. I know what happened and what to do. Matches, and this is close to what I would write by hand.
**Blockers:** none.
**Major:**
- M1 Same "200 -\n> 20" line break in the money card (y 245–272).
- M2 Right rail footer (y≈715): "Steps chosen by Claude Opus 5.5 · 93k tokens". Token count is a developer metric on an on-call screen; move it to "Show me why".
**Minor:**
- m1 "(0911)" id in the "Seen something like this" line.
- m2 "Show me why →" link next to the buttons duplicates the "Show me why" tab in the header. One is enough.
- m3 FIX panel copy "No runbook for this yet. Confirm the cause and the fix is saved for next time." is good; keep.
**What works:** Confirm button now says "Confirm cause" (fixed), path chips and sentence agree in direction (fixed), Sources are typed chips with titles (fixed), "What a change log alone would blame" now explains itself in one sentence (fixed).

### After Confirm cause (09-act1-confirmed-1440.png)
**Score: 7/10**
**10-second test:** Green "Confirmed" pill, "Cause confirmed" card, "Confirmed by you", FIX now reads "SAVED TO MEMORY: Next time a change on payments-gw hurts checkout, 'Revert the config change on payments-gw' is tried first. Show 4 steps". I confirmed, it saved. Matches.
**Blockers:** none.
**Major:**
- M1 Sidebar header (y≈85): "0 open · 1 confirmed". Confirming a cause has removed the incident from "open". Nobody has reverted anything. Keep it open (or "Identified") until someone resolves it; the status rename to "Confirmed" (fixed) is undone by this count.
- M2 Same "200 -\n> 20" break.
- M3 FIX card: the inline "SAVED TO MEMORY" pill is followed by "Next" on the same line, then the sentence wraps over seven lines in a narrow column (y 430–570). Put the pill on its own line.
**Minor:**
- m1 Sources order is now stable between 08 and 09 (fixed).
- m2 "Also at risk: refunds, subscriptions" still shown; acceptable now that the incident is not "Resolved".
**What works:** "Confirmed" instead of "Resolved", no "last time" written from the future, no "1 of 1 times" (all fixed from last round). The saved-runbook sentence is concrete.

### Second incident, memory banner (10-act2-memory-1440.png)
**Score: 6/10**
**10-second test:** Purple "Seen this before." banner naming the previous incident and the fix, big "3 steps instead of 6" and "1 suspect tested instead of 4", likely cause on payments-gw, FIX "Revert the config change on payments-gw · confirmed once". I understand that memory shortened the investigation. Matches; still the best demo moment.
**Blockers:**
- B1 No "Wrong cause" button (y≈469: only "Confirm cause" and "Show me why →"). Flagged last round, still missing. This is the one incident where the answer came from memory, i.e. the one place a wrong memory would be repeated forever. If I cannot disagree here, the memory feature is a trap.
**Major:**
- M1 Right rail "Change log + anomalies: pgw-pool-2 SAME ANSWER" (y≈241). "pgw-pool-2" appears nowhere else on the screen; the likely cause is titled "Config rollout 2026.10.18: payments-gw max_connections 200 -> 25". I cannot verify "same answer" without the id mapping.
- M2 Banner: "'checkout p99 latency above 2s' (checkout-latency) was fixed with…" — the slug in parentheses is an id.
**Minor:**
- m1 "Status update drafted for #incidents · preview · Connect Slack to post it" is good; it belongs above the fold, not under the path.
- m2 "61k tokens" in the right rail footer again.
**What works:** The banner numbers are instantly legible and the sentence "so the same fix was tried first" explains the whole feature. "confirmed once" (fixed) is honest.

### "Show me why", second incident (12-act2-why-1440.png)
**Score: 7/10**
**10-second test:** Graph "Showing 18 of 25 services: what this incident touched, plus one hop", orange path refunds → payments → payments-gw with a diamond change, a purple memory link from refunds-latency to checkout-latency to a runbook, legend wrapped and readable. Right: "Agent steps · 13 · 0.1 s on the graph", grouped by TRIAGE / INVESTIGATOR with the handoff sentence as the group header, each step a plain question ("Who depends on refunds?"), a "Rules" or "Claude Opus 5.5" badge, a WHY line, and a Cypher expander. I know what it is and could defend it. Matches.
**Blockers:** none.
**Major:**
- M1 Graph labels are ~8px ("subscriptions", "inventory", "refunds-latency", "Quinn Tanaka"). Unreadable in a demo video or from across a room. Fit to panel with a larger min zoom.
- M2 People (Asha Nakamura, Sana Brandt, Quinn Tanaka, Bram Mensah, Lena Costa, y 590–680) and "Payments team" sit in a column with no visible edges to anything. Either draw their edges or drop them from this view.
- M3 The change diamond "pgw-pool-2" (765, 455) hangs between payments and payments-gw, nearer payments; the change is on payments-gw. Anchor it to payments-gw.
**Minor:**
- m1 Tool ids in monospace next to the titles ("open_incident", "blast_radius") are tolerable for engineers now that the verb title leads, but they compete with the "Rules" badge for the same line.
- m2 Dimmed nodes (auth, inventory, cart, pricing, search) are close to invisible; if they are the "one hop", give them a readable grey.
**What works:** Continuous numbering with the handoff as a group header (fixed), plain-English step titles with a reason (fixed), "queries" spelled right (fixed), legend wraps (fixed), the memory chain at the bottom is the clearest picture of cross-incident memory in the app.

### Alert storm answer (02-stored-storm-answer-1440.png)
**Score: 6/10**
**10-second test:** "3 alerts, 1 incident" with a sub-line that says which three and what they share, likely cause on postgres-orders with "explains all 3 alerting services", Confirm / Wrong cause / Show me why, an ALERT STORM panel on the right. I understand three alerts were correlated to one change. Matches.
**Blockers:** none.
**Major:**
- M1 Ruled-out area (y≈755): "Also possible: subs-88 on subscriptions · pg-conn-3 explains every alerting service this change does (1) and 2 more". Still garbled (flagged last round), and "pg-conn-3" is an id that appears nowhere else on the screen (the cause is titled "postgres-orders max_connections 500 -> 150"). Say "Also possible: subs-88, but it only explains subscriptions; the postgres-orders change explains all three."
- M2 WHAT BROKE (y 451–520): the three alert names are joined with " · " and wrap so that lines 2 and 3 start with a lone "·". Render them as three lines.
- M3 Sidebar: "checkout, refunds, subscript…" truncated (still open from last round); the title fits on two lines.
**Minor:**
- m1 Footer "company: shots" (a different test tenant from the other screens).
- m2 Right rail "WHAT A CHANGE LOG ALONE WOULD BLAME: subs-88 WRONG" uses an id that is only explained by the garbled line above.
**What works:** The ALERT STORM panel ("Nearest shared upstream: payments, postgres-orders. Without correlating them first, the same agents blame a change that explains only one alert.") is the clearest explanation of a graph feature in the app. The header sub-line is new and good.

### "Show me why", alert storm (03-stored-storm-why-1440.png)
**Score: 5/10**
**10-second test:** A graph with one red-outlined service (subscriptions) and an orange path to postgres-orders, sitting in the bottom half of the panel; the agent steps on the right include "Do these alerts share a cause?". I can tell it is the evidence view but I cannot see a storm: only one service is marked alerting.
**Blockers:** none.
**Major:**
- M1 Only "subscriptions" has the red alerting outline (427, 529); "checkout" (427, 463) and "refunds" (427, 578) are plain. The legend promises purple "shared upstream" and none is drawn (payments and postgres-orders are orange only). The correlation this screen exists to show is not on the graph. Last round's version had three red outlines and purple nodes; this is a regression.
- M2 Sidebar says "Open" for "3 alerts, 1 incident" and "refunds p99 latency above 2s" (y 131, 191) while the header pill says "Cause found" and screen 02 said "Cause found" for the same incidents. Two states for one incident on one screen.
- M3 Steps 2–4 carry a "Rules" badge and a reason line "WHY LLM chose correlate_alerts" (y 498, 614, 749). The badge and the reason contradict each other, and "LLM chose X" is not a reason. Stored runs need the same plain-English WHY the new runs have, or the WHY should be hidden when it is just the tool name.
- M4 Graph is not fitted: the top 200px of the panel (y 160–350) is empty, edges from subscriptions and checkout run off the left edge at x≈320 to nodes outside the viewport, and labels are ~9px.
**Minor:**
- m1 Steps 1–4 have no "Cypher · n queries" expander while screen 12 does; inconsistent.
- m2 Sidebar titles truncated again.
**What works:** Grouped steps with the handoff sentence read well, and "3 related alerts on 3 services (…); 6 upstream services are shared by all of them, nearest to all first: payments, postgres-orders, fraud-check" is the fact I want.

### Ask the brain (13-ask-answer-1440.png)
**Score: 5/10**
**10-second test:** A chat bubble "Who owns kafka?" top right of the left pane, an answer card below it, typed Sources (Decision, Runbook, Ticket, Chat, a superseded Decision), "More linked (9)", a Cypher line, and a graph on the right "Showing what this answer is linked to". It is a Q&A over the company graph. But the answer card starts with "costa) is on call as of the latest alert in the graph…" — mid-word.
**Blockers:**
- B1 The answer is clipped at the top of its own card (card border at y≈135, first visible text "costa) is on call…" at y≈153). The sentence that answers "Who owns kafka?" (the team, the owner) is not on screen; what I see starts in the middle of "@hana.costa". Either the card clips its content or the answer text really begins there; either way the one line I came for is missing.
**Major:**
- M1 Graph highlights do not match the answer: "Data" team with yellow edges to "reporting" and "analytics" gets the same weight as "Platform" → "kafka"; "Jae Haddad" and "Pia Petrov" float with no edges; "Omar Tanaka", named in the text as a member, is not drawn. For "who owns kafka" I expect kafka → Platform → people, nothing else lit.
- M2 No one-line answer pinned above the sources ("kafka: Platform team, on call: Hana Costa"); the card goes straight into a paragraph and then a "More detail" expander.
**Minor:**
- m1 Left pane is 60% empty below the card (y 460–840); fine for a chat, but the input is 400px away from the answer.
- m2 Yellow dotted edges are the only edge style not in the legend.
**What works:** "queries" spelled right, STATUS_UPDATE badge gone, linked chips capped with "More linked (9)", the superseded ADR shown with a "superseded" tag next to the current one is exactly the "is this still current?" signal Track 03 asks for.

### Connect (14-connect-1440.png)
**Score: 4/10**
**10-second test:** "Plug it into your stack", four status chips (FalkorDB connected, Alert webhook ready, Slack not connected, Steps chosen by Claude Opus 5.5), six cards. I would copy the curl. Then I see the top three cards painted over each other.
**Blockers:**
- B1 The top row of cards overlaps. Card 1's code block runs under card 2: the curl is cut at "http://localhost:8000/api/tenants/a" (x≈545) and its last line "-d '{"service": "svc:checkout", …}'" reappears under card 2's code area (x 585–915, y 337). Card 2's "claude mcp add --transport stdio oncall-brain --" is cut at x≈925 by card 3, and its second block "python -m oncall_brain.mcp_server --http --port 8001 [Copy]" extends to x≈1325, over card 3. Card 3's text overflows its right border: "(Apps → Incoming" at (1280–1390, 244) renders with overlapping glyphs, and a fragment "HTTP instead:" at (1020, 338) is half hidden. The one page an adopter opens to install it, and the commands cannot be read or copied. Cause is almost certainly `white-space: pre` (last round's fix) on a grid child with the default `min-width: auto`; add `min-width: 0` on the cards and `overflow-x: auto` on the code blocks.
**Major:**
- M1 Card 1 and card 2 body text is also cut by the overlap ("map its payl…", "who depends on wh…").
**Minor:**
- m1 "This company: after1" in card 5.
- m2 Card 4 bullets in monospace (record_change, record_anomaly…) are fine; the "idempotent MERGE" footnote is still jargon, glossed only partially.
**What works:** The status chip row answers "is it wired up?" in one glance; "Every agent tool is defined once and exposed three ways" is the right one-line pitch; tenant now glossed as "(tenant)".

### Static replay landing (11-offline-replay-landing.png)
**Score: 5/10**
**10-second test:** Identical to the live landing: same hero, same orange "Simulate an incident: checkout is slow", same "Connect your alerts", footer "FalkorDB connected · steps chosen by Claude Opus 5.5 · company: acme". Nothing tells me this is a recording.
**Blockers:**
- B1 The status line claims "FalkorDB connected" and "steps chosen by Claude Opus 5.5" on a static page with no database and no model behind it. A judge who notices is told the product lied; an engineer clicks "Connect your alerts" and gets a page that cannot connect anything. Replace the footer with "Recorded replay · no database · run it locally to go live" and rename the button "Replay a recorded incident".
**Major:**
- M1 Header tagline truncated: "with the proof from your service…" (x≈630, y≈52) at a wider viewport than 1440, where it fits.
**Minor:**
- m1 "company: acme" vs "after1" vs "shots" across screens; the id has no meaning to a visitor anywhere.
**What works:** Everything that works on the live landing works here; it just needs to say what it is.

### Incident answer at 390px (04-stored-storm-answer-390.png)
**Score: 7/10**
**10-second test:** Likely cause card, author and timing, the green "Very likely" pill, Confirm / Wrong cause / Show me why, What broke, Who's paged, Fix. On a phone, scrolled to the card, I get the cause and the button. Matches. No overlap, no clipped edges, 16px gutters.
**Blockers:** none.
**Major:**
- M1 "✓ Confirm cause" wraps to two lines inside the green button (y 322–382) while "Wrong cause" stays on one; the two buttons are different heights. Give the row `flex-wrap` or shorten to "Confirm".
**Minor:**
- m1 WHAT BROKE joins the three alerts with middots over three lines (same as 02).
- m2 "500 -> 150" ASCII arrow (did not break here, but will at a narrower width).
- m3 Cannot judge the header or inbox from this crop; last round's overlap bug is not visible in this capture, so it is neither confirmed fixed nor open.
**What works:** The card stack reads top to bottom with no nested scroll region in view; the paged people with team and "on-call for X" are readable at thumb distance.

## Overall
**Lowest score:** 4/10 on Connect (14-connect-1440.png)

**Fixed since last round / still open:**
- Fixed: "null"/"nullnull" gone on every incident screen; Confirm button names the cause, not an id; "Confirmed" instead of "Resolved" and no "last time"/"1 of 1 times" copy; "Wrong cause" present on act 1 and the storm; path chips and sentence agree in direction; Sources are typed chips with titles; "querys" typo; linked chips capped ("More linked (9)"); STATUS_UPDATE badge gone; "planner: claude-opus-5-5" chip replaced by "Steps chosen by Claude Opus 5.5"; "decoy" gone; svc:/inc:/chg: prefixes gone from human text; "REFUTES" → "Ruled out:"; "Skip animation" → "Skip to answer"; legend wraps; agent steps numbered continuously with the handoff as a group header; step titles are questions with a WHY line and a model badge (new runs); "Without the graph" panel now explains itself; memory numbers "3 steps instead of 6"; sidebar empty state; 390 answer card no longer overlaps anything in the captured region.
- Still open: no "Wrong cause" on the memory incident (10); garbled "Also possible: subs-88 … (1) and 2 more" (02); "hypotheses" vs "suspects" (07); test tenant ids in the footer/menu ("after1", "shots", "acme"); graph labels ~8px and people nodes with no edges (12, 03); sidebar titles truncated (02, 03); "WHY LLM chose X" on stored runs, now contradicting a "Rules" badge (03); storm graph lost its three red outlines and purple shared-upstream nodes (03, regression); Connect code blocks went from wrapping mid-token to overlapping the neighbouring cards (14, regression). New: ASCII "->" breaking as "200 -\n> 20" on 07/08/09; Ask answer clipped at the top of its card (13); replay landing claims "FalkorDB connected" (11); sidebar "Open" vs header "Cause found" on the same incident (03); "0 open" the moment a cause is confirmed (09).

**Top 5 fixes, in order of impact**
1. Connect (14): stop the top-row cards overlapping (`min-width: 0` on grid cards, `overflow-x: auto` on code blocks) so the curl and the `claude mcp add` line can be read and copied; this is the install page for the MCP-first pitch.
2. Ask (13) and replay (11): make the one-line answer the first visible text in the card (nothing may start mid-word), and on the static replay replace "FalkorDB connected · steps chosen by Claude Opus 5.5" with "Recorded replay · no database".
3. Add "Wrong cause" to every screen that proposes a cause (10), and rewrite the storm's "Also possible" line to "subs-88 only explains subscriptions; the postgres-orders change explains all three" (02).
4. Storm "Show me why" (03): red-outline all three alerting services and draw the purple shared-upstream nodes again, fit the graph so no edge leaves the panel, give stored runs the same plain WHY text as new runs, and make the sidebar badge match the header pill.
5. Replace "->" with "→" in change titles so "200 -\n> 20" never breaks (07/08/09), keep the incident counted as open after Confirm cause (09), and replace "company: after1/shots/acme" with a display name or nothing.

**Ship it?** Not yet: the desktop incident flow has crossed from demo rig to product, but the Connect page an adopter opens first is visibly broken, the Ask answer starts mid-word, and the static replay claims a live database, and those are the three screens a judge checking "MCP-first, honest, explainable" would open.

## Hackathon judge, round 2

## Rule 2 check
Unchanged from round 1 and still true: every tool is a named, parameterised Cypher statement run through `FalkorRepository._run` (`src/oncall_brain/adapters/falkordb/repository.py:44-57`, reads via `ro_query`), the planner's only input is the board re-read from the graph before each step (`agents/loop.py:40-41` -> `services/board.py`), and memory, handoffs, the status update and the company brain are nodes and edges (`queries/*.cypher`, 87 named statements, 1,711-line generated `docs/QUERIES.md`). `make test`: 178 passed in 24 s against the live FalkorDB (unit + integration, incl. `test_tenants_are_isolated`, `test_mcp_exposes_every_registry_tool_and_runs_them_on_a_tenant`). The MCP server itself refuses a tenant with no graph (`mcp_server/__init__.py:_repo`). The only graph-less path is the GitHub Pages replay, labelled "recording" (commit 3c49593). Still no `algo.*` anywhere (`grep -rn "algo\." src/` empty). **Verdict: indispensable.**

## Track scores

### Track 01: 8/10
For: temporal multi-hop traversals and `shortestPath` refutations unchanged (`investigate.cypher`); the LLM path is now the default when a key exists and the recordings prove it: `web/fixtures/act{1,2,3}.json` carry 46 steps `"by": "claude-opus-5-5"` and 3 `"rules"` (the handoffs); `docs/LLM_RUN.md` 60/60 model decisions, 0 fallbacks; every step shows a model/rules badge and a one-line reason (screenshot 12). MCP is a stronger "tool selection" story than round 1: server `instructions`, 24 tools with every argument described (verified live with `catalogue()`; `tests/unit/test_mcp_surface.py` gates it), `readOnlyHint`, two prompts, and `docs/MCP_PICK.md` 14/14 picks from the tool list alone. Actions written back unchanged.
Against/missing: still no graph algorithm as a tool (the track names them; the README's betweenness rejection is honest but is a "no"). The LLM prompt "states the same rules the deterministic planner follows" (`LLM_RUN.md`), and `domain/planner.py` is still a 102-line decision tree, so no screenshot shows a decision the rules would not have made. Screenshot 03 (stored storm) has steps badged `Rules` while the reason text reads "WHY LLM chose correlate_alerts": a contradiction a judge will spot. `scripts/mcp_pick.py` needs an Anthropic key and is not in `make test`.
A 10 would: at least one `algo.*` (PageRank/WCC on the live-at-alert subgraph) the planner chooses, with a trace line showing it changed page/warn order or split a storm.

### Track 02: 8/10
For: episodic (`Incident`+`CAUSED_BY`+`AgentStep`), semantic (`valid_from/valid_to`, `SUPERSEDES`), procedural (`Runbook uses/successes`) all graph structure; cross-session memory is now the clearest moment in the product (screenshot 10: "Seen this before... 3 steps instead of 6, 1 suspect instead of 4"); handoffs are first-class in the UI (screenshot 12 "Handed to investigator: ..."); "Confirmed" replaces the wrong "Resolved" state (screenshot 09); one graph per tenant with `GRAPH.COPY` resets.
Against/missing: nothing moved on concurrency. `grep -rn constraint src/` is empty, `tests/integration/test_concurrency.py` does not exist, and the per-tenant Redis lock (`repository.py:35-42`, 15-min lease) still serialises every write. The fix is sitting unapplied in `collab/patches/rival-004-constraints-atomic-reset-concurrency.patch` (800 lines: unique constraints, atomic RENAME reset, 5 tests, p50/p95 numbers) with ACK.md saying "waiting". Per-user memory still absent (tenant only); the three "agents" remain three role functions in one process.
A 10 would: constraints + measured concurrency (the patch), per-incident locking, and a per-engineer session/question memory.

### Track 03: 7/10
For: docs/tickets/chat in the same graph (`datagen.py`, 34/41/21), `ask` answers "Who owns kafka?" with a short answer, titled source chips with kind badges (Decision, Runbook, Ticket, Chat), a `superseded` flag on ADR-006, "More linked (9)" and the answer subgraph (screenshot 13: Platform team -> kafka -> people), `who_knows`/`change_story`, `CITES` on every status update; `tests/integration/test_brain.py`.
Against/missing: in the one Ask screenshot the answer sentence is scrolled off ("costa) is on call as of the latest alert..."), so the first impression is again a source list; the corpus is tiny and seed-only (no tool to add a doc/ticket/message, per SCORECARD T3-4); ownership has no validity, so "who owned X when" has no answer; the "why" path (decision -> source -> author -> still current?) is a chip list, not a lit path like incidents get.
A 10 would: a `record_doc`/ownership-transfer event with a test showing an `ask` answer flip, and the decision chain rendered as a path.

## MCP surface: 7/10
What an outside agent gets (verified by `python -c "from oncall_brain.mcp_server import catalogue..."`): 24 tools, names a model reads correctly (`blast_radius`, `dependency_path`, `who_knows`, `record_change`...), descriptions of 40+ chars, every argument described with an example id, `tenant` required first, `readOnlyHint` right (16 writers incl. `who_knows`), server `instructions` listing the three workflows and id formats, prompts `work_alert` and `company_question` (which Claude Code already exposes as `/oncall-brain:work_alert`), JSON results that include every Cypher run, tool errors returned as `isError` instead of killing the session, lazy store so `tools/list` works with FalkorDB down, `reset_tenant` that seeds on first use. Stdio and Streamable HTTP (`__main__.py`), Host/Origin rebinding protection on any bind, bearer token when `API_TOKEN` is set (`test_remote_mcp_requires_the_token_when_one_is_set`). `docs/MCP.md` is a real integration doc with a verbatim session and headless `curl` (`api/app.py:173-178`, `adapters/slack.py`). 14/14 first-try picks in `docs/MCP_PICK.md`.
Missing for "install into Claude Code in one minute": **there is no plugin.** `find . -name plugin.json -o -name .mcp.json -o -name marketplace.json -o -name SKILL.md` returns nothing; `docs/PRODUCT.md` and `docs/MCP.md` say "in progress / see the README once it lands"; the uncommitted README links to `#use-it-from-claude-code-in-one-minute`, a section that does not exist in the file (`grep -n "Use it from Claude Code" README.md` hits only the link). The install today is `claude mcp add ... -- <venv>/bin/python -m oncall_brain.mcp_server` after `make setup db`, which is closer to ten minutes than one. No MCP resources (the service map or an incident board as a resource would be natural). The pick test is one tool per request, so multi-step use (raise_alert then respond_to_alert) is untested from outside.

## Submission checklist
| item | status | where |
|---|---|---|
| Public repo | pending push (fine); README has uncommitted edits (`git status`) | `git log` 58 commits |
| README: setup + data model | present | `README.md` quick start, Mermaid model; `docs/DATA_MODEL.md` (250 lines) |
| Cypher queries | present, generated | `docs/QUERIES.md` from 9 `.cypher` files via `scripts/gen_queries_doc.py` |
| Demo video script | present but stale: says "the planner is rules, not a language model", 184/200, buttons "Act 1" / "Confirm root cause" that no longer exist | `docs/DEMO_SCRIPT.md`; STATUS admits "being rewritten" |
| Deployment / local setup | present, not live; clean-run verified by the cloud helper | `Dockerfile`, `docker-compose.yml`, `render.yaml`, `docs/DEPLOY.md`, `.github/workflows/pages.yml` |
| Tracks named | present | README "Tracks entered" + per-track table |
| AI usage disclosed | present, now **internally wrong**: still 5 `TODO(Harsh)` lines, says 184/200 (EVAL and README say 186), and "the LLM adapters have never been run against a live model" while `docs/LLM_RUN.md` and the fixtures show Opus 5.5 driving 60 decisions | `docs/AI_USAGE.md:27-31,37,51` |
| Docs that teach | present and good | `ARCHITECTURE.md` (508), `WALKTHROUGH.md`, `EVAL.md`, `PERF.md`, `SCORECARD.md`, ADR-001..005, `PRODUCT.md` |
| MCP as deliverable | present | `docs/MCP.md`, `docs/MCP_PICK.md`, `src/oncall_brain/mcp_server/` |
| Secrets | ok | `.env` ignored, `.env.example` shipped |

## Product quality: 8/10
10-second test (screenshot 05): "What broke, why, who's paged, and the fix", one orange CTA, a three-step strip, the demo-company line: a product, not a rig. The simulate menu (06) explains each scenario in one sentence. The answer card (08) is the best screen: cause in plain words with author and "40 min before the alert", a confidence label with its reason, Confirm/Wrong cause, what broke / who's paged / fix, ruled-out with one reason each, titled sources with kind badges. "Seen this before" (10) and "Saved to memory" (09) land the memory story without reading. Phone (04) holds up.
What costs points in the first minute: the **Connect page at 1440 (14) has three overlapping cards** (the MCP card sits on top of the webhook and Slack cards, text collides at "(Apps → Incoming"); this is the page the owner says is the product. The footer chip still leaks test tenant names ("company: after1", "company: shots"). The storm answer (02) still carries the garbled line "subs-88 on subscriptions · pg-conn-3 explains every alerting service this change does (1) and 2 more". Act 2 (10) has no "Wrong cause" button, the one place a disagree button matters most (commit 3c49593 claims a fix; the screenshot does not show it). The live view (07) shows "Likely cause" while cart-310 is still "open", so the answer is declared before the investigation ends.
First minute of a video: with the current DEMO_SCRIPT it would narrate buttons that are not on screen; with the UI as shot, inbox -> simulate -> answer -> confirm -> second incident is a strong 60 seconds.

## What moved since round 1
- Fixed: "nullnull" gone from every screen; ids off the Confirm button; sources titled; "Resolved" -> "Confirmed"; model/rules badge and reason per step; handoffs visible; graph fits the panel; tool names rendered as questions ("Who depends on refunds?").
- Added: `docs/PRODUCT.md` (who, where, two surfaces); MCP instructions, prompts, argument descriptions, HTTP bearer token, `MCP_PICK.md` 14/14; headless webhook `POST /api/tenants/{t}/alerts?respond=true` + Slack post; Claude as default planner with recorded fixtures; tests 169 -> 178; `docs/SCORECARD.md` applied.
- Not moved: no `algo.*`; no constraints/concurrency (patch available, unapplied); no plugin directory; `AI_USAGE.md` TODOs and now a false "never run against a live model" line; `DEMO_SCRIPT.md` stale; Connect page layout bug is new.

## Top 5 changes that would raise the score
1. `git am collab/patches/rival-004-constraints-atomic-reset-concurrency.patch`, run `make test`, commit. Track 02 +1 (constraints, atomic reset, measured p50/p95, 5 tests). ~0.5 h.
2. Ship `plugin/` (plugin.json, .mcp.json pointing at `python -m oncall_brain.mcp_server`, two skills that send the existing `prompt_text()` strings, marketplace.json) and the README "Use it from Claude Code in one minute" section the link already points to, tested from a fresh Claude Code. MCP +2, Track 01 +0.5. ~2 h.
3. Consistency pass: `AI_USAGE.md` (186, the LLM run happened, fill or strike the TODOs), rewrite `DEMO_SCRIPT.md` to UI v2 and the LLM planner, fix the Connect card overlap, hide the tenant chip, fix the "Also possible" sentence, restore "Wrong cause" on act 2, drop the `Rules`/"LLM chose" contradiction on stored steps. Removes a disclosure risk; Product +1. ~1.5 h.
4. Record the video with Claude Code driving the MCP server for the first 30 s (`claude mcp add`, "checkout is slow, why?"), then the inbox for the confirm/memory beat. Product +0.5, Track 01 +0.5, MCP +0.5. ~2 h.
5. One `algo.pageRank` (or WCC) tool over live `DEPENDS_ON` that triage chooses to order who is paged/warned, checked against temporal edges, with a test that the planner picks it. Track 01 +1. ~3 h.

## One-line verdict
Still a yes for Track 01 and a borderline-yes for Track 02 with a now-credible MCP story, but "the MCP server is the product" is not yet true on disk: no plugin, an unapplied concurrency patch, a broken Connect page, and a disclosure doc that contradicts the LLM run are the gaps between 8/10 and the top of the field.


## Hackathon judge, round 3

## Rule 2 check
Unchanged and still true, verified at HEAD `f715317` (05:18 IST, working tree clean). Every tool is a named, parameterised Cypher statement (91 in `docs/QUERIES.md`, generated from `src/oncall_brain/adapters/falkordb/queries/*.cypher`), the planner's only input is the incident board re-read from the graph, and memory, handoffs, the status update, the heads-up and the company brain are nodes and edges. New since round 2: `algo.pageRank` now runs on a point-in-time projection (`algorithms.cypher: topology_at / project_topology / criticality`) and writes `IMPACTS.rank` and `WARNED` edges, and `GRAPH.CONSTRAINT ... UNIQUE` on `id` for every label (`repository.py:77-101`). `source devenv/env.sh && make test`: **189 passed in 29 s** against live FalkorDB. The only graph-less path is the GitHub Pages replay, now labelled "Replay" (`f715317`). **Verdict: indispensable.**

## Track scores

### Track 01: 8.5/10
For: temporal multi-hop and `shortestPath` refutations unchanged; a graph algorithm now decides an action, which was the round-2 gap: PageRank over the dependencies live at alert time orders the blast radius and picks who gets a heads-up (`services/tools.py:_criticality`, `warn_owners`; `tests/integration/test_algorithms.py` proves history edges do not change the order and the scratch graph is dropped). Claude Opus 5.5 calls `warn_owners` in all three acts unprompted (`docs/LLM_RUN.md:27`, fixtures `act{1,2,3}.json` show `"warn_owners","by":"claude-opus-5-5"`). Tool selection via MCP is now real: plugin, 14/14 pick test, every argument described, `readOnlyHint`. The stored-step "Rules / LLM chose" contradiction is gone (screenshot 03: "chosen by the model (older run; its reason was not recorded)").
Against/missing: PageRank runs *inside* `blast_radius`, so the agent never chooses the algorithm; it chooses `warn_owners`, and the LLM system prompt (`adapters/llm/openai_compat.py:SYSTEM`) tells it to in a fixed order: the model follows a playbook that mirrors `domain/planner.py`. One algorithm only; the storm split is still a hop count, not WCC/labelPropagation. Screenshot 07 still declares "Likely cause" while `cart-310` is open.
A 10 would: `criticality` (PageRank) and a `WCC` storm split as separately chosen tools, a trace line showing the pick and its effect, and a prompt that lets the model deviate from the playbook with a case where it did.

### Track 02: 8.5/10
For: episodic/semantic/procedural unchanged and visible ("Seen this before: 3 steps instead of 6", screenshot 10). The concurrency gap closed: rival-004 applied in `85fa11b` (unique constraints, `GRAPH.COPY` + `RENAME` atomic reset, 5 tests in `tests/integration/test_concurrency.py`, measured tables in `docs/PERF.md` "Concurrency": 8 tenants in parallel 8/8 right, 1,236 reads at p50 24 ms while agent runs hold the lock, 600 concurrent writes with 0 duplicates). One graph per tenant; handoffs first-class in the trace (screenshot 12).
Against/missing: per-user memory is still absent (V3 "accepted, backend-first" in `collab/ACK.md:14`, nothing landed; `grep -i "per-user"` only hits the auth caveat). The per-tenant lock still serialises every write (p99 204 ms from polling, `PERF.md`). Three roles remain functions in one process; ownership has no validity.
A 10 would: a per-engineer session/question memory recalled on the next question, per-incident instead of per-tenant locking, and a second process (the MCP server) demonstrably sharing state with the API mid-incident.

### Track 03: 7.5/10
For: docs/tickets/chat in one graph, `ask` with titled source chips and a `superseded` badge (screenshot 13), `who_knows`, `change_story`, `CITES`. New: `record_doc` (`fdef431`, `ac3ddb6`) records a decision/postmortem/runbook page as a live event with `AUTHORED_BY`, `DECIDES`, `MENTIONS`, `SUPERSEDES`, and `test_a_new_decision_record_flips_the_ask_answer_and_flags_the_old_one` shows "keeping knowledge current" as a tested behaviour, which is the first half of what round 2 asked for.
Against/missing: ownership still has no validity, so "who owned X when" has no answer (`grep OWNS.*valid` in queries: empty; `ACK.md:24` leaves it open). The Ask screenshot (13, shot 04:51) still opens scrolled past the answer sentence ("costa) is on call..."); the fix is claimed in `b0a0167` but not re-shot. The decision chain is still a chip list, not a lit path.
A 10 would: `OWNS {valid_from, valid_to}` plus `transfer_ownership`, the why-chain (decision -> source -> author -> superseded-by) rendered as a path, and a fresh Ask screenshot that leads with the answer.

## MCP surface and plugin: 8.5/10
Verified: `plugin/.claude-plugin/plugin.json`, `plugin/.mcp.json` (`${CLAUDE_PLUGIN_ROOT}/bin/oncall-brain-mcp`), a launcher with a clear failure message when no interpreter is found (ran it with a bare env: "no interpreter at .../.venv/bin/python. Run 'make setup'..."; `make setup` on a plain checkout creates exactly that `.venv`), three skills whose SKILL.md bodies are genuinely good operator playbooks (incident: respond, report in order, offer `resolve_incident`; who-owns: `who_knows` -> `ask` -> `page_on_call` with no incident), `.claude-plugin/marketplace.json` at the root, README section "Use it from Claude Code in one minute" now exists (`README.md:167`), `docs/MCP.md:92-112`. `tests/integration/test_plugin.py` validates manifests (and `claude plugin validate --strict` when the CLI exists) and drives the server through the launcher with an MCP client, following the who-owns skill: it passed in this run. Catalogue: 26 tools, 2 prompts, instructions, token on HTTP.
Costs: tool count drifts across docs (README "24 in all", `MCP.md:48` 24 and `:109` 25, `plugin/README.md` 25, live `catalogue()` returns 26: 24 registry incl. `warn_owners` and `record_doc`, plus 2). The Connect page (screenshot 14, shot 05:02) still shows `claude mcp add` and never mentions the plugin (`grep -i plugin web/`: nothing), so the product's own window does not advertise its primary install path. `docs/PRODUCT.md` still says "Plugin: in progress". No MCP resources. The marketplace install path depends on a public repo that does not exist yet.

## Submission checklist
| item | status | where |
|---|---|---|
| Public repo | pending push; tree clean, 68 commits | `git log`, `git status` |
| README: setup + data model | present | `README.md:109` Mermaid model, `:152` quick start; `docs/DATA_MODEL.md` (259 lines, now with `IMPACTS.rank/score`, `WARNED`, `SUPERSEDES`) |
| Cypher queries | present, generated, 91 statements | `docs/QUERIES.md` via `scripts/gen_queries_doc.py` |
| Demo video script | present and current (UI v2, Claude badges, plugin skill at 1:55) | `docs/DEMO_SCRIPT.md`; line 6 preamble still says `claude mcp add` while row 22 uses `--plugin-dir` |
| Deployment / local setup | present, not live | `Dockerfile`, `docker-compose.yml`, `render.yaml`, `docs/DEPLOY.md` |
| Tracks named | present | `README.md:16`, `:216` per-track table |
| AI usage disclosed | present, now consistent (186, live-LLM line removed, product-phase section added); 5 `TODO(Harsh)` lines remain for Harsh | `docs/AI_USAGE.md:27-31` |
| Docs that teach | present and strong | `ARCHITECTURE.md` (546), `WALKTHROUGH.md`, `EVAL.md`, `PERF.md`, `SCORECARD.md`, ADR-001..006 |
| MCP as deliverable | present, plus plugin | `docs/MCP.md`, `docs/MCP_PICK.md`, `plugin/`, `src/oncall_brain/mcp_server/` |
| Secrets | ok | `.env` ignored, `.env.example` |

## Product quality: 8.5/10
10-second test still passes (screenshot 05). The Connect page overlap is fixed (14). Stored steps no longer contradict themselves (03). Phone layout holds (15). The answer card (08/09) remains the best screen; "Saved to memory" and "Seen this before" land without reading.
What costs points: 9 of the 12 screenshots (02, 05-13) were shot 04:40-04:51, *before* the round-2 fix commit `b0a0167` and the PageRank step, so they still show the garbled "Also possible: ... explains every alerting service this change does (1) and 2 more" (02; the plain-words rewrite is in `web/app.js:483-485`), test tenant chips "company: after1 / shots" (`companyLabel()` only relabels the default tenant), no "Wrong cause" on act 2 (10, shot one minute before `3c49593`), no heads-up in "Who's paged", and the scrolled Ask answer (13). I cannot confirm from images that those fixes work; the images in `docs/screenshots/after/` currently under-sell the code. Screenshot 07 still shows "Likely cause" with a suspect open. Code blocks on Connect are horizontally clipped with the Copy button over the text.

## What moved since round 2 (per top-5 item)
1. **Apply rival-004 (concurrency).** Done: `85fa11b`; `repository.py` constraints + atomic reset, `test_concurrency.py` 5 tests green, `PERF.md` Concurrency section with p50/p95/p99 tables, `ACK.md:21-22` closes V2/V7. Fully moved.
2. **Ship `plugin/` + README section.** Done: `323e6c9`, `28005a2`, `b5b8357`; manifests, launcher, 3 skills, marketplace, `README.md:167`, `MCP.md:92`, `test_plugin.py` (2 tests, pass). Residual: Connect page and `PRODUCT.md` not updated, tool-count drift.
3. **Consistency pass.** Mostly moved: `AI_USAGE.md` consistent (186, false "never run" line gone); `DEMO_SCRIPT.md` rewritten to UI v2 + Claude + plugin; Connect overlap fixed; Rules/"LLM chose" contradiction fixed; "Also possible" rewrite, Ask scroll, act-2 Wrong cause claimed in `b0a0167`/`3c49593` but the screenshots that would prove them predate the commits. Tenant chip still leaks for non-default tenants.
4. **Video with Claude Code first.** Not moved as suggested: the script puts the plugin segment at 1:55-2:10, not the opening 30 s. Defensible choice, but the "MCP is the product" claim is made in the last 15 seconds.
5. **One `algo.*` the planner chooses.** Moved: rival-005 in `7a00fb8`; PageRank on the point-in-time projection, `warn_owners` action, `WARNED` edges, two integration tests, Claude picks it 3/3 acts. Half credit on "chooses": the algorithm is inside `blast_radius`, and the chosen step is in the prompt's playbook.

## Top 5 changes that would raise the score now
1. **Re-shoot the 9 stale screenshots on the default tenant and fix doc drift** (tool count 26 everywhere, `PRODUCT.md` plugin "shipped", Connect page gets `claude --plugin-dir ./plugin` and the three skills, DEMO_SCRIPT line 6). Product +0.5, MCP +0.5. ~1 h. (best score/hour)
2. **Harsh fills the 5 `TODO(Harsh)` lines after running `make setup db seed demo test` on a clean checkout and the plugin from a fresh `claude`.** No score points, but it removes the "entirely AI-generated" rejection risk, which outweighs every row above. ~1.5 h.
3. **Make the algorithm a chosen step:** expose `criticality` as its own tool (blast_radius stops calling it), and add `algo.WCC` over the alert-time projection in `correlate_alerts` to split a storm into components, with a trace line and a test that the planner picks each. Track 01 +0.5-1. ~3 h.
4. **Ownership validity:** `OWNS {valid_from, valid_to}`, `transfer_ownership` event tool, `who_knows`/`page_on_call` at `$at`, one test where "who owned X at T1" differs from today. Track 03 +0.5. ~2 h.
5. **Per-engineer memory:** `asked_by` on Ask/MCP questions as `(Person)-[:ASKED]->(Question)` nodes, recalled on the next question ("you asked about kafka on Oct 16"). Track 02 +0.5. ~2 h.

## One-line verdict
A yes for Track 01 and a yes for Track 02 now that the concurrency and algorithm gaps are closed with tests and numbers, and "the MCP server is the product" is finally true on disk with a validated plugin; what remains between this and the top of the field is a fresh set of screenshots that match the code, an algorithm the agent visibly chooses rather than inherits, and Harsh's own verification lines in `AI_USAGE.md`.
