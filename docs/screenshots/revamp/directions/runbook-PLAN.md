# Direction: Runbook

## The one idea

The answer is a printed incident sheet from the operations manual: a ruled verdict box at the top, a numbered procedure beneath it (what broke, who is paged, the fix, what was ruled out, the status update) and references at the foot, with one red mark for the live incident. When the engineer confirms the cause, a stamp lands on the verdict box and the fix section fills with the runbook the graph just learned.

## Palette (6 tokens)

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#F4F5F7` | page, cool bond paper (OKLCH ~97% 0.004 250) |
| `--paper-2` | `#E9EBEF` | status-update block, Cypher blocks |
| `--rule` | `#C6CBD3` | hairlines between rows |
| `--muted` | `#5A6270` | secondary text, reference marks |
| `--ink` | `#1B2130` | text, borders, the stamp, the primary button |
| `--signal` | `#BE1E2D` | the live incident only: inbox dot, state line, verdict square, anomaly times, the supporting step number |

Contrast pairs (WCAG 2.1): ink on paper 14.7:1; ink on paper-2 13.5:1; muted on paper 5.6:1; muted on paper-2 5.2:1; signal on paper 5.6:1; signal on paper-2 5.2:1; paper on ink (Confirm button) 14.7:1. All text pairs pass AA at every size used; the rule colour is never used for text.

Signal budget: a 8px dot, a 10px square, one short line of 14px text, three timestamps. Well under 3% of any viewport. The stamp and the primary button are ink, not signal, so "confirmed" never reads as "alarm".

## Type

Two families, both Google Fonts.

- **Source Serif 4** (opsz, 400 and 600): display and body. The voice of a typeset manual; the optical-size axis keeps 14px meta crisp and 31px titles tight.
- **IBM Plex Mono** (400): Cypher blocks only. Never for labels or ids.

Scale, ratio 1.25 from 16px: 14 (meta, sources, reasons), 16 (body), 20 (procedure headings, stamp), 25 (verdict cause, procedure numerals), 31 (incident title). Five sizes, no more. Tabular numerals everywhere; weight contrast is 400 against 600 with no in-between.

Roles: numerals carry wayfinding (procedure 1 to 5, agent steps 1 to 19, references 1 to 6); weight carries hierarchy; rules carry grouping. No icons at all.

## Layout, answer view

1440:

```
+----------------------------------------------------------------------------------------------+
| On-call Brain   Incidents  Ask the brain  Connect                     [Simulate an incident]  |
|==============================================================================================|  double rule
|                                                                                              |
| Incidents      5 alerts, 1 open |  * Open since 04:00 UTC, cause identified                  |
| --------------------------------|  checkout p99 latency above 2s                              |
| * checkout p99 latency above 2s |  Fired on checkout on 15 Oct. 2 people paged, 2 warned ... |
|   checkout, 15 Oct 04:00 UTC    |  Answer   Show me why                                       |
|   Open, cause identified        |  ----------------------------------------------------------- |
| --------------------------------|  +----------------------------------------------------+    |
|   refunds p99 latency above 2s  |  | # Verdict                       Very likely, high  |    |
|   refunds, 18 Oct 04:00 UTC     |  | A config change on payments-gw by Sana Brandt 5    |    |
|   Waiting for the agents        |  | "Lower payments-gw HTTP pool ..." 1 landed 03:20   |    |
| --------------------------------|  | Why we think so: anomalies follow this change ...  |    |
|   checkout p99 ... (20 Oct)     |  | payments-gw 03:22 -- payments 03:24 -- checkout    |    |
|   refunds p99 ...  (20 Oct)     |  +----------------------------------------------[stamp]    |
|   subscriptions ...(20 Oct)     |  [Confirm cause]  [Wrong cause]                             |
|                                 |  =========================================================== |
| Alerts arrive from your webhook |  1   What broke         checkout p99 latency ..., on checkout|
|                                 |  --------------------------------------------------------- |
|                                 |  2   Who is paged       Asha Nakamura   on call for payments-gw|
|                                 |                         Ravi Moreau     on call for checkout |
|                                 |  --------------------------------------------------------- |
|                                 |  3   The fix            No runbook yet. Confirm the cause... |
|                                 |  --------------------------------------------------------- |
|                                 |  4   Ruled out, 4       ~~Deploy legacy-billing v1.9.3~~    |
|                                 |  --------------------------------------------------------- |
|                                 |  5   Status update      [ pre-wrapped update text ]  Copy   |
|                                 |  =========================================================== |
|                                 |  Sources                                                    |
|                                 |  1 Change Lower payments-gw ...   4 Message #payments-deploys|
|                                 |  2 Doc Postmortem: ...            5 Person Sana Brandt       |
|                                 |  3 Doc Q4 cost review: ...        6 Ticket CR-881 ...        |
+----------------------------------------------------------------------------------------------+
   300px inbox        64px gutter        sheet, max 860px, left-biased; the right margin stays empty
```

