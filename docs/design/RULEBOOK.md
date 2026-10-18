# On-call Brain UI rulebook

Written before the code. `web/style.css` implements it, and the design reviewer audits against it. Direction: **Pager**,
chosen from three mocks (Pager, Runbook, Blueprint; screenshots and the reasons in
`docs/screenshots/revamp/directions/README.md`).

## 1. The one idea

The page is the page you were woken by. An incident opens as an ink-black readout slab: the time and the service in
condensed numerals, the alert in large type, four counts under it. Everything below the slab answers that page in the
order an on-call engineer needs it, as ruled dispatch rows: Cause, Where, Since, Who, Do this, Ruled out, Sources.
One red is reserved for what is broken right now. When a human confirms the cause, the red Firing block becomes an ink
Confirmed block, and the memory the graph just learned shows under Do this.

Grafts from the other two mocks: Blueprint's evidence wire (the cause path drawn as boxes on one signal line, the
minute each service went red under each box) in the Where row; Runbook's "the confirm lands on the slab" moment.

Boldness lives in one place: the slab. Everything else is quiet paper, ink and rules.

## 2. Tokens (`:root` in web/style.css; nothing else in the CSS declares a colour or a font family)

### Colour (six)

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#F8F6F4` | page ground |
| `--paper-2` | `#EAE7E4` | second surface: selected inbox row, the drafted update, code blocks, inputs |
| `--rule` | `#BBB6B2` | 1px hairlines between rows; graph edges that are not evidence. Never text. |
| `--muted` | `#5E5652` | secondary text on paper and paper-2 only |
| `--ink` | `#18120F` | text, 2px section rules, the slab, filled buttons, focus ring on light |
| `--signal` | `#C50710` | only what is broken right now: the Firing block, the alerting service, anomaly times, the evidence wire, the leading cause mark |

Derived, for text on the slab only: `--on-ink: #F8F6F4` (paper) and `--on-ink-2: #CFC8C3` (secondary text on ink).

No other colours. There is no green, no amber and no orange. Confirmed is ink, not green. Investigating is a dashed
ink outline, not yellow.

### Type (two families, vendored as woff2 in web/vendor/fonts with their OFL licence; no runtime CDN)

- `--font-display`: **Barlow Condensed** 600 and 700. Used for the wordmark, the slab title, every time and count (inbox
  times, slab counts, the Since timeline, step numbers, group counts) and view headings.
- `--font-body`: **IBM Plex Sans** 400 and 600. Used for body text, the UI, labels, buttons and tables.
- `--font-code`: **IBM Plex Mono** 400. Used only inside `<pre>`/`<code>` for Cypher, curl and shell commands. Never
  for labels, ids, numerals or small text.

Scale (px): 13 (smallest; meta and table heads), 14 (secondary), 16 (body), 20 (the cause line, the Ask answer lead),
28 (display numerals in lists and view headings), 44 (slab counts), and the slab title at `clamp(34px, 18px + 2.2vw, 60px)`.
Body line-height is 1.5 and display line-height is 1.02. Use tabular figures everywhere numbers line up.
Sentence case throughout. No uppercase transforms and no letter-spacing on labels.

### Spacing, radius, depth, motion

- Spacing scale: `--s1` 4, `--s2` 8, `--s3` 12, `--s4` 16, `--s5` 24, `--s6` 32, `--s7` 48, `--s8` 64. Every padding, gap
  and margin uses the scale. Gutter: 16px under 600px, 24px to 1100px, 32px above.
- Radius: 0 everywhere (buttons, inputs, blocks, graph nodes are squares or circles drawn by the graph only).
- Depth: none from shadows. Hierarchy comes from the ink slab, 2px ink rules between sections and 1px `--rule` lines
  between rows. `box-shadow` appears only as the focus ring fallback.
- Controls are 40px tall on desktop and 44px on touch. The primary button is filled ink with paper text; the secondary
  button is a 1.5px ink outline. A destructive action (Reset demo company) is a text button that asks to confirm in
  place.

### Motion

- One orchestrated moment: when an answer arrives (a run completes, or a stored incident opens), the slab prints first,
  then the dispatch rows follow 45ms apart (opacity plus a 6px rise, 360ms, `cubic-bezier(.16,1,.3,1)`).
- Allowed otherwise, because it is real work or an answer to the user: agent steps appearing while a run is streaming;
  hover and press colour changes (120 to 180ms, colour and background only); details open and close.
- Not allowed: `transition: all`, hover scale, animating width, height, top, left, margin or padding, overshoot easing,
  scroll-triggered reveals, counters ticking, any looping animation except the one "working" indicator during a live run.
- `prefers-reduced-motion: reduce`: no travel and no fades; final frames only.

## 3. Contrast pairs (WCAG 2.1, measured; reviewers re-measure from computed styles)

| Text | On | Ratio | Use |
|---|---|---|---|
| ink | paper | 17.20 | body, headings |
| ink | paper-2 | 15.06 | selected row, update draft, code |
| muted | paper | 6.65 | secondary text |
| muted | paper-2 | 5.82 | secondary text on the second surface |
| signal | paper | 5.71 | anomaly times, "Supported", the alerting service name |
| signal | paper-2 | 5.00 | the same on paper-2 (passes AA for body) |
| paper | signal | 5.71 | the Firing block, the alerting service box |
| paper | ink | 17.20 | slab text, filled buttons, the Confirmed block |
| on-ink-2 | ink | 11.22 | secondary text on the slab |

Banned pairs: signal text on ink (3.01), ink text on signal (3.01), muted on ink (2.59), and rule-coloured text anywhere
(1.86). On the slab, red appears only as a filled block with paper text. Focus ring: 3px ink outline offset 2px on light
grounds and 3px paper outline on the slab; it appears instantly with no transition.

