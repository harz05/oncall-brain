# Choosing the design direction

Before rebuilding the UI, I explored three directions as static mocks, each built from a real recorded run in
`web/fixtures` so no number on screen is made up, and each checked at desktop (1440 px) and phone (390 px) width. The
plan behind each mock sits next to its screenshots (`<direction>-PLAN.md`).

| Direction | The idea | What I decided |
|---|---|---|
| **Pager** (chosen) | The incident opens as the ink-black alert readout you were woken by, and ruled rows answer it in the order an on-call engineer needs: cause, where, since, who, do this, ruled out, sources. One red is reserved for what is broken right now. | I chose this one. It has the strongest contrast and the clearest structure, the "since" timeline makes the causal story readable in two seconds, and the condensed numerals give it an on-call feel without decoration. |
| Runbook | A printed incident sheet: a ruled verdict box, a numbered procedure, and a stamp when you confirm. | The calmest and most readable, but a serif document reads like a report, not a tool you act on at 3 am. I kept its best moment: confirming turns the red Firing block into an ink Confirmed block. |
| Blueprint | The service graph as a wiring schematic, with the evidence path as the one red wire. | The evidence wire is the clearest single explanation of "why this change", so I brought it into Pager's Where row. As a whole page it drifted toward a generic light SaaS look. |

The rules the final build follows (colours, type, layout, motion and what is banned) are in `docs/design/RULEBOOK.md`.