390:

```
+----------------------------------------+
| On-call Brain    [Simulate an incident]|
| Incidents  Ask the brain  Connect      |
|========================================|
| Incidents              5 alerts, 1 open|   <details>, collapsed; tap to open the list
|----------------------------------------|
| * Open since 04:00 UTC, cause identified|
| checkout p99 latency                   |
| above 2s                               |
| Fired on checkout on 15 Oct. ...       |
| Answer   Show me why                   |
|----------------------------------------|
| +------------------------------------+ |
| | # Verdict      Very likely, high   | |
| | A config change on payments-gw     | |
| | by Sana Brandt 5                   | |
| | "Lower payments-gw ..." 1 landed   | |
| | Why we think so: ...               | |
| | payments-gw 03:22 UTC              | |
| |   -- payments 03:24 UTC            | |
| |   -- checkout 03:25 UTC    [stamp] | |
| +------------------------------------+ |
| [Confirm cause] [Wrong cause]          |
|========================================|
| 1  What broke                          |
|    checkout p99 latency ..., on checkout|
|----------------------------------------|
| 2  Who is paged                        |
|    Asha Nakamura   on call for payments-gw|
| ...                                    |
|========================================|
| Sources (one column)                   |
+----------------------------------------+
   36px numeral column, 16px side gutters, no horizontal scroll
```

"Show me why" uses the same sheet: a stats line, the evidence path drawn as four ruled boxes joined by arrows (the change, double-ruled, then payments-gw, payments, checkout with the anomaly time on each in signal), the four ruled-out suspects struck through beneath it, then the 19 steps in order under three role headings, each with its summary, the agent's reason, the tool and who decided, and a disclosure holding every Cypher query with parameters, row count and ms. Handoffs are a quiet ruled line between roles. At 390 the path boxes stack vertically with the arrows turned downward.

## The single load moment

The sheet's three blocks (head, answer, why) settle in once: 6px rise and fade, 360ms, exponential ease-out, staggered 60ms. Nothing else animates on load. The only other motion answers an action: pressing Confirm cause scales the stamp from 1.25 to 1 over 220ms as it lands. Both are removed under `prefers-reduced-motion`. Tab switches are instant.

## Self-review: what risked being generic, what changed

- **Risk: the dev-tool look (sans body, mono everywhere, pill tabs, cards).** Changed: serif body and display, mono only inside Cypher blocks, tabs as underlined words, no cards. Sections are separated by rules of two weights (ink for sections, light for rows) and dotted rules for people. Nothing is rounded, nothing has a shadow.
- **Risk: cream and terracotta "paper".** Changed: the paper is cool and faintly blue, the ink is blue-black, the signal is a stamp-pad red. It reads as bond paper and a red pen, not a café menu.
- **Risk: tag-left eyebrow heads.** The procedure and the step log use hanging numerals, but each numeral is a list counter on the same baseline as its heading inside an `<ol>`, not a tracked label beside a title, and both lists are genuinely ordinal (a procedure, a log). No eyebrows, no uppercase tracking anywhere.
- **Risk: a decorative graph drawing.** Changed: the evidence path is the actual `live_paths` row from the run with the `anomalies_between` times on each node, and the refuted suspects are struck through with the agent's reason. It shows what the graph returned, not a pretty network.
- **Risk: the first-draft stamp covered the confidence line and the three-line wrap of the verdict made it read like a poem.** Changed: the stamp now presses over the bottom-right corner of the box, and the cause line is capped at 30ch so it sits on two lines at 1440.
- **Risk: a dangling second row of path nodes.** Changed: the drawing holds only the cause path; the downstream services became a sentence under it.
- **Risk: invented numbers.** Every figure on the page comes from `act1.json`, `alerts.json`, `graph.json` and `resolve.json`: 19 steps, 82 queries, 0.18 s, 106,642 tokens, 03:20/03:22/03:24/03:25 UTC, 40 minutes, the people, the handles, the sources. The only derived numbers are sums and differences of those.
- Left for the real build: the Ask and Connect views, a dark mode (paper and ink invert cleanly, nothing else changes), keyboard arrow navigation on the tablist, and the inbox rows actually switching incidents.
