# Reviews of the before screenshots

## Accessibility pass (WCAG 2.1 AA, subagent)

WCAG 2.1 AA pass: On-call Brain web UI (`/media/harsh/MyPassport1/wemakedevs/graphhacks/web/{index.html,style.css,app.js}`)

Contrast ratios computed from the literal hex pairs in style.css (WCAG relative-luminance formula). Baseline pairs all pass: body `#e3e9f3` on `#0b1020` 15.5:1, on panel `#111a2c` 14.3:1; muted `#93a1b8` on `#0b1020` 7.24:1, on `#111a2c` 6.65:1, on `#16213a` 6.12:1, on inbox bg `#0d1526` 6.97:1, on Slack card `#1a1d21` 6.47:1; accent `#7dd3fc` on bg 11.4:1; role pills (`#0b1020` on triage 8.8, investigator 12.4, comms 7.2, human 9.0); status pills 10.5–12.7; `.pill.memory` 7.0, `.pill.rb` 8.1, `.pill.alert` 6.6, `.pill.out` 7.1, `.pill.kind` 8.6; `.rw.ro` 8.0, `.rw.w` 8.2; `.verdict.supports` 6.6; `.tag` 5.9; `.src` 13.1; `.confirm` white on `#15803d` 5.0; `.app` `#9a9b9e` on `#2c2f33` 4.84 (10.5px, passes narrowly). Findings below are what fails or is missing.

1. **major** — "null" / "nullnull" text rendered in the progress area (screens 02, 03, 05, 06, 07 at 1440). Screen readers announce "null null" inside the `aria-live` region on every step. Source now has `.filter(Boolean)` in `renderProgress` (app.js:253), so this may be fixed since the capture; verify in the current build and, if still present, keep `.filter(Boolean)` and also guard `h()` so `null` kids are never stringified.

2. **major** — Mobile layout overlap (screens 13, 14 at 390): the incident header (status pill "Cause found", h2) renders on top of the "3 alerts at once" scenario card, and the inbox list (3 incidents) is not visible at all. Cause: `.inbox-panel { max-height: 45vh }` under 900px with no `overflow`, so `.story` overflows and the next grid row paints over it. Fix in the `@media (max-width: 900px)` block: `.inbox-panel { max-height: 45vh; overflow-y: auto; }` and `.inbox { flex: 1 0 auto; max-height: none; }` so the list keeps its height (or drop `max-height` and let the page scroll, since `body { overflow: auto }` already applies there).

3. **major** — Legend text cut off (screens 04, 08 at 1440; 16 at 390): `.legend` is `overflow: hidden; white-space: nowrap`, so "retired dependency", "root-cause path", "memory link" are clipped ("--- ret"). At 390 only the first four items survive. Fix: `.legend { height: auto; min-height: 34px; flex-wrap: wrap; white-space: normal; overflow: visible; row-gap: 2px; }` and change `#graph { inset: 40px 0 34px }` to use a CSS var or `bottom: auto` with the legend placed in flow (e.g. make `.graph-wrap` a `display:grid; grid-template-rows: 40px 1fr auto`).

4. **major** — HUD text cut off (screens 13, 16 at 390): `.hud` is `overflow: hidden; white-space: nowrap`: "20 Oct, 09:" and "callers left, depen" are clipped, i.e. the alert time and the graph caption are lost on phones (1.4.10 reflow). Fix: `.hud { flex-wrap: wrap; white-space: normal; height: auto; min-height: 40px; overflow: visible; }` with the same grid-row change as item 3.

5. **major** — Landing CTA `.cta` (screen 01, 17): white 16px bold on gradient `#f97316 → #ef4444`. Measured 2.80:1 at the orange end, 3.24:1 mid, 3.76:1 at the red end; 16px bold is not "large text" (needs 18.67px bold or 24px), so 4.5:1 applies. Fail. Fix: `background: linear-gradient(135deg, #c2410c, #b91c1c)` (white on `#c2410c` ≈ 5.0:1, on `#b91c1c` ≈ 6.3:1), or keep the gradient and set `font-size: 19px` (then 3:1 large-text threshold still fails at the orange end, so darken anyway).

6. **major** — `.verdict.refutes, .verdict.inconclusive`: `#7c8799` on `#2a3345`, 12px bold = **3.49:1**. Fail (trace cards, screens 04, 08). Fix: `color: #b9c3d3` (7.1:1, same as `.pill.out`).

7. **major** — Opacity-dimmed informative text. `.tile.waiting { opacity: .55 }` makes the muted job description (`#93a1b8` → effective `#596479`) **2.92:1** on `#111a2c` (screen 02 "Writes the update, with sources"). `.scenario.done { opacity: .6 }` makes the muted note **3.23:1** (screens 02–08). These are text, not disabled controls, so no exemption. Fix: replace opacity with colours: `.tile.waiting { opacity: 1; border-style: dashed; } .tile.waiting p { color: var(--muted); }` and `.scenario.done { opacity: 1; } .scenario.done b { color: var(--muted); }`. Keep the `Fired` button disabled (disabled controls are exempt).

8. **major** — Non-text contrast of control boundaries (1.4.11): `.ghost` buttons (Fire, Reset demo, Skip animation, Wrong cause?, This one) and the chat `<input>` are identified only by a `#24314b` border: **1.46:1** on `#0b1020`, **1.34:1** on `#111a2c`, **1.23:1** on `#16213a`. Fail. Fix: `.ghost, .chat-input input, .chip-btn { border-color: #4b5a78; }` (≈3.2:1 on bg, 3.0:1 on panel) or give `.ghost` a filled background `var(--panel-2)` plus the brighter border.

9. **major** — Focus visibility (2.4.7): no `:focus-visible` rule anywhere; `.chat-input input:focus { outline: none }` removes the ring and leaves only a 1px border change; `.trace .card:focus-visible { outline: none }` leaves only a 1px border colour change (`#7dd3fc` vs `#24314b`). Buttons fall back to the UA ring, which is fine in Chromium but inconsistent and lost behind `overflow: hidden` containers (seg tabs, chip pills). Fix, one rule: `:is(button, a, input, summary, [tabindex]):focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }` and delete both `outline: none` declarations. `#7dd3fc` is 10.4:1 on panel, 11.4:1 on bg.

