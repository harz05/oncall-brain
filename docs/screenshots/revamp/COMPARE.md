# Before and after: the Pager rebuild

Each state at 1440 and 390 (click an image for the full file). Before: `before/` (dark theme, Oct 18 morning). After:
`after/` (Pager direction, see `../../design/RULEBOOK.md`). One line per state is in `before/NOTES.md` and `after/NOTES.md`;
768 shots and full-page (`-full`) shots are in the same folders.

## landing

| | 1440 | 390 |
|---|---|---|
| Before | [![before landing 1440](before/landing-1440.png)](before/landing-1440.png) | [![before landing 390](before/landing-390.png)](before/landing-390.png) |
| After | [![after landing 1440](after/landing-1440.png)](after/landing-1440.png) | [![after landing 390](after/landing-390.png)](after/landing-390.png) |

The dark landing page, with its orange "Simulate" hero and three cards, becomes the Pager page: the open incident sits in an ink readout slab with "Open it and confirm the cause", the next step is a plain sentence plus a quiet button, and how it works is three ruled rows (at 390 the wordmark no longer wraps).

## inbox-with-incidents

| | 1440 | 390 |
|---|---|---|
| Before | [![before inbox-with-incidents 1440](before/inbox-with-incidents-1440.png)](before/inbox-with-incidents-1440.png) | [![before inbox-with-incidents 390](before/inbox-with-incidents-390.png)](before/inbox-with-incidents-390.png) |
| After | [![after inbox-with-incidents 1440](after/inbox-with-incidents-1440.png)](after/inbox-with-incidents-1440.png) | [![after inbox-with-incidents 390](after/inbox-with-incidents-390.png)](after/inbox-with-incidents-390.png) |

The inbox splits into Open and Confirmed with counts, a time and date column and wrapping subtitles ("3 alerts on …, folded into one incident"); the orange "All demo incidents handled. Reset demo company" primary becomes a sentence, and "1 teams" now reads "6 teams".

## simulate-menu

| | 1440 | 390 |
|---|---|---|
| Before | [![before simulate-menu 1440](before/simulate-menu-1440.png)](before/simulate-menu-1440.png) | [![before simulate-menu 390](before/simulate-menu-390.png)](before/simulate-menu-390.png) |
| After | [![after simulate-menu 1440](after/simulate-menu-1440.png)](after/simulate-menu-1440.png) | [![after simulate-menu 390](after/simulate-menu-390.png)](after/simulate-menu-390.png) |

Same three scenarios and custom alert, now a ruled panel (a full-screen sheet at 390) that gives each scenario a plain state ("Ran, not confirmed", why scenario 2 waits) and turns Reset into a quiet text link.

## reset-confirm

| | 1440 | 390 |
|---|---|---|
| Before | no before (new state) | no before (new state) |
| After | [![after reset-confirm 1440](after/reset-confirm-1440.png)](after/reset-confirm-1440.png) | [![after reset-confirm 390](after/reset-confirm-390.png)](after/reset-confirm-390.png) |

New state: Reset now asks in place and says what is deleted, with "Keep it" as the filled, focused default.

## keyboard-focus

| | 1440 | 390 |
|---|---|---|
| Before | no before (new state) | no before (new state) |
| After | [![after keyboard-focus 1440](after/keyboard-focus-1440.png)](after/keyboard-focus-1440.png) | [![after keyboard-focus 390](after/keyboard-focus-390.png)](after/keyboard-focus-390.png) |

New state: tabbing from the top reaches the open incident row, which shows a heavy ink focus outline.

## answer

| | 1440 | 390 |
|---|---|---|
| Before | [![before answer 1440](before/answer-1440.png)](before/answer-1440.png) | [![before answer 390](before/answer-390.png)](before/answer-390.png) |
| After | [![after answer 1440](after/answer-1440.png)](after/answer-1440.png) | [![after answer 390](after/answer-390.png)](after/answer-390.png) |

The boxed cause card, three tiles and evaluation rail become an ink slab (title plus a readout of 40 min / 4 services / 5 suspects / 2 paged) above ruled rows (Cause, Where with the evidence wire, Since, Who, Do this, Ruled out, Sources); the title is the alert name instead of "2 alerts, 1 incident", and Confirm / Wrong cause sit in the tab bar (still sticky at 390).

## wrong-cause

| | 1440 | 390 |
|---|---|---|
| Before | no before (new state) | no before (new state) |
| After | [![after wrong-cause 1440](after/wrong-cause-1440.png)](after/wrong-cause-1440.png) | [![after wrong-cause 390](after/wrong-cause-390.png)](after/wrong-cause-390.png) |

New state: Wrong cause opens a picker of the other four changes with their reason tags, "This one" for each, and a Cancel that saves nothing.

## answer-confirmed

