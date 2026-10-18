# Direction: Pager

## The idea

The hero object is the page itself: the alert lands as an ink-black readout with the time, the service and the
counts in condensed numerals, exactly the thing the engineer was woken by. Everything under it is a dispatch
answering that page in order (cause, where, since, who, do this), set in hard rules on light paper, with one
red reserved for what is broken right now.

## Palette (six tokens, OKLCH-derived, hex as shipped)

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#F8F6F4` | ground (oklch 97.5% 0.004 70; near-white, not cream) |
| `--paper-2` | `#EAE7E4` | second surface: open inbox row, the drafted update |
| `--rule` | `#BBB6B2` | hairlines and refuted boxes only, never text |
| `--muted` | `#5E5652` | secondary text |
| `--ink` | `#18120F` | text, hard rules, the readout slab, the Confirm button |
| `--signal` | `#C50710` | only: "Firing" block, the alerting service, anomaly marks and times, the supported verdict |

Contrast pairs (WCAG 2.1):
- ink on paper 17.2:1; paper on ink 17.2:1 (readout slab, Confirm button, active tab)
- muted on paper 6.65:1; muted on paper-2 5.82:1
- signal text on paper 5.71:1 (timeline 08:55 / 09:30, "Supported:" result line)
- paper on signal 5.71:1 ("Firing" block, the `checkout` node in the chain and the drawing)
- ink on paper-2 15.1:1 (open inbox row, update preview)
- rule is never used for text (1.86:1); boxes drawn in it carry muted text at 6.65:1.

## Type

- Display and numerals: **Barlow Condensed** 700 (500 loaded, unused on the final page). Roles: wordmark, the
  alert title in the slab (clamp 34-60px, line-height 1.02), every time and count (inbox 22px, slab 44px, group
  counts 28px, step numbers 26px, timeline 20px, drawing 18px).
- Body and UI: **IBM Plex Sans** 400/600, 16px body, 14-15px secondary, 20px for the cause lead. Tabular nums.
- Two families, no mono: the Cypher blocks are Plex Sans 14px `pre-wrap`, which keeps the query readable without
  a third face. Scale used: 14, 15, 16, 20, 26-28, 44, 60 (display).

## Layout, answer view

1440:
```
+--------------------------------------------------------------------------------------------+
| On-call Brain   Incidents  Ask the brain  Connect                 Steps chosen by claude... |
+============================================================================================+
| Open                  1 ||  [Firing] 09:30 15 Oct, IST                     inc:checkout...  |
| 09:30 checkout p99 ...  ||  checkout p99 latency                                            |
| 15 Oct checkout, ...    ||  above 2s                                 (ink slab, paper text) |
|        cause identified ||  checkout, tier 1, owned by the Checkout team.                   |
|-------------------------||  ------------------------------------------------------------    |
| Received, not worked  4 ||  38 min from first   4 services   5 suspects   2 people paged    |
| 09:30 refunds p99 ...   ||     anomaly to alert     hurt        tested                      |
| 18 Oct  Work it         ||+------------------------------------------------------------------+
| 09:26 checkout p99 ...  ||  [Answer][Show me why]              [Confirm cause] [Wrong cause]|
| ...                     ||==================================================================|
|                         ||  Cause     | payments-gw: Lower payments-gw HTTP pool ... 200 → 20|
|                         ||            | Config change by Sana Brandt at 08:50, 40 min before |
|                         ||            | [Very likely] 4 of 5 suspects ruled out; anomalies.. |
|                         ||  ----------+-----------------------------------------------------|
|                         ||  Where     | [payments-gw] → [payments] → [checkout]              |
|                         ||            | Also hurt: api-gateway, mobile-bff, web-frontend ... |
|                         ||  Since     | 08:50  config change lands on payments-gw            |
|                         ||            | 08:52  payments-gw: connection pool exhausted ...    |
|                         ||            | 09:30  alert fires on checkout                       |
|                         ||  Who       | Paged   Asha Nakamura @asha.nakamura, Payments ...   |
|                         ||            | Heads-up Hana Costa ...   Knows it best Sana Brandt  |
|                         ||  Do this   | No runbook for this yet. Ask Sana Brandt ...         |
|                         ||  Ruled out | legacy-193 on legacy-billing [dependency retired]    |
|                         ||  Sources   | Change  Lower payments-gw HTTP pool ...      15 Oct  |
|                         ||==================================================================|
|                         ||  Status update drafted for #incidents  preview  09:30            |
|                         ||  [ checkout p99 latency above 2s: cause identified, fix pending ]|
+--------------------------------------------------------------------------------------------+
```

390:
```
+------------------------------------+
| On-call Brain                      |
| Incidents  Ask the brain  Connect  |
+====================================+
| Open                             1 |
| 09:30  checkout p99 latency ...    |
| Received, not worked yet         4 |
| 09:30  refunds p99 ...  Work it    |
| ... (3 more rows)                  |
+====================================+
| [Firing] 09:30 15 Oct, IST         |
| checkout p99 latency               |
| above 2s                 (ink slab)|
| 38 min from first   4 services hurt|
| 5 suspects tested   2 people paged |
+------------------------------------+
| [Answer][Show me why]              |
| [   Confirm cause ][ Wrong cause ] |
|====================================|
| Cause                              |
| payments-gw: Lower payments-gw ... |
| Where                              |
| [payments-gw] → [payments] →       |
| [checkout]                         |
| Since / Who / Do this / Ruled out /|
| Sources, each label above its text |
| Status update drafted ...          |
+------------------------------------+
```
"Show me why": the evidence drawing (SVG, 1000x330 viewBox) sits full width above the steps; at 390 it scrolls
inside its own frame (min-width 760) so the page never scrolls sideways. Steps are grouped Triage / Investigator /
Comms with the count as a numeral, each step: question, who chose it, the agent's reason verbatim, the result,
and a native `<details>` with the tool's Cypher. The supporting check (step 10) is open by default.

## The single load moment

The readout slab prints first, then the seven dispatch rows and the update follow at 45 ms steps (360 ms ease-out,
6 px rise). Nothing else moves on its own: tab switches are instant, buttons only shift colour on hover, and
`prefers-reduced-motion: reduce` removes the print entirely.

## Self-review

What risked being generic, and what changed:
- The first draft put "Decided by claude-opus-5-5, after re-reading the board" under all 19 steps, a tic.
  It is now one sentence above the list and a short "Chosen by" per step.
- The drawing's caption claimed "three live paths were walked"; the fixture's `live_paths` query returned one row.
  The caption now reads its numbers from that query (1 path, 3 anomalies).
- The anomaly subtext in the drawing was truncated mid-word; it now says "2 min after the change", computed.
- Mobile overrides used `1fr` and let `<pre>` push the page past 390 px; every grid track is `minmax(0, 1fr)`.
- The wordmark and "Ask the brain" wrapped at 390; the masthead stacks into two rows there and links never wrap.
- "she made it" assumed a pronoun the data does not give; now "who made the pool change".
- Deliberately not done: no cards, no rounded corners, no shadows, no caps labels, no middle dots, no arrows on
  buttons, no fake Slack chrome around the update (it is a ruled block with the comms agent's lines).
- Still debatable: the inbox at 390 takes the first screen before the page; a real build would collapse the
  "not worked yet" group behind its count.
