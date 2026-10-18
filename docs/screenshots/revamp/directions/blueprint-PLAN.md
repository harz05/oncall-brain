# Direction: Blueprint

## The one idea
The incident is a drawing: the service graph is drawn as a wiring schematic in one ink on a technical ground, and the
proof is the single wire drawn in the signal colour, running from the config change through payments-gw and payments
into the alerting checkout box, annotated with the minute each service went red. Owners, on-call and the change sit in a
title block under the sheet, so "who, what, when" is read the way an engineer reads any drawing.

## Palette (6 tokens, all hex, no alpha)
| token | hex | role |
|---|---|---|
| `--paper` | #eef1f6 | ground, cool-tinted (never pure white) |
| `--paper-2` | #e2e7ef | selected inbox row, handoff rows, impacted boxes on the drawing |
| `--rule` | #aeb8c8 | hairline dividers only (decorative, 1.77:1, never text or a meaningful boundary) |
| `--wire` | #55617a | muted text, dependency wires, arrowheads |
| `--ink` | #141f3a | text, hard rules, boxes, filled buttons |
| `--signal` | #b32f0a | the live fault only: evidence wire, alerting marker, "Likely cause", anomaly times, active nav underline |

Contrast pairs (WCAG 2.1, computed):
ink on paper 14.41:1; ink on paper-2 13.14:1; wire on paper 5.49:1; wire on paper-2 5.01:1; signal on paper 5.57:1;
signal on paper-2 5.08:1; paper on ink (filled buttons, selected tab) 14.41:1; paper on wire (filled-button hover) 5.49:1.
All text pairs are at or above AA (4.5:1). Dependency wires (1.2px, wire on paper) are 5.49:1, above the 3:1 for UI graphics.

## Type (two families, Google Fonts)
- Display and labels: **Archivo** (variable, width 62-125, weight 400-800). Wordmark at wdth 112, headings at wdth 96,
  the cause service at wdth 80 / 800, drawing labels at wdth 92. The width axis gives the drawing-lettering register
  without a third family.
- Body and UI: **IBM Plex Sans** 400/600. Also carries the Cypher blocks (pre, pre-wrap, 13px, left rule) so there is no
  monospace anywhere; identifiers are told apart by weight, not by face.
- Scale (1.25 from 15): 13 small labels and table heads, 15 body, 19 role headings and wordmark, 24 incident title,
  30 the cause line. Tabular figures everywhere (`font-variant-numeric: tabular-nums` on html). Drawing: 13px box
  labels, 12.5/11.5px tag, 11.5px annotations with a paper halo (min-width 980px keeps them legible at 390 by panning).

## Layout, answer view at 1440
```
+---------------------------------------------------------------------------------------------------------+
| On-call Brain   Incidents  Ask the brain  Connect                 Agents run on claude-opus-5-5. Graph: ...|  1.5px ink rule
+-----------------------+---------------------------------------------------------------------------------+
| Incidents  5 alerts.. | checkout p99 latency above 2s                               [ Answer |Show me why]|
| # checkout p99 ... *  | Fired Thu 15 Oct 09:30 IST on checkout (Checkout). Open.                          |
|   Thu 15 Oct 09:30    |---------------------------------------------------------------- 1.5px ink rule ---|
| o refunds p99 ...     | Likely cause                                                   [ Confirm cause  ] |
| o checkout p99 ...    | payments-gw: Lower HTTP pool max_connections 200 -> 20          [ Wrong cause   ] |
| o refunds p99 ...     | Config change by Sana Brandt, Thu 15 Oct 08:50 IST, 40 min before the alert.      |
| o subscriptions ...   | [Very likely: 4 of 5 suspects ruled out]  Why this confidence: ...                |
|                       |-------------------------------------------------------------------- hairline -----|
| Alerts arrive from    | Why this change: the evidence wire                                                |
| your webhook, ...     | >-pgw-pool-1 ------[]-payments-gw -------[]-payments --------[#]-checkout         |
|                       |   08:50 config      08:52 pool exhausted  08:54 p99 4.2s       08:55 p99 5.1s     |
|                       |                                                                 09:30 alert fired |
|                       | The latency travels payments-gw -> payments -> checkout, the same path ...        |
|                       |-------------------------------------------------------------------- hairline -----|
|                       | What broke (1.05fr)      | Who is paged (1.25fr)             | Fix (0.9fr)        |
|                       | ---- ink rule ----       | ---- ink rule ----                | ---- ink rule ---- |
|                       | checkout p99 ...         | Asha Nakamura   on call for pgw   | No runbook yet ... |
|                       | api-gateway  depends ... | Ravi Moreau     on call for chk   | Seen something ... |
|                       | checkout  alerting       | Heads-up Hana Costa ..., Kiri ... |                    |
|                       |-------------------------------------------------------------------- hairline -----|
|                       | Ruled out (4)   Change | Service | Why not            (table, ink head rule)      |
|                       | Status update drafted for #incidents   [ pre, 1.5px ink frame, 88ch ]             |
|                       | [Change ...] [Doc ...] [Doc ...] [Message ...] [Person ...] [Ticket ...]  sources |
+-----------------------+---------------------------------------------------------------------------------+
```
"Show me why" swaps the sheet body for: intro line, the drawing (figure with caption strip, SVG, then a bottom
strip split 1.1fr/1fr: legend | title block), then the 19 steps as one numbered list with role rules (Triage 4,
Investigator 9, Comms 6), handoffs as paper-2 rows, each step's queries in a details block with the Cypher.