## 4. Layout

- **Top bar** (56px, paper, 2px ink rule under it): the wordmark "On-call Brain" with a one-line positioning sentence
  beside it at desktop widths ("What broke, why, who is paged and the fix, with the proof from your company graph"),
  the three views (Incidents, Ask the brain, Connect) as text tabs with a 3px ink underline on the current one, and on
  the right one secondary button "Simulate an incident". Nothing wraps; at 390 the bar is two rows (brand and Simulate,
  then the views) and the positioning sentence moves into the landing.
- **Incidents, desktop:** inbox rail 300px on the left, the incident on the right with a reading column of at most 880px.
  The rail groups rows under "Open" and "Confirmed", each with its count as a display numeral. A row is a big condensed
  time over the date, then the title, the service and team, and the status in words.
- **No incident open:** the right side is the landing. It has the positioning line as a 28px heading, one paragraph,
  the primary "Simulate an incident: <next scenario>" button, a "Connect your alerts" text link, and the three-step
  "how it works" as a ruled numbered list (not cards). The facts line follows: services, teams and dependencies, with
  correct singular and plural.
- **Incident:** the slab first, then a bar with the Answer / Show me why tabs on the left and Confirm cause / Wrong cause
  on the right, then the dispatch rows (a 120px label column and the content column, split by 1px rules, with 2px ink
  rules above and below the group), then the status update drafted for #incidents.
- **Show me why:** the incident subgraph (Cytoscape, restyled to the tokens: ink nodes and labels, signal for the evidence
  path and the alerting service, rule-coloured for context) beside a numbered step log grouped by role (Triage,
  Investigator, Comms, each with its count as a display numeral). Every step shows the question it answered, who chose
  it (model or rules) and the reason, with its Cypher in a closed `<details>`. Clicking a step highlights its part of
  the graph.
- **Phone (under 900px):** one column. With nothing open, the inbox comes first once an incident exists, otherwise the
  landing comes first. With an incident open, the inbox is hidden behind an "Incidents" back button, the slab comes next,
  and Confirm / Wrong cause sit in a bar fixed to the bottom of the screen. In Show me why the graph is 60vh tall and
  fitted to the evidence path, with the step log under it. In Ask, "Show on graph" opens the graph above the answer and
  scrolls to it.
- Prose measure is 45 to 75ch. Interactive rows set `align-items: center`. There is no horizontal page scroll from 320 to
  1920px (`overflow-x: clip` on html and body); a wide code block scrolls inside itself.

## 5. Components and states

- Every interactive element has default, hover, focus-visible, active and disabled styles. Confirm cause and Wrong cause
  also have a loading state ("Saving…") and a done state (the slab block flips).
- **Status block on the slab:** Firing (signal fill, paper text) while the incident is open; Investigating (the same block
  with the live step underneath) while agents run; Confirmed (ink fill, paper text, with a 1.5px paper outline so it
  reads on the slab) after a human confirms; Needs a human (signal outline, paper text) when no cause was found.
- **Inbox row:** default, hover (paper-2), selected (paper-2 plus a 3px ink bar on the left edge, the only side bar
  allowed, because it marks selection rather than decoration), and focus-visible.
- **Every view has empty, loading, error and full states with real copy.** Empty says what will appear and how to make it
  happen. Loading shows the structure (skeleton rows in paper-2, no spinners except the one working indicator). An error
  says what failed in plain words and the one thing to try, appears in the content area where the content would be
  (never over a heading), and keeps the raw API text in a closed details element. FalkorDB down (health 503) shows in
  the top of the incidents view as an ink-ruled notice with "Start FalkorDB with make db, then reload".
- **Live regions:** streamed steps and the run result are announced politely (`aria-live="polite"`). The graph has an
  accessible name and a text alternative (the evidence path as a sentence). Toasts are for invisible effects and
  failures only; they sit bottom-left on desktop and bottom on phone, never over a heading, and close with a button.
- **Copy:** buttons say what happens ("Confirm cause", "Simulate an incident", "Copy update"). Tool names in snake_case
  never appear in prose; they appear only in the Cypher details as the tool's name.

## 6. Banned (the design reviewer fails any of these on sight)

- cream plus terracotta; dark plus neon accent; purple-to-blue gradients, gradient text, gradient washes
- identical rounded cards with soft grey shadows; cards inside cards; coloured side-stripe cards (the selected inbox row's
  ink bar is the one exception); 3-column icon-above-heading tiles
- ALL-CAPS or letter-spaced eyebrow labels; an eyebrow beside a heading; "A · B · C" middle-dot meta strings; "WORD —
  fragment" labels
- monospace outside code blocks; a fourth font family; italic words inside headings
- arrows glued to links and buttons ("Open →"); emoji or check-mark glyphs as icons or status (status is words); two icon
  sets; fake browser, phone, terminal or Slack chrome (the status update is a ruled block, not a fake Slack message)
- invented numbers or names: every number and name on screen comes from the API or the fixtures
- any colour outside the six tokens and the two on-ink derivatives; rounded corners; drop shadows
- Inter, Roboto, Poppins, Space Grotesk or system-ui as the identity face; pure #000 or #fff
- a hero with every element centred on one axis; a toast celebrating something the user can already see; the same
  action offered twice on one screen (the header Simulate and the landing button may both exist only because the header
  one is the persistent entry and the landing one names the next scenario)

## 7. Copy voice

Plain, sentence case, from the engineer's side, active verbs. The first line of every view says what you can do there.
Times are shown in the viewer's local time with the zone named once per view. No "AI-powered", no "seamless", no
exclamation marks, and no jargon ("tenant", "planner", "MCP") outside the Connect view.
