# Three directions, one pick (Oct 18)

Three designers each built a static mock from the recorded run in `web/fixtures` (real data, no invented numbers), at
1440 and 390 px. Their plans are next to the screenshots (`<direction>-PLAN.md`).

| Direction | The one idea | Verdict |
|---|---|---|
| **Pager** (picked) | The incident opens as the ink-black alert readout you were woken by; dispatch rows answer it in order (Cause, Where, Since, Who, Do this, Ruled out, Sources); one red for what is broken now. | Strongest contrast and the clearest blocks, which is what the brief asked for ("not plain: contrast, blocks"). The Since timeline makes the causal story readable in two seconds. Condensed numerals carry the on-call voice without decoration. |
| Runbook | A printed incident sheet: ruled verdict box, numbered procedure, a stamp when you confirm. | The calmest and most readable, but a serif document reads as a report, not a tool you act on at 3 AM. Its confirm-stamp moment is grafted into Pager (the Firing block turns into an ink Confirmed block). |
| Blueprint | The service graph as a wiring schematic; the evidence path is the one red wire. | The evidence wire is the best single explanation of "why this change" and is grafted into Pager's Where row. As a whole page it drifts toward a generic light SaaS look. |

The rulebook that the build follows is `docs/design/RULEBOOK.md`.