10. **major** — Live region chatter (4.1.3): `#progress[aria-live=polite]` is fully rebuilt with `replaceChildren` every step (≥750 ms), so screen readers re-announce all three tiles, the planner line and the Skip button each time; `#chat-log[aria-live=polite]` re-announces the whole chat history on each render. Fix: remove `aria-live` from `#progress` and `#chat-log`; add a visually-hidden `<p id="sr-status" aria-live="polite" aria-atomic="true">` and set its `textContent` once per step to `${last.role}: ${last.reason}` (and once per answer in `askQ`). Add the `.sr-only` utility (`position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap`).

11. **major** — Graph canvas has no accessible name or role: `#graph` is a `<div aria-label="Service dependency graph">`; `aria-label` on a generic div is not exposed, and the canvas content is not reachable by keyboard or AT (screens 04, 08, 09, 10, 16). The trace panel and "Linked in the graph" chips are the text equivalent. Fix: `<div id="graph" role="img" aria-label="Service dependency graph; the agent steps panel lists what is highlighted">` and give the Cytoscape canvas `tabindex="-1"`. Also set `.hud` as `aria-live="polite"` is not needed; leave it static.

12. **minor** — Tabs pattern incomplete (ARIA): `role="tab"` buttons lack `aria-controls`, tabpanels lack `tabindex="0"`, and there is no arrow-key handling; `.views` buttons use `aria-current="page"` (allowed, but they behave as tabs). Fix: add `aria-controls="answer-view"` / `"why-view"`, `tabindex="0"` on both `role="tabpanel"` divs, inactive tab `tabindex="-1"`, and a 6-line keydown on `.seg` that moves focus/selection on ArrowLeft/ArrowRight. Same for `.views` if you convert it to `role="tablist"`; otherwise leave it as a `<nav>` (current markup is acceptable).

13. **minor** — Keyboard reachability: handoff rows (`li.handoff`, cursor:pointer, `data-i`) are clickable to repaint the graph but have no `tabindex`, so keyboard users cannot trigger them; trace cards respond to Enter but not Space. Everything else (view tabs, Answer/Show me why, Fire, CTA, Confirm, Wrong cause?, This one, inbox items, Skip animation, Reset demo, Ask, example chips, Connect Slack link) is a native `<button>`/`<a>`/`<input>` and is reachable. Fix: add `tabindex: 0` and `role: 'button'` to the handoff `li` in `stepCard`, and in the keydown handler use `if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onTraceClick(e); }`.

14. **minor** — Toast: `role="status"` is right for success; error toasts (10 s, `isError`) should be `role="alert"` so they interrupt. Fix in `toast()`: `el.setAttribute('role', isError ? 'alert' : 'status')`. Also the toast overlaps the Confirm row on screen 07 (bottom-centre, 1440); add `padding-bottom: 72px` to `.answer-view` or move the toast to `top: 72px`.

15. **minor** — Reduced motion: `prefers-reduced-motion` covers `.trace li`, `.dot.working`, `.skel`, `.spinner` only. Not covered: Cytoscape `cy.animate` fit (450 ms/300 ms) and node/edge `transition-duration: 300` in graph.js, `scrollIntoView({behavior:'smooth'})` in `appendTrace`, `.tile.working` glow is static (fine). Fix: `const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;` once in graph.js and app.js; pass `duration: RM ? 0 : 450`, `'transition-duration': RM ? 0 : 300`, and `behavior: RM || state.skip ? 'auto' : 'smooth'`. Also add `@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }` to cover `@keyframes pulse/shimmer/spin/in` in one line.

16. **minor** — Touch target sizes at 390 (measured from CSS: 12.5px line ≈ 18px + padding + border). `.ghost` Fire / Reset demo / Skip / This one ≈ 28px tall; `.seg button` ≈ 30px; `.view-tab` ≈ 32px; `.primary-btn` ≈ 30px; `.chip-btn` ≈ 31px; `.confirm` ≈ 34px; `summary` disclosures ("Cypher: 4 queries…", "rows (n)") ≈ 18px. WCAG 2.1 AA has no target-size criterion (2.5.5 is AAA, 24px minimum is 2.2 AA); against the 24×24 minimum only the `summary` rows fail, against 44×44 everything but the CTA fails. Fix: `.ghost, .primary-btn, .seg button, .view-tab, .chip-btn, .confirm { min-height: 36px; }`, `summary { min-height: 24px; display: flex; align-items: center; }`, and under 900px `min-height: 44px` for `.ghost.primary-btn` in `.scenario` and the Confirm/Wrong-cause row.

17. **minor** — Truncated inbox titles ("checkout p99 latency a…", screens 03–08) have no full-text affordance for sighted users; AT reads the full text. Fix: in `renderInbox` add `title: trigger.name` to the `.inbox-item` button, or let `.ii-title { white-space: normal }` wrap (two lines fit in the 320px column).

18. **minor** — 390px reflow of the Ask view (screen 16): the chat log is squeezed to ~90px (`.ask-graph { min-height: 60vh }`) so the answer is unreadable without scrolling inside a tiny box, and graph node labels render at ~4px. Fix: under 900px `.chat-log { min-height: 40vh }`, `.ask-view { grid-template-rows: auto auto; }`, and `min-height: 60vh → 45vh` on `.ask-graph`; in graph.js set `cy.minZoom(0.6)` on narrow viewports so labels never drop below ~10px.

19. **minor** — Dimmed graph labels (`.dim { opacity: 0.12 }`, `.ctx { opacity: 0.5 }`): unfocused node labels such as "notifications" (screen 04) are well under 3:1. Canvas art with a text alternative (trace panel), so informative-image rules apply rather than text contrast; acceptable, but raise `.dim` to `0.25` so the layout remains perceivable for low-vision users.