| | 1440 | 390 |
|---|---|---|
| Before | [![before answer-confirmed 1440](before/answer-confirmed-1440.png)](before/answer-confirmed-1440.png) | [![before answer-confirmed 390](before/answer-confirmed-390.png)](before/answer-confirmed-390.png) |
| After | [![after answer-confirmed 1440](after/answer-confirmed-1440.png)](after/answer-confirmed-1440.png) | [![after answer-confirmed 390](after/answer-confirmed-390.png)](after/answer-confirmed-390.png) |

The green "Cause confirmed" card becomes a "Confirmed" label, and Do this now says the fix is saved to memory instead of contradicting the status with "No runbook for this yet".

## answer-storm

| | 1440 | 390 |
|---|---|---|
| Before | [![before answer-storm 1440](before/answer-storm-1440.png)](before/answer-storm-1440.png) | [![before answer-storm 390](before/answer-storm-390.png)](before/answer-storm-390.png) |
| After | [![after answer-storm 1440](after/answer-storm-1440.png)](after/answer-storm-1440.png) | [![after answer-storm 390](after/answer-storm-390.png)](after/answer-storm-390.png) |

The storm keeps its alert name as the title, puts the storm sentence ("fired within 4 minutes and share payments and postgres-orders upstream") and a "21 min from change to first alert" readout in the slab, lists the three alert times under Since, and gives "Also possible: subs-88" its own row; at 390 two readout labels collide.

## why

| | 1440 | 390 |
|---|---|---|
| Before | [![before why 1440](before/why-1440.png)](before/why-1440.png) | [![before why 390](before/why-390.png)](before/why-390.png) |
| After | [![after why 1440](after/why-1440.png)](after/why-1440.png) | [![after why 390](after/why-390.png)](after/why-390.png) |

The dark, dense full-company graph and debug-style step cards become a light graph fitted to the cause path (11 of 25 services) with zoom buttons and a worded legend, next to "How the agents got here", where each step has a question title, who chose it, and why; at 390 the graph shows the whole path instead of a cropped strip.

## why-storm

| | 1440 | 390 |
|---|---|---|
| Before | no before (new state) | no before (new state) |
| After | [![after why-storm 1440](after/why-storm-1440.png)](after/why-storm-1440.png) | [![after why-storm 390](after/why-storm-390.png)](after/why-storm-390.png) |

New state: the storm subgraph, with three red alerting services converging on the pg-conn-3 → postgres-orders → payments path and the ruled-out changes as squares.

## working

| | 1440 | 390 |
|---|---|---|
| Before | [![before working 1440](before/working-1440.png)](before/working-1440.png) | [![before working 390](before/working-390.png)](before/working-390.png) |
| After | [![after working 1440](after/working-1440.png)](after/working-1440.png) | [![after working 390](after/working-390.png)](after/working-390.png) |

The role cards and the "hypothesize_from_memory" line become a slab with the live sentence in plain words and "Skip the replay", then a single ruled done / working / waiting row and labelled skeleton rows; at 390 the roles no longer fill the screen.

## working-why

| | 1440 | 390 |
|---|---|---|
| Before | [![before working-why 1440](before/working-why-1440.png)](before/working-why-1440.png) | [![before working-why 390](before/working-why-390.png)](before/working-why-390.png) |
| After | [![after working-why 1440](after/working-why-1440.png)](after/working-why-1440.png) | [![after working-why 390](after/working-why-390.png)](after/working-why-390.png) |

While the replay streams, the graph now marks the latest step in black and greys out services the agents have not touched, and the step list shows its Cypher behind query/row/ms rows.

## answer-just-confirmed

| | 1440 | 390 |
|---|---|---|
| Before | [![before answer-just-confirmed 1440](before/answer-just-confirmed-1440.png)](before/answer-just-confirmed-1440.png) | [![before answer-just-confirmed 390](before/answer-just-confirmed-390.png)](before/answer-just-confirmed-390.png) |
| After | [![after answer-just-confirmed 1440](after/answer-just-confirmed-1440.png)](after/answer-just-confirmed-1440.png) | [![after answer-just-confirmed 390](after/answer-just-confirmed-390.png)](after/answer-just-confirmed-390.png) |

Bug fixed: offline Confirm used to show a toast over an unchanged card; now the cause flips to "Confirmed, You confirmed this cause" and the row moves to Confirmed in the inbox.

## answer-learned

| | 1440 | 390 |
|---|---|---|
| Before | [![before answer-learned 1440](before/answer-learned-1440.png)](before/answer-learned-1440.png) | [![before answer-learned 390](before/answer-learned-390.png)](before/answer-learned-390.png) |
| After | [![after answer-learned 1440](after/answer-learned-1440.png)](after/answer-learned-1440.png) | [![after answer-learned 390](after/answer-learned-390.png)](after/answer-learned-390.png) |