## Layout, answer view at 390
```
+--------------------------------------+
| On-call Brain                        |
| Incidents  Ask the brain  Connect    |
| Agents run on claude-opus-5-5. ...   |
+---- 1.5px ink rule ------------------+
| Incidents           5 alerts, 1 ...  |
| [# checkout p99..][o refunds p99..]> |   inbox becomes a horizontal strip (scrolls inside itself)
+---- 1.5px ink rule ------------------+
| checkout p99 latency above 2s        |
| Fired Thu 15 Oct 09:30 IST ...       |
| [      Answer      |  Show me why  ] |
| Likely cause                         |
| payments-gw: Lower HTTP pool ...     |
| Config change by Sana Brandt, ...    |
| [Very likely: 4 of 5 suspects ...]   |
| [ Confirm cause ] [ Wrong cause ]    |
| Why this change: the evidence wire   |
| |> pgw-pool-1   08:50 config change  |   the wire turns vertical, markers on it
| |[] payments-gw 08:52 pool exhausted |
| |[] payments    08:54 p99 4.2s ...   |
| |[#] checkout   08:55 p99 5.1s, 09:30|
| What broke / Who is paged / Fix      |   stacked, each under its own ink rule
| Ruled out (4)  change | service      |   two-column rows, reason below
|                reason                |
| Status update ... [pre]  sources     |
+--------------------------------------+
```
The drawing at 390 keeps its 980px minimum width inside a figure that pans sideways; the page itself never scrolls
horizontally (checked: scrollWidth 390 on both screens).

## The single load moment
When "Show me why" first renders, the signal wire traces itself from the change tag down into payments-gw, then left
through payments into checkout (one SVG path, `pathLength=1`, dashoffset 1 -> 0, 1.8s, ease-out). It runs once per
page load; everything else appears in place. Under `prefers-reduced-motion: reduce` the wire is simply drawn.
Every other motion answers a click (tab switch, Confirm, Wrong cause, details).

## Self-review: what risked being generic, and what changed
- The three answer columns were an equal 3-column grid with headings. Changed to 1.05fr / 1.25fr / 0.9fr with a hard
  ink rule under each heading and no card borders, so they read as columns on a sheet, not feature cards.
- The dependency graph was going to be a generic node-link diagram. It is now a layered orthogonal schematic: boxes
  with double borders for tier-1, dashed wires for the retired dependency, elbow wires with arrowheads, and paper
  halos so wires break at boxes. The evidence path is the only coloured line, and its arrows run in the anomaly's
  direction (opposite to the dependency arrows), which is the actual argument the investigator makes.
- Meta strings like "Thu 15 Oct · open · checkout" were replaced with sentences ("Fired Thu 15 Oct 09:30 IST on
  checkout (Checkout). Open.") and the title block uses labelled cells instead of dot-joined fragments.
- A first draft of the change tag carried "40 min before the alert", which overflowed the tag; the tag now holds only
  id, kind, time and author, and the 40 min lives in the verdict byline where it is computed from the data.
- The incident sheet had a stray "acme" tenant name that is not in the fixtures; removed. Every number on the page
  (25 services, 39 dependencies, 1 retired, 19 steps, 5 suspects, 3 checks, 106,642 tokens, 40 min, every timestamp)
  is computed from act1.json, alerts.json or graph.json.
- Buttons are hard-cornered ink or ink-outlined, the active nav item is a 2px signal underline, there are no shadows,
  radii, gradients, eyebrows, emoji or icons; the only pictures are the drawing and the legend swatches.
- Not built in the mock: Ask and Connect views (nav only), the live run progress state, and "Run the agents" on the
  alerts that have no run in the fixtures (button is inert).
