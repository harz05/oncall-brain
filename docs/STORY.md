# The demo story

Three incidents on one synthetic company, in the order `make demo` and the live site run them. Each act is checked by
`make demo` (it exits non-zero if the story breaks) and by the integration tests named below.

**Act 1, 09:30: "checkout p99 latency above 2s".**
- Triage walks `DEPENDS_ON` backwards: checkout, api-gateway, web-frontend and mobile-bff are hurt. It pages whoever is on call for checkout (rotation edges in the graph).
- The investigator recalls past incidents first. An old checkout incident was caused by inventory, but inventory has no change today, so it moves on.
- It lists every change from the last 2 hours on services checkout depends on at alert time, plus the newest changes anywhere (what a flat change log would blame). Each suspect becomes a `Hypothesis` on the incident and is tested against the graph:

| Suspect | Verdict | Graph fact that decided it |
|---|---|---|
| search deploy, 8 min before (the newest change anywhere) | refuted | no `DEPENDS_ON` path from checkout to search |
| legacy-billing deploy | refuted | checkout's dependency on it was retired 3 days ago (`valid_to`) |
| pricing deploy | refuted | rolled back before the alert |
| cart deploy | refuted | cart shows no anomaly after the change |
| **payments-gw config change** (pool 200 -> 20) | **supported** | anomaly propagates payments-gw -> payments -> checkout, two hops |

- Both change logs without the graph get it wrong. The flat one blames the newest change (search). One that also watches anomalies blames legacy-billing: it deployed at 08:40 and threw errors at 08:45, before payments-gw went red. But checkout stopped calling legacy-billing 3 days ago, and only the temporal edge knows that.
- Comms pages the payments team and asks the graph who knows payments-gw best (`who_knows`, recorded as `CONSULTED`). It sends a heads-up to the on-call of the most critical impacted teams nobody paged (`warn_owners`) and writes the status update for #incidents. The update is stored on the incident as a `Message` that `CITES` its sources, and is posted to Slack only when `SLACK_WEBHOOK_URL` is set. From `make demo`:

```text
[checkout p99 latency above 2s] status: cause identified, fix pending
Impact: api-gateway, checkout, mobile-bff, web-frontend
Likely cause: config change on payments-gw by Sana Brandt: "Lower payments-gw HTTP pool max_connections 200 -> 20 (cost cleanup)"
Behind it: CR-881 is part of 'Q4 cost review' (Payments, led by Lena Costa, due 2026-12-31)
Context: Q4 cost review: payments gateway idle connections (design); Postmortem: payments gateway pool exhausted in the peak load test (postmortem)
Ruled out: legacy-193 (dependency retired), search-420 (no dependency path), pricing-2140 (rolled back), cart-310 (no anomaly after it)
Paged: @asha.nakamura (Payments), @ravi.moreau (Checkout)
Heads-up (most relied-on first): @hana.costa (Platform) for api-gateway, @kiri.novak (Storefront) for mobile-bff
Also at risk: refunds, subscriptions
Ask: Sana Brandt (@sana.brandt, Payments) knows payments-gw best
Sources: msg:pay-deploys-1, ticket:CR-881, doc:cost-review-pgw
```

- A human confirms. The incident gets `CAUSED_BY` the change, a `Runbook` is learned for (payments-gw, config), and the update is rewritten as "resolved, cause confirmed". The human's call wins: confirming a different change than the agents picked makes that change the cause.

**Act 2, three days later: "refunds p99 latency above 2s".**
Recall finds act 1 by structure: payments-gw is on refunds' live dependency path and the symptom is the same. Text
similarity plays no part. Act 1's runbook is for config changes on payments-gw, so the investigator tests the new
payments-gw config change first and confirms it in one check. **The same incident replayed without act 1's memory takes
6 investigator calls and finds the culprit on check 2; with the memory it takes 3 calls and check 1** (the UI shows
both, via `?compare=memory`). Without memory, nearest-first checking tries a newer, healthy payments deploy
(`chg:pay-77`, 1 hop away) first. The update adds "Next action: Revert the config change on payments-gw (this runbook
worked 1 of 1 times)". An anomaly-aware change log also gets act 2 right (the payments-gw change is the first to go
red), so act 2 shows memory making the investigation shorter, not beating that baseline.

**Act 3, two days later: three alerts in 4 minutes** (checkout, refunds, subscriptions).
- Triage sees other recent alerts on the board and calls `correlate_alerts` first. It walks each alerting service's upstream over edges live at alert time and notes which services went red. It projects the alerting services and their red upstreams into a scratch graph, and `algo.WCC` says which alerts are one incident: the origin's component is folded in (`CORRELATED_WITH`), chains included, and the other components are separate storms. An alert that only shares a quiet cache is not connected and stays its own incident.
- The services all three reach are the shared upstream, ranked by convergence (fewest total hops from the alerting services first: payments, then postgres-orders, ...) and stored as `SHARED_UPSTREAM {rank, hops}`. The investigator checks suspects there first.
- The postgres-orders config change (max_connections 500 -> 150) is supported on check 1 and explains all 3 alerting services. The subscriptions deploy, 5 minutes before it, is supported too (subscriptions blipped right after it) but explains only subscriptions. `conclude` keeps one leading cause and records the other as outranked: "chg:pg-conn-3 explains every alerting service this change does (1) and 2 more".
- Related alerts need not share one cause: a suspect that explains an alerting service the leader cannot is kept as a co-cause (its team is paged, the update says "Also contributing"), not ruled out (`tests/integration/test_storms.py`).
- Both change logs are wrong here: the flat one blames a search deploy, the anomaly-aware one blames the subscriptions deploy because it went red first. Without correlation, the same planner blames the subscriptions deploy too (`make demo` prints this ablation).

![The alert storm: "3 alerts, 1 incident: subscriptions, refunds and checkout fired within 4 minutes and share payments and postgres-orders upstream"; the postgres-orders config change (Omar Tanaka, 21 min before the first alert) named as the cause, labelled "Very likely" because it explains all 3 alerting services, and the evidence path from the change through postgres-orders and payments to subscriptions](img/storm.png)

The eval in [EVAL.md](EVAL.md) runs 200 generated variants of act 1. The eval has single-alert incidents only. Act 3's
storm is checked by `make demo` and `test_act3_alert_storm_is_correlated_and_only_then_solved`; five more storms (two
independent causes, alerts on one service, a quiet shared cache, memory that explains part of a storm, two changes on
one service) by `tests/integration/test_storms.py`; a cascade victim and a monitoring gap by
`tests/integration/test_causality.py`.