The "Saved to memory" block appears straight after Confirm, with no re-render trick needed, and now lists the three runbook steps and the culprit it came from.

## answer-memory

| | 1440 | 390 |
|---|---|---|
| Before | no before (new state) | no before (new state) |
| After | [![after answer-memory 1440](after/answer-memory-1440.png)](after/answer-memory-1440.png) | [![after answer-memory 390](after/answer-memory-390.png)](after/answer-memory-390.png) |

New state: act 2 after act 1 was confirmed shows "Solved from memory" with "3 investigator steps instead of 6" and "1 suspect tested instead of 4", measured against the same alert with memory switched off.

## ask-empty

| | 1440 | 390 |
|---|---|---|
| Before | [![before ask-empty 1440](before/ask-empty-1440.png)](before/ask-empty-1440.png) | [![before ask-empty 390](before/ask-empty-390.png)](before/ask-empty-390.png) |
| After | [![after ask-empty 1440](after/ask-empty-1440.png)](after/ask-empty-1440.png) | [![after ask-empty 390](after/ask-empty-390.png)](after/ask-empty-390.png) |

The empty Ask page loses the inert full-company graph (1440) and the empty dark column (390): a heading, an explainer, six example buttons and a labelled question field, with one line saying where the graph will appear.

## ask-answered

| | 1440 | 390 |
|---|---|---|
| Before | [![before ask-answered 1440](before/ask-answered-1440.png)](before/ask-answered-1440.png) | [![before ask-answered 390](before/ask-answered-390.png)](before/ask-answered-390.png) |
| After | [![after ask-answered 1440](after/ask-answered-1440.png)](after/ask-answered-1440.png) | [![after ask-answered 390](after/ask-answered-390.png)](after/ask-answered-390.png) |

The chat bubble and source chips become "You asked:", a large lead sentence (time in IST instead of UTC) and a dated, typed sources list with the superseded decision marked; the 1440 graph is scoped to kafka, its callers and Platform, with zoom buttons.

## ask-answered-graph

| | 1440 | 390 |
|---|---|---|
| Before | no 1440 shot (at 1440 the graph sits beside the answer, see ask-answered) | [![before ask-answered-graph 390](before/ask-answered-graph-390.png)](before/ask-answered-graph-390.png) |
| After | no 1440 shot (at 1440 the graph sits beside the answer, see ask-answered) | [![after ask-answered-graph 390](after/ask-answered-graph-390.png)](after/ask-answered-graph-390.png) |

Bug fixed: on phone "Show on graph" used to render the graph off-screen below the input; now it opens above the answer, scrolls into view, and toggles to "Hide graph".

## connect

| | 1440 | 390 |
|---|---|---|
| Before | [![before connect 1440](before/connect-1440.png)](before/connect-1440.png) | [![before connect 390](before/connect-390.png)](before/connect-390.png) |
| After | [![after connect 1440](after/connect-1440.png)](after/connect-1440.png) | [![after connect 390](after/connect-390.png)](after/connect-390.png) |

Six equal-weight cards become six numbered steps that start with the webhook, under a key/value status list; the curl body is unchanged, and Reset is a quiet link inside step 5.

## error

| | 1440 | 390 |
|---|---|---|
| Before | [![before error 1440](before/error-1440.png)](before/error-1440.png) | [![before error 390](before/error-390.png)](before/error-390.png) |
| After | [![after error 1440](after/error-1440.png)](after/error-1440.png) | [![after error 390](after/error-390.png)](after/error-390.png) |

Bug fixed: the raw API toast that covered the headline, and the misleading "All demo incidents handled" CTA, become an in-place "There is no company called “nope” here." block with "Open the demo company" and the server text behind a disclosure.

## empty

| | 1440 | 390 |
|---|---|---|
| Before | [![before empty 1440](before/empty-1440.png)](before/empty-1440.png) | [![before empty 390](before/empty-390.png)](before/empty-390.png) |
| After | [![after empty 1440](after/empty-1440.png)](after/empty-1440.png) | [![after empty 390](after/empty-390.png)](after/empty-390.png) |

Before was the nope company after its toast faded (disabled CTA, no facts); after is a real empty company (?tenant=uiempty): "No incidents yet." in the rail and "Simulate an incident: checkout is slow" as the one primary action.

## health-down

| | 1440 | 390 |
|---|---|---|
| Before | no before (new state) | no before (new state) |
| After | [![after health-down 1440](after/health-down-1440.png)](after/health-down-1440.png) | [![after health-down 390](after/health-down-390.png)](after/health-down-390.png) |

New state: with FalkorDB unreachable the page explains it in place ("start FalkorDB with make db"), offers "Open the replay", disables Simulate and turns the footer status red.