20. **minor** — Status conveyed by colour alone in the legend swatches `.lg.*` and `.dot` is mitigated by text labels next to each; no action. The `<s>` strikethrough for refuted changes (`#7c8799` on `#111a2c` = 4.79:1) passes.

**Do these five first**
1. Fix the 390px inbox/story overflow so the incident header no longer overlaps the scenario cards and the inbox list is visible (`.inbox-panel { overflow-y: auto }`, item 2).
2. Add one global `:focus-visible` rule and remove both `outline: none` declarations (item 9).
3. Fix the real text-contrast failures: `.cta` gradient (2.80:1), `.verdict.refutes` (3.49:1), `.tile.waiting`/`.scenario.done` opacity (2.92/3.23:1) (items 5–7).
4. Replace the two chatty `aria-live` regions with a single `.sr-only` status line updated once per step/answer, and switch error toasts to `role="alert"` (items 10, 14).
5. Let `.legend` and `.hud` wrap instead of clipping, and raise `.ghost`/input border contrast to ≥3:1 (items 3, 4, 8).

## Hackathon judge, round 1 (subagent, before the product work)

## Rule 2 check
The graph does the work. Every agent decision is made from a board rebuilt out of FalkorDB before each step (`src/oncall_brain/agents/loop.py` -> `services/board.py` -> `queries/board.cypher`), and the 82 named, parameterised queries in `src/oncall_brain/adapters/falkordb/queries/*.cypher` (generated into `docs/QUERIES.md`, 1,686 lines) carry the logic: `path_suspects`, `live_paths`, `recall_similar` and `memory_suspects` in `investigate.cypher` use `DEPENDS_ON*0..6` with `valid_from`/`valid_to` filtering and `shortestPath` in `WITH`; `correlate_alerts` intersects upstream closures; memory is `RECALLS -> FIXED_WITH -> Runbook -> FOR_SERVICE`; `ask` uses three FalkorDB full-text indexes plus `MENTIONS`/`DECIDES`/`SUPERSEDES` expansion (`knowledge.cypher` lines 117-132, `services/brain.py:299`). The UI calls `/api/tenants/{t}/...` for every action (`web/app.js:63`); `make test` ran 169 tests green against a live FalkorDB (unit + integration, including `test_tenants_are_isolated`, `test_concurrent_responders_do_not_duplicate_work_or_edges`, `test_mcp_exposes_every_registry_tool_and_runs_them_on_a_tenant`). The README's baseline table (flat log 0/200, anomaly log 134/200, graph agent 186/200) is the right kind of ablation. Two honest caveats: no `algo.*` procedure is used anywhere (`grep algo\.` in `src/` is empty; the README explains dropping `betweenness`), and the GitHub Pages "replay" works with no database, but it is labelled recorded fixtures and not the product. **Verdict: indispensable.**

## Track scores

### Track 01: 8/10
For: multi-hop temporal traversals are the core (`investigate.cypher`); the trace shows each step's Cypher, rows and ms, and the UI highlights the evidence path (screenshot 04); actions are written back (`Incident`, `IMPACTS`, `PAGED`, `Hypothesis`, `Evidence`, `Message CITES`); MCP exposes all 24 tools from one registry (`mcp_server/__init__.py`, `tests/integration/test_mcp.py`); a real LLM run exists with 60/60 model-chosen decisions (`docs/llm_runs/claude-opus-5-5.json`, verified: 60 `"by": "model"`, 0 `"by": "rules"`).
Against: the default planner is a hand-written decision tree (`domain/planner.py`, 102 lines) that branches on board state; the LLM path works only after the prompt was rewritten to "state the same rules the deterministic planner follows" (`docs/LLM_RUN.md`), so tool selection is largely scripted either way. No graph algorithm (PageRank/WCC/community) is offered as a tool, which the track names explicitly. `DEMO_SCRIPT.md` tells the presenter "the planner is rules, not a language model" while every screenshot shows `planner: claude-opus-5-5`.
A 10 would: let the model choose among tools including at least one `algo.*` procedure, with the trace showing a decision the rules would not have made.

### Track 02: 8/10
For: all three memory kinds are real graph structure (`Incident`+`CAUSED_BY`+`AgentStep`; `valid_from`/`valid_to` and `SUPERSEDES`; `Runbook` with `uses`/`successes`), persisted across runs (act 2 recalls act 1, screenshot 06, `?compare=memory` ablation 6->3 calls computed on a pristine clone in `respond.without_memory`); handoffs are `AgentStep` nodes visible in the UI; one graph per tenant with `GRAPH.COPY` resets.
Against: "high-concurrency" is the opposite of what is built: a per-tenant Redis lock serialises every run (`repository.py:35-42`, documented honestly because concurrent `MERGE` produced duplicates); the three "agents" are three role functions executed sequentially by one process, not independent agents coordinating. Per-user memory is per-tenant only.
A 10 would: concurrent runs on one tenant (per-incident locks + unique constraints), and two genuinely separate processes handing off through the graph.

### Track 03: 7/10
For: docs, tickets and chat live in the same graph as services and incidents (`datagen.py:_corpus`; 34/41/21 per README); `who_knows`, `change_story` and `ask` return sources and linked entities (screenshot 10 shows a design note, chat, status update, postmortem, ticket, and 16 linked graph entities); superseded docs are demoted; `tests/integration/test_brain.py` has 10 tests.
Against: the corpus is tiny and synthetic; `ask` is a keyword-term + intent-route assembler (`brain.py`), so it answers the demo questions well but a free-form question outside the planted story is unverified; the `ask` UI empty state (screenshot 09) gives example questions only.
A 10 would: a larger or public corpus, and an answer that shows the trace of "decision -> source -> who decided -> still current?" as a path, the way incidents do.

## Submission checklist
| item | status | where |
|---|---|---|
| Public repo | pending push (fine) | `git log` 25+ commits, not pushed |
| README setup + data model | present | `README.md` quick start, Mermaid model, `docs/DATA_MODEL.md` |
| Cypher queries | present | `docs/QUERIES.md` generated from 9 `.cypher` files by `scripts/gen_queries_doc.py` |
| Demo video / script | script present, video missing; script inconsistent | `docs/DEMO_SCRIPT.md` (says rules planner, 184/200; UI and README say Claude planner, 186/200) |
| Deployment / local setup | present, not live | `Dockerfile`, `docker-compose.yml`, `render.yaml`, `docs/DEPLOY.md`, `.github/workflows/pages.yml`; `make test` 169 passed |
| Tracks named | present | README "Tracks entered" and per-track table |
| AI usage disclosed | present but weak | `docs/AI_USAGE.md`: honest, but five `TODO(Harsh)` lines unfilled; states every commit was AI-made |
| Docs that teach / defensible | present | `docs/ARCHITECTURE.md` (508 lines), `WALKTHROUGH.md`, ADR-001..004, `EVAL.md`, `PERF.md` |
| Secrets | ok | `.env` is git-ignored (`git check-ignore .env`), `.env.example` shipped |

## Product quality: 7/10
The 10-second test passes: "Your AI on-call teammate", a three-step explanation, one orange CTA (screenshot 01). The answer card reads like a Slack post with a Confirm button, and "Show me why" (04) with the lit path plus per-step Cypher is the best screen. What a judge sees in the first minute that costs points: the literal string **"nullnull"** rendered under the role cards in screenshots 03, 06 and 07 (`web/app.js` ~line 451, `state.caption`); a `company: shots` chip in the header that means nothing to a visitor; the 390px landing (17) puts demo alerts above the hero so the product pitch is below the fold; the Connect tab is a developer page. It is a product rather than a rig, but the bug is on the money screen.

## Top 5 changes that would raise the score
1. Fix "nullnull" and rename the `company:` chip to something meaningful (or hide it); product +1. ~0.5 h.
2. Reconcile `DEMO_SCRIPT.md` with the UI and README (planner badge, 186 vs 184) and fill the `TODO(Harsh)` lines in `AI_USAGE.md`; submission risk removed (the rules reject work with no participant contribution shown). ~1 h.
3. Add one `algo.*` procedure as an agent-choosable tool (e.g. `algo.WCC` or `pageRank` on the live-at-alert subgraph to rank blast radius or the storm's shared upstream), with a test showing the planner picks it; Track 01 +1. ~3 h.
4. Replace the per-tenant global lock with per-incident locking plus `db.constraints` unique ids, and a test where two alerts on one tenant run in parallel; Track 02 +1. ~3 h.
5. Record the demo video with the LLM planner on and the "LLM chose" badge visible, and show one decision the rules would have made differently; Track 01 +0.5, Product +0.5. ~2 h.

## One-line verdict
Yes for Track 01 and borderline-yes for Track 02: the temporal multi-hop reasoning, ablations against non-graph baselines, honest eval and explainable traces are stronger than most graph-agent demos, held back only by a rule-based default planner, no graph algorithms, serialised concurrency, and a visible rendering bug on the main screen.

## UX critic (first-time on-call engineer, subagent)

### Landing / empty inbox, 1440 (01-landing-1440.png)
**Score: 7/10**
**10-second test:** A dark incident-tool shell ("Incidents / Ask the brain / Connect") with a hero that says "Your AI on-call teammate" and one big orange button "Fire the first alert: checkout is slow". I believe it is an AI incident-triage tool, for on-call engineers, and I would click the orange button. That matches the intended purpose.
**Blockers:** none.
**Major:**
- M1 Header right, chips "planner: claude-opus-5-5" and "company: shots". "planner" is your internal word; "shots" is unexplained. Say "Model: Claude Opus" and "Company: Shots (demo)" or move both to Connect.
- M2 Left sidebar: ~330px of dead space between "No incidents." (y≈130) and "DEMO ALERTS" (y≈548). On an empty inbox put the demo alerts directly under the empty state, or put the empty-state CTA there.
- M3 Copy "decoy" appears twice (step 2 card: "rules out the decoys"; demo card 1: "Watch each decoy get ruled out"). "Decoy" is demo-rig language that tells me the data was planted. Say "rules out the other recent changes".
**Minor:**
- m1 Two ways to fire the same alert (sidebar card 1 "Fire" and the hero CTA). Fine, but make the sidebar card show "same as the button on the right" or drop the highlight ring on card 1.
- m2 Footer line "Ask the company brain · Use it from Claude Code or your alerting" is two links jammed into a sentence with a middot; make them two buttons.
- m3 Eyebrow "INCIDENT RESPONSE ON A KNOWLEDGE GRAPH · FALKORDB" is marketing; harmless.
**What works:** The three-step strip (alert fires / agents investigate / you confirm, it learns) is the clearest explanation of the product anywhere in the app. The single orange CTA is correct.

### Incident while the agents work, act 1 (02-act1-working-1440.png)
**Score: 5/10**
**10-second test:** An incident page with three agent cards (Triage done, Investigator working, Comms waiting), a Slack-style preview that is still loading, and a status line. I believe agents are investigating a latency alert. Matches. Then I see the word "null" and stop trusting it.
**Blockers:**
- B1 Literal text "null" rendered at (338, 300), directly under the investigator status line. That is an unrendered template value. A judge sees a broken product; an engineer assumes the rest is also untested. Remove the element when the value is empty.
**Major:**
- M1 Investigator card: "Now: REFUTES chg:pricing-2140: change was rolled back before the alert fired". "REFUTES" in caps and the "chg:" id are internal. Say "Ruled out: pricing change #2140, it was rolled back before the alert".
- M2 Status line "investigator: Two hypotheses are still open, so I'm checking both. · steps chosen by claude-opus-5-5". "hypotheses" -> "suspects" (you already use "suspects" in the card above). "steps chosen by claude-opus-5-5" is a model id; say "Claude is choosing the next step" or nothing.
- M3 Triage card: "for svc:checkout". Drop the "svc:" prefix everywhere the human reads it.
- M4 Everything below y≈480 is empty while the agents run (half the screen). Stream the agent steps here (the ones that exist on "Show me why") instead of a skeleton loader on a fake Slack message.
**Minor:**
- m1 "Skip animation" (top right of the status line) admits the stream is replayed. Call it "Jump to result".
- m2 Slack preview "The comms agent posts here once the cause is clear…" is good copy; the two grey skeleton bars under it are fine.
**What works:** The three agent cards with done / working / waiting states and the yellow outline on the active one read instantly.

### Incident answer after the agents finish (03-act1-answer-1440.png)
**Score: 5/10**
**10-second test:** A Slack-style status update with Impact, Likely cause, Ruled out, Paged, Sources, and a green Confirm button. I believe the AI found the cause and wants me to confirm. Matches, and the update itself is close to what I would write by hand.
**Blockers:**
- B1 Literal "nullnull" at (338, 244), the same broken line as screen 02, now doubled. Same fix.
- B2 Green button "Confirm: pgw-pool-1 caused it" (355, 709). "pgw-pool-1" appears nowhere in the update above it. The cause is described as "config change on payments-gw by Sana Brandt". I cannot confirm an id I have never seen. Say "Confirm: the payments-gw pool change caused it".
**Major:**
- M1 "Sources: msg:pay-deploys-1 ticket:CR-881 doc:cost-review-pgw" are ids in code chips. Show titles ("#payments-deploys message, 14 Oct", "CR-881 Reduce idle connections on payments-gw") and make them obviously clickable.
- M2 Right panel "WITHOUT THE GRAPH": "Newest change search-420 WRONG / Change log + anomalies legacy-193 WRONG". This is a benchmark against two straw-man heuristics, written in ids. An on-call engineer does not care; a judge reads it as self-congratulation. Either explain in one sentence what the two rows are ("if you just blamed the newest change: search-420, wrong") or move it to "Show me why".
- M3 "WHY THIS CHANGE" panel: chips read "checkout → payments → payments-gw" but the sentence under it reads "anomaly propagates payments-gw -> payments -> checkout". Opposite direction, two arrow styles. Pick one direction (cause on the left) and the unicode arrow.
- M4 "Paged: @asha.nakamura (Payments), @ravi.moreau (Checkout)" in the update, but the Triage card at the top says only "Paged Ravi Moreau". Two different facts on one screen.
**Minor:**
- m1 Sidebar incident title truncated: "checkout p99 latency a…". Give it two lines.
- m2 "Shown here only. Connect Slack to post it to a real channel." is good.
- m3 Header meta "inc:checkout-latency" id; drop the prefix or hide it.
**What works:** The update body (Impact / Likely cause / Context / Ruled out with one reason each / Also at risk / Ask: who knows it best) is the right shape for a 3 AM message; "Ruled out ... (rolled back)" reasons are exactly what I want.

### "Show me why", act 1 (04-act1-why-1440.png)
**Score: 6/10**
**10-second test:** A dependency graph with an orange path checkout → payments → payments-gw, people and changes hanging off it, and a numbered list of agent steps on the right with "Cypher" rows. I believe this is the evidence view. Matches.
**Blockers:** none.
**Major:**
- M1 Graph labels clipped by the right edge of the graph panel at x≈1005: "Payments te", "Asha N", "Lena C", and a lone "C" at (1003, 443). Fit the graph to the panel with padding.
- M2 Legend at the bottom (y≈883) is cut off: "- - - ret" then nothing. Let it wrap.
- M3 Overlapping labels: "checkout-latency" and "0911" over each other at (320–420, 595–645); the "pgw-pool-1" diamond sits on the payments-gw node's border at (870, 560); "Sana Brandt" label crosses an edge. Increase node spacing or use a layout that reserves label space.
- M4 Agent steps numbering jumps #3 → handoff → #5. Where is #4? Either number the handoff row or renumber.
- M5 Step copy is developer-facing: tool names in snake_case ("open_incident", "blast_radius", "recall_similar", "hypothesize_from_memory"), "WHY LLM chose blast_radius", and "Cypher: 4 queries, 5 rows, 13.1 ms". Render tool names as verbs ("Opened incident", "Computed blast radius", "Recalled similar incidents"), say "Why this step" instead of "WHY LLM chose", and label the expander "Graph queries (4), 13 ms".
**Minor:**
- m1 Dimmed nodes ("notifications" at (652, 190), "reporting", "analytics") are nearly invisible; if they are not relevant hide them, if they are, raise contrast.
- m2 Step #6 text "Two of the recalled incidents score 3 (inc:1000 and" is internal scoring with an id.
- m3 "ALERT" header over the graph duplicates the incident title above it.
**What works:** The orange highlighted path plus the diamond for the suspect change is the one picture that explains the product; the handoff row between TRIAGE and INVESTIGATOR is a real differentiator.

### After the human confirms (05-act1-confirmed-1440.png)
**Score: 5/10**
**10-second test:** Same page, status pill now "Resolved", update says "resolved, cause confirmed", a green "SAVED TO MEMORY" box lists a 4-step runbook. I believe I confirmed and it saved. Matches.
**Blockers:**
- B1 "nullnull" at (338, 244) again.
**Major:**
- M1 Status flips to "Resolved" (pill at (340, 97), sidebar badge, update headline) the moment I confirm the cause. Confirming a cause is not resolving an incident; nobody has reverted anything yet. incident.io/FireHydrant would call this "Identified". Use "Cause confirmed" and leave "Resolved" for a separate action.
- M2 SAVED TO MEMORY step 3: "Last time the culprit was: Lower payments-gw HTTP pool max_connections 200 -> 20 (cost cleanup)". This is the first time; "last time" is written from the future. Say "This time the culprit was…" or "Known culprit:".
- M3 "Next action: Revert the config change on payments-gw (this runbook worked 1 of 1 times)". "1 of 1 times" is the same confirmation I just made, presented as track record. Say "confirmed once (this incident)".
**Minor:**
- m1 "Also at risk: refunds, subscriptions" still shown on a "resolved" update.
- m2 Sources chips reordered versus screen 03 (doc first now). Keep order stable.
- m3 Right-hand panels are identical to screen 03; the MEMORY panel could now say "Saved: Revert the config change on payments-gw" instead of repeating what did not apply.
**What works:** The green SAVED TO MEMORY block with a concrete 4-step runbook is the payoff of the whole flow and reads well.

### Act 2 answer, the memory moment (06-act2-answer-1440.png)
**Score: 5/10**
**10-second test:** A second incident (refunds), one suspect tested, "SOLVED BY MEMORY" with "6 → 3 investigator steps, 4 → 1 suspects tested". I believe the system reused last time's fix. Matches; this is the best demo moment in the app.
**Blockers:**
- B1 "nullnull" at (338, 244) again.
**Major:**
- M1 The "Wrong cause?" button is missing. Screen 03 and 07 have "Confirm" + "Wrong cause?"; here only "Confirm: pgw-pool-2 caused it" (355, 688). The one time the system is most confident is exactly when I need the disagree button.
- M2 "WITHOUT THE GRAPH" panel: "Change log + anomalies: pgw-pool-1 SAME ANSWER" while the Confirm button says "pgw-pool-2". pgw-pool-1 was last incident's change. Either it is a different change (then it is not the same answer) or the ids are wrong.
- M3 Same id problem on the Confirm button ("pgw-pool-2").
- M4 MEMORY panel: "Same incident, replayed on the graph without this memory: 6 → 3 / 4 → 1". Good numbers, confusing sentence. Say "Without last week's memory this took 6 investigator steps and 4 suspects. With it: 3 steps, 1 suspect."
**Minor:**
- m1 "Sources: ticket:CR-902" is one id chip; title it.
- m2 "Tested 1 suspect, ruled out 0." reads odd; "1 suspect, confirmed by memory" is clearer.
- m3 Header meta "inc:refunds-latency" id.
**What works:** "SOLVED BY MEMORY" badge and the before/after pair are instantly legible and are the one thing a judge will remember.

### Act 3 answer, alert storm (07-act3-answer-1440.png)
**Score: 5/10**
**10-second test:** Incident titled "3 alerts: checkout, refunds, subscriptions", an "ALERT STORM 3 alerts → 1 incident" panel, cause on postgres-orders. I believe three alerts were correlated to one cause. Matches.
**Blockers:**
- B1 "nullnull" at (338, 244) again.
**Major:**
- M1 The Slack update headline says "subscriptions p99 latency above 2s — cause identified" while the page title says "3 alerts: checkout, refunds, subscriptions". The message that gets posted to the channel should say three alerts, one cause.
- M2 Update line "Supported but outranked: subs-88 (chg:pg-conn-3 explains every alerting service this change does (1) and 2 more)" is a garbled sentence with two ids and nested parentheses. Say "Also plausible: subs-88, but it only explains subscriptions; pg-conn-3 explains all three."
- M3 Toast at bottom centre (455–985, 842–880): "Cause found: pg-conn-3 on postgres-orders. Confirm it to save the fix to memory." Appears over empty space, uses the id, and duplicates the green button. Drop it or make it the button's helper text.
- M4 "Paged: @hana.costa (Platform), @asha.nakamura (Payments)" vs Triage card "Paged Asha Nakamura" only. Same inconsistency as screen 03.
- M5 Confirm button "Confirm: pg-conn-3 caused it" (id again).
**Minor:**
- m1 Sidebar row "checkout, refunds, subscripti…" truncated.
- m2 "WHY THIS CHANGE" chips wrap to two lines with the second arrow orphaned at the line end (1263, 500).
- m3 MEMORY panel is cut off at the bottom of the viewport (scrolls, fine) but says the recalled fix "did not apply here" in smaller text than the recall itself, so at a glance it looks like it applied.
**What works:** The ALERT STORM panel copy ("They share upstream services; the nearest to all of them: payments, postgres-orders. Without correlating them first, the same agents blame a change that explains only one alert.") is the clearest explanation of a graph feature in the app.

### "Show me why", alert storm (08-act3-why-1440.png)
**Score: 6/10**
**10-second test:** Graph with three red-outlined alerting services, an orange path through payments to postgres-orders, and purple "shared upstream" nodes. I believe it is showing why three alerts share a cause. Matches.
**Blockers:** none.
**Major:**
- M1 Labels clipped on the left edge of the graph panel: "atency" at (320, 383) and "tions-latency" at (320, 410), plus a half-hidden node at (330, 405).
- M2 Legend cut at "- - - ret" (y≈883) again.
- M3 Floating purple label "shared by all 3 alerting services" at (683, 572) is not attached to anything; it sits between payments-gw and pg-conn-3. Attach it to the nodes it describes or put it in the panel.
- M4 Agent steps go #4 → handoff → #6. Missing #5 (same bug as screen 04, different number).
- M5 Same jargon as screen 04: "correlate_alerts", "WHY LLM chose correlate_alerts", "Cypher: 5 querys…" style rows.
**Minor:**
- m1 Step #2 text is a wall: "6 upstream services are shared by all of them, nearest to all first: payments, postgres-orders, fraud-check". Break into two lines.
- m2 Person nodes ("Tomas Brandt", "Pia Petrov", "Jae Haddad") float with no visible edge to anything in this zoom.
**What works:** Red outlines for alerting services and purple for shared upstream make the correlation visible without reading anything.

### Ask the company brain, empty (09-ask-empty-1440.png)
**Score: 7/10**
**10-second test:** Left: "Ask the company brain", six suggested questions as chips, an input at the bottom. Right: the whole service dependency graph. I believe this is a Q&A over the company's systems; I would click "Who owns kafka?". Matches.
**Blockers:** none.
**Major:**
- M1 Graph on the right renders at roughly 9px labels ("web-frontend", "api-gateway") in a 800×780 panel with ~200px empty margins on every side. Fit to panel; this is unreadable from the back of a room in a demo video.
- M2 Legend bottom-right ends with an orange bar cut off at x≈1435 after "- - - retired dependency". Something is missing after it.
**Minor:**
- m1 Left column content is vertically centred, leaving ~280px of nothing above the heading. Top-align it.
- m2 Paragraph "No LLM writes it: it is assembled from graph facts and quoted text." is a good promise; move it to a one-line note under the input so it does not read as a disclaimer.
- m3 Graph header "callers left, dependencies right" is useful; keep.
**What works:** Suggested-question chips are concrete and in plain English ("Why was the payments gateway pool lowered?"). This is the one page with no ids on it.

### Ask the company brain, answer (10-ask-answer-1440.png)
**Score: 6/10**
**10-second test:** A numbered list of five sources with type badges (DESIGN, CHAT, STATUS_UPDATE, POSTMORTEM, TICKET), then "LINKED IN THE GRAPH" chips, then a Cypher expander. The graph on the right highlights payments / payments-gw / checkout and two people. I believe this is the answer to "why was the pool lowered". Partly matches: I cannot see the question or a one-sentence answer in this capture, only sources.
**Blockers:** none.
**Major:**
- M1 Typo in the expander (y≈797): "Cypher: 4 querys, 69 rows, 8.9 ms". "queries". Appears on mobile too (screen 16).
- M2 The answer panel starts at y=82 with item "1. DESIGN …"; the question asked and any summary sentence are scrolled out of view, so the screenshot reads as a search-results page, not an answer. Pin the question and a one-line answer at the top of the panel.
- M3 Graph labels clipped on the right edge at x≈1425: "re" (640) and "pl" (718).
- M4 Badge "STATUS_UPDATE" has an underscore; "STATUS UPDATE".
**Minor:**
- m1 Chips in "LINKED IN THE GRAPH" are 15 items with no grouping; group by type (Services, People, Tickets…) or cap at 8 with "+7".
- m2 Item 3 truncates with "…" mid-sentence; it is the same text as the act-1 update. Fine, but show "(this incident)".
- m3 Graph header still says "25 services · 39 dependencies" while most are dimmed; say "highlighting 8 of 25".
**What works:** Source cards with type badge, title and a two-line excerpt are exactly the right unit; the highlighted people and runbook on the graph tie the answer to things I can click.

### Connect, 1440 (11-connect-1440.png)
**Score: 7/10**
**10-second test:** "Plug it into your stack", six cards: MCP, webhook, Slack, own data, who decides, per-company graph. I believe it is the integration page for engineers; I would copy the curl. Matches.
**Blockers:** none.
**Major:**
- M1 Code blocks soft-wrap mid-token: "oncall-b / rain" and "mcp_s / erver" in card 1 (y 310–365), "/api/t / enants", "sympto / m", "abov / e 2s" in card 2 (y 293–400), "hooks.slack.co / m" in card 3. Use `white-space: pre; overflow-x: auto` and a copy button.
- M2 Cards 3, 5 and 6 vertically centre their text, leaving 40–70px blank bands under their headings (card 3 y 205–255, card 5 y 530–590, card 6 y 530–600) while cards 1, 2, 4 are top-aligned. Top-align all.
- M3 Jargon without a gloss on an otherwise engineer-friendly page: "tenant" (card 6, twice), "idempotent MERGE" (card 4), "Cypher query" (card 5), "LLM_PROVIDER". One parenthetical each is enough: "tenant (company)".
**Minor:**
- m1 Card 1 footnote "Over HTTP instead: python -m oncall_brain.mcp_server --http --port 8001" is a command in body text, not a code block.
- m2 Card 6 "This page shows tenant shots; add ?tenant=<name> to the URL and Reset demo to try another" is the only place "shots" is explained; say it in the header chip instead.
- m3 Card 2 note "symptom is latency, errors or saturation" belongs in the JSON as a comment.
**What works:** Six cards, each a real integration with a real command; the webhook curl is the kind of thing I would actually paste.

### Connect at 390 (12-connect-390.png)
**Score: 6/10**
**10-second test:** Same page stacked. I believe it is the integration page. Matches.
**Blockers:** none.
**Major:**
- M1 Header takes 170px of an 844px viewport: logo row, tab row, then four status chips wrapped onto two rows (y 95–160). On a phone, collapse "FalkorDB / planner / company / Reset demo" into one overflow menu.
- M2 Code blocks wrap worse than desktop: "onca / ll-brain", "oncall_brain.m / cp_server", and the curl puts a bare "\" on its own line (y 770). Horizontal scroll, not wrap.
**Minor:**
- m1 Card 1 footnote command wraps across three lines in grey small text (y 530–570); hard to read.
- m2 Nothing says this is a phone-hostile page; a "best viewed on desktop" line would be honest.
**What works:** Cards stack cleanly with consistent padding.

### Incident "Show me why" at 390 (13-incident-why-390.png)
**Score: 3/10**
**10-second test:** Logo, tabs, four chips, "Incidents 3" with no incidents listed, three greyed demo cards, and then a "Cause found" pill sitting on top of the third demo card, a four-line title, and an "ALERTS checkout, refunds, subscriptions 20 Oct, 09:" line cut off. I cannot see a graph or a single agent step. I would not know this is the evidence view.
**Blockers:**
- B1 Overlap: the sidebar is a fixed-height scroll box and the incident header is painted over its bottom. "Cause found" pill at (20, 530) sits on the third demo card ("3. 3 alerts at once", y 480–550) and the card's text "Three services alert within four minutes. One shared cause, or three?" shows through under the pill and the title. Broken layout on the first screen.
- B2 Nothing about "why" is visible: the graph and the agent steps are below the fold; the first viewport shows chrome, demo cards and a header. On a phone, "Show me why" should open the agent steps first and the graph behind a toggle.
**Major:**
- M1 Title "3 alerts: checkout, refunds, subscriptions" wraps to four lines at ~22px, with the "Answer / Show me why" buttons squeezed to its right (160–360, 615–650). Put the buttons under the title, full width.
- M2 Meta line wraps to four lines: "subscriptions · 20 / Oct, 09:30 IST · / inc:subscriptions- / latency". Drop the "inc:" id on mobile.
- M3 "ALERTS checkout, refunds, subscriptions 20 Oct, 09:" cut off at the right edge (y≈777).
- M4 "Incidents 3" header with zero incident rows under it; the list is missing on mobile, only the demo cards show.
- M5 Header chips wrap to two rows (same as screen 12).
**Minor:**
- m1 Demo cards are greyed "Fired" but still take 250px above the incident.
**What works:** Nothing I can point to on this viewport.

### Incident answer at 390 (14-incident-answer-390.png)
**Score: 3/10**
**10-second test:** Identical chrome to screen 13; the only product content in the viewport is the top of the TRIAGE card at y 775–844 ("Paged Asha Nakamura (@asha.nakamura, Payments) for svc:subscriptions"). The status update, cause and Confirm button are all below the fold. At 3 AM on my phone I would have to scroll past three demo cards and a four-line title to find out what is wrong.
**Blockers:**
- B1 Same overlap as 13: "Cause found" pill at (20, 530) painted over the third demo card (y 450–530); card text shows through.
- B2 The answer is not on the first screen. Answer-first on mobile: cause, Confirm, then everything else.
**Major:**
- M1 Four-line title with buttons jammed to the right (same as 13).
- M2 "inc:subscriptions-latency" and "svc:subscriptions" ids on a 390px screen.
- M3 "Incidents 3" with no rows.
- M4 Header chips on two rows.
**Minor:**
- m1 Scrollbar at the right of the agent cards (x≈380, y 775–844) shows a second nested scroll region; nested scrolling on a phone is a trap.
**What works:** "Answer" is visibly the selected toggle, so at least I know which mode I am in.

### Ask at 390 (16-ask-390.png)
**Score: 4/10**
**10-second test:** Header chrome, then a ~100px scroll box with the tail of an answer ("SERVICE checkout, TEAM Checkout, MESSAGE #payments, Cypher: 4 querys…"), an input, then a thumbnail of the whole graph with ~5px labels filling 450px. I would guess "some search over services". I cannot see the question or the answer.
**Blockers:** none, but only just.
**Major:**
- M1 The answer lives in a fixed-height box of ~100px (y 165–265) with its own scrollbar; the graph gets 450px. Invert it: answer takes the screen, graph behind a "Show on graph" button.
- M2 Graph labels are unreadable at this size (every node ~4px text, e.g. "api-gateway" at (95, 575)). Unreadable element on screen; hide the graph at this width or render a list.
- M3 Graph header cut: "25 services · 39 dependencies (1 retired) · callers left, depen" at the right edge (y≈355).
- M4 Legend cut at "per" (y≈826).
- M5 Typo "querys" again (y≈236).
**Minor:**
- m1 Input placeholder "Ask about services, owners, decisions, pas" is cut; shorten to "Ask about services, owners, decisions…".
- m2 Chips in the answer box are 80% of its height, so one row of chips is the whole visible answer.
**What works:** Input and "Ask" button are reachable with a thumb and clearly labelled.

### Landing / empty inbox at 390 (17-landing-390.png)
**Score: 5/10**
**10-second test:** "On-call Brain", three tabs, chips, "Incidents" (empty, no text), "DEMO ALERTS" with three Fire buttons, and only then the hero "Your AI on-call teammate". I believe it is an on-call tool with canned alerts. It matches, but the demo rig is the first thing I see and the product pitch is the second.
**Blockers:** none.
**Major:**
- M1 Order: the demo-alert list (y 230–545) comes before "what this is" (y 545+). On mobile, hero first, then one "Fire the first alert" button, demo list collapsed.
- M2 Third demo card is clipped at the bottom by the sidebar scroll container: the card's bottom border is missing at y≈540 and the eyebrow text starts immediately under it at y 545, with a scrollbar thumb at (380, 525–540). Cut-off element.
- M3 Header chip reads "company: shots390" while every other screen says "shots". That looks like a leaked test tenant name. Use the same display name everywhere (and not the id).
- M4 Header chips on two rows (same as 12/13/14).
**Minor:**
- m1 "Incidents" heading with no "No incidents." text under it; the desktop empty-state copy is missing here.
- m2 Hero paragraph is set at ~19px on a 390px screen and runs eight lines; drop to 16px.
- m3 Eyebrow "INCIDENT RESPONSE ON A KNOWLEDGE GRAPH · FALKORDB" wraps to two lines of tracked caps.
**What works:** The three demo cards are readable and the Fire buttons are a good tap size.

## Overall
**Lowest score:** 3/10 on Incident "Show me why" at 390 (13) and Incident answer at 390 (14)

**Top 5 fixes, in order of impact**
1. Remove the "null" / "nullnull" line under the agent cards (screens 02, 03, 05, 06, 07): one template string rendering undefined values, visible on every incident screen in the demo video.
2. Mobile incident layout (13, 14, 17): the fixed-height sidebar paints under the incident header and clips the third demo card; collapse demo alerts and header chips into menus and put the cause + Confirm button first on the screen.
3. Confirm button and status semantics (03, 05, 06, 07): name the change in words ("Confirm: the payments-gw pool change caused it") not "pgw-pool-1", always show "Wrong cause?" (missing on 06), and do not flip the incident to "Resolved" on confirm; call it "Cause confirmed".
4. Strip internal vocabulary from human-facing surfaces (all screens): "svc:/inc:/chg:" prefixes in titles and cards, "planner: claude-opus-5-5" chip, "steps chosen by claude-opus-5-5", "REFUTES", "hypotheses", "WHY LLM chose", snake_case tool names, "tenant"; fix the "querys" typo (10, 16); give Sources titles instead of "msg:pay-deploys-1".
5. Graph rendering (04, 08, 09, 10, 16): fit-to-panel with label padding so nothing is clipped at the edges, let the legend wrap instead of ending in "- - - ret", fix the overlapping labels around checkout-latency / pgw-pool-1, and number the handoff row so Agent steps do not skip #4 / #5.

**Ship it?** Not yet: the desktop flow is a genuinely good incident update with evidence, but a visible "null" on every incident screen, a Confirm button that names an id the engineer has never seen, and a phone layout that paints the incident header over the demo cards would make a judge mark it down and an on-call engineer close the tab.
