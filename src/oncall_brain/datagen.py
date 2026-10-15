"""Seeded synthetic company for the demo: the planted two-act story plus random noise.

The story (fixed, hand-written so the demo is repeatable):
  Act 1 at T1: "checkout p99 latency" fires. Real cause: a config change on payments-gw (pool 200 -> 20),
  two hops upstream (checkout -> payments -> payments-gw). Decoys, each refuted by a different graph fact:
    - search deploy 8 min before:   most recent change anywhere (what a flat change log blames), no path
    - legacy-billing deploy:        checkout used to depend on it, edge retired 3 days ago. It also went red
                                    first, so a change log that watches anomalies (no graph) blames it
    - pricing deploy:               on the path, but rolled back before the alert
    - cart deploy:                  on the path, but cart shows no anomaly
  Act 2 at T2 = T1 + 3 days: "refunds p99 latency". Same upstream (refunds -> payments -> payments-gw),
  same kind of change. A newer deploy on payments (1 hop, healthy) is what nearest-first checking tries
  first; with act 1 resolved, memory skips it and solves the incident in one check.
  Act 3 at T3 = T1 + 5 days: an alert storm. checkout, refunds and subscriptions alert within 4 minutes.
  Real cause: a config change on postgres-orders, which all three reach through payments. A deploy on
  subscriptions half an hour earlier (and a blip right after it) looks guilty from subscriptions' point of view
  alone, and it went red first; but it explains only one of the three alerts. Correlating the alerts over the
  dependency graph keeps the postgres-orders change, which explains all three.
Noise (random, seeded): extra people, changes, anomalies and past incidents, kept outside both act windows.
All names are fake. All times are epoch seconds.
"""

import random
from datetime import UTC, datetime

from oncall_brain.domain.planner import WINDOW

MIN, HOUR, DAY = 60, 3600, 86400
T1 = int(datetime(2026, 10, 15, 4, 0, tzinfo=UTC).timestamp())  # 09:30 IST
T2 = T1 + 3 * DAY
T3 = T1 + 5 * DAY
EPOCH = T1 - 400 * DAY  # when the "company" started; most dependencies are valid from here

TEAMS = {
    "storefront": ("Storefront", ["web-frontend", "mobile-bff", "search", "recommendations"]),
    "checkout": ("Checkout", ["checkout", "cart", "pricing", "promotions"]),
    "payments": ("Payments", ["payments", "payments-gw", "refunds", "fraud-check", "legacy-billing",
                              "subscriptions"]),
    "fulfilment": ("Fulfilment", ["inventory", "shipping", "warehouse-sync"]),
    "platform": ("Platform", ["api-gateway", "auth", "postgres-orders", "kafka", "redis-cache",
                              "notifications"]),
    "data": ("Data", ["analytics", "reporting"]),
}
TIER1 = {"web-frontend", "mobile-bff", "api-gateway", "auth", "checkout", "cart", "payments", "payments-gw",
         "postgres-orders", "kafka"}

DEPS = [  # (caller, callee): caller DEPENDS_ON callee
    ("web-frontend", "api-gateway"), ("mobile-bff", "api-gateway"),
    ("api-gateway", "auth"), ("api-gateway", "search"), ("api-gateway", "checkout"), ("api-gateway", "cart"),
    ("api-gateway", "recommendations"), ("api-gateway", "refunds"), ("api-gateway", "subscriptions"),
    ("search", "redis-cache"), ("recommendations", "analytics"), ("recommendations", "redis-cache"),
    ("checkout", "cart"), ("checkout", "pricing"), ("checkout", "payments"), ("checkout", "inventory"),
    ("checkout", "auth"), ("cart", "redis-cache"), ("cart", "pricing"), ("pricing", "promotions"),
    ("pricing", "redis-cache"), ("payments", "payments-gw"), ("payments", "fraud-check"),
    ("payments", "postgres-orders"), ("payments-gw", "kafka"), ("refunds", "payments"),
    ("refunds", "postgres-orders"), ("subscriptions", "payments"), ("inventory", "postgres-orders"),
    ("inventory", "warehouse-sync"), ("shipping", "inventory"), ("shipping", "notifications"),
    ("notifications", "kafka"), ("analytics", "kafka"), ("reporting", "analytics"),
    ("reporting", "postgres-orders"), ("fraud-check", "redis-cache"), ("legacy-billing", "postgres-orders"),
]
RETIRED_DEPS = [("checkout", "legacy-billing", EPOCH, T1 - 3 * DAY)]  # (caller, callee, valid_from, valid_to)

FIRST = ["Asha", "Bram", "Chidi", "Dana", "Elio", "Farah", "Goran", "Hana", "Ivo", "Jae", "Kiri", "Lena",
         "Milo", "Nia", "Omar", "Pia", "Quinn", "Ravi", "Sana", "Tomas", "Uma", "Vik", "Wren", "Yara"]
LAST = ["Okafor", "Lindqvist", "Moreau", "Tanaka", "Silva", "Novak", "Haddad", "Kowalski", "Mensah",
        "Iyer", "Brandt", "Costa", "Varga", "Nakamura", "Petrov", "Quispe"]


def _svc(name: str) -> str:
    return f"svc:{name}"


def generate(seed: int = 7) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    d: dict[str, list[dict]] = {k: [] for k in (
        "teams", "people", "services", "depends_on", "on_call", "changes", "alerts", "anomalies",
        "runbooks", "incidents", "tickets", "messages")}

    # --- org: teams, people, services, dependencies -------------------------------------------------
    names = rng.sample([f"{f} {last}" for f in FIRST for last in LAST], 24)
    team_people: dict[str, list[str]] = {}
    for i, (tid, (tname, services)) in enumerate(TEAMS.items()):
        d["teams"].append({"id": f"team:{tid}", "name": tname})
        members = names[i * 4:(i + 1) * 4]
        team_people[tid] = []
        for n in members:
            pid = "person:" + n.lower().replace(" ", "-")
            team_people[tid].append(pid)
            d["people"].append({"id": pid, "name": n, "handle": "@" + n.lower().replace(" ", "."),
                                "team": f"team:{tid}"})
        for s in services:
            d["services"].append({"id": _svc(s), "name": s, "tier": 1 if s in TIER1 else 2,
                                  "team": f"team:{tid}"})
    for a, b in DEPS:
        d["depends_on"].append({"src": _svc(a), "dst": _svc(b), "valid_from": EPOCH, "valid_to": None})
    for a, b, vf, vt in RETIRED_DEPS:
        d["depends_on"].append({"src": _svc(a), "dst": _svc(b), "valid_from": vf, "valid_to": vt})

    # Weekly on-call rotation per team, covering both acts.
    week0 = T1 - 14 * DAY
    for tid, people in team_people.items():
        for w in range(4):
            d["on_call"].append({"person": people[(w + len(tid)) % len(people)], "team": f"team:{tid}",
                                 "start": week0 + w * 7 * DAY, "end": week0 + (w + 1) * 7 * DAY})

    pay = team_people["payments"]

    def change(cid, kind, svc, at, summary, author, rolled_back_at=None, version=None):
        d["changes"].append({"id": cid, "kind": kind, "service": _svc(svc), "at": at, "summary": summary,
                             "author": author, "rolled_back_at": rolled_back_at, "version": version})

    def anomaly(aid, svc, at, kind, summary):
        d["anomalies"].append({"id": aid, "service": _svc(svc), "at": at, "kind": kind, "summary": summary})

    # --- act 1 ---------------------------------------------------------------------------------------
    d["alerts"].append({"id": "alert:checkout-latency", "service": _svc("checkout"), "at": T1, "act": 1,
                        "symptom": "latency", "name": "checkout p99 latency above 2s"})
    change("chg:pgw-pool-1", "config", "payments-gw", T1 - 40 * MIN,
           "Lower payments-gw HTTP pool max_connections 200 -> 20 (cost cleanup)", pay[1])
    change("chg:search-420", "deploy", "search", T1 - 8 * MIN, "Deploy search v4.2.0 (new ranking model)",
           team_people["storefront"][0], version="4.2.0")
    change("chg:legacy-193", "deploy", "legacy-billing", T1 - 50 * MIN, "Deploy legacy-billing v1.9.3",
           pay[2], version="1.9.3")
    change("chg:pricing-2140", "deploy", "pricing", T1 - 95 * MIN, "Deploy pricing v2.14.0",
           team_people["checkout"][1], rolled_back_at=T1 - 70 * MIN, version="2.14.0")
    change("chg:cart-310", "deploy", "cart", T1 - 25 * MIN, "Deploy cart v3.1.0 (UI copy changes)",
           team_people["checkout"][2], version="3.1.0")
    anomaly("anom:pgw-1", "payments-gw", T1 - 38 * MIN, "saturation", "connection pool exhausted, 180 waiters")
    anomaly("anom:pay-1", "payments", T1 - 36 * MIN, "latency", "p99 4.2s calling payments-gw")
    anomaly("anom:checkout-1", "checkout", T1 - 35 * MIN, "latency", "p99 5.1s on POST /checkout")
    anomaly("anom:search-1", "search", T1 - 6 * MIN, "errors", "cache miss rate up after deploy")
    anomaly("anom:legacy-1", "legacy-billing", T1 - 45 * MIN, "errors", "5xx on /invoice")
    d["tickets"].append({"id": "ticket:CR-881", "change": "chg:pgw-pool-1", "author": pay[1], "at": T1 - 2 * DAY,
                         "title": "CR-881 Reduce idle connections on payments-gw",
                         "text": "Cost review: pool is mostly idle overnight. Lower max_connections to 20."})
    d["messages"].append({"id": "msg:pay-deploys-1", "change": "chg:pgw-pool-1", "author": pay[1],
                          "at": T1 - 41 * MIN, "channel": "#payments-deploys",
                          "text": "Rolling CR-881 now: payments-gw pool max_connections 200 -> 20."})

    # --- act 2 ---------------------------------------------------------------------------------------
    d["alerts"].append({"id": "alert:refunds-latency", "service": _svc("refunds"), "at": T2, "act": 2,
                        "symptom": "latency", "name": "refunds p99 latency above 2s"})
    change("chg:pgw-pool-2", "config", "payments-gw", T2 - 30 * MIN,
           "Config rollout 2026.10.18: payments-gw max_connections 200 -> 25 (template default regressed)",
           pay[3])
    change("chg:notif-77", "deploy", "notifications", T2 - 12 * MIN, "Deploy notifications v7.7.0",
           team_people["platform"][2], version="7.7.0")
    change("chg:fraud-512", "deploy", "fraud-check", T2 - 50 * MIN, "Deploy fraud-check v5.1.2", pay[0],
           version="5.1.2")
    change("chg:pay-77", "deploy", "payments", T2 - 20 * MIN, "Deploy payments v7.7.0 (receipt template)", pay[2],
           version="7.7.0")
    anomaly("anom:pgw-2", "payments-gw", T2 - 28 * MIN, "saturation", "connection pool exhausted, 140 waiters")
    anomaly("anom:pay-2", "payments", T2 - 27 * MIN, "latency", "p99 3.8s calling payments-gw")
    anomaly("anom:refunds-2", "refunds", T2 - 25 * MIN, "latency", "p99 4.4s on POST /refunds")
    d["tickets"].append({"id": "ticket:CR-902", "change": "chg:pgw-pool-2", "author": pay[3], "at": T2 - DAY,
                         "title": "CR-902 Roll out config template 2026.10.18",
                         "text": "Quarterly config template rollout across payments services."})

    # --- act 3: alert storm --------------------------------------------------------------------------
    for aid, svc, dt in (("alert:checkout-latency-3", "checkout", 4), ("alert:refunds-latency-3", "refunds", 2),
                         ("alert:subscriptions-latency", "subscriptions", 0)):
        d["alerts"].append({"id": aid, "service": _svc(svc), "at": T3 - dt * MIN, "act": 3, "symptom": "latency",
                            "name": f"{svc} p99 latency above 2s"})
    change("chg:pg-conn-3", "config", "postgres-orders", T3 - 25 * MIN,
           "postgres-orders max_connections 500 -> 150 (memory tuning)", team_people["platform"][1])
    change("chg:subs-88", "deploy", "subscriptions", T3 - 30 * MIN, "Deploy subscriptions v8.8.0 (billing cycles)",
           pay[0], version="8.8.0")
    change("chg:search-430", "deploy", "search", T3 - 3 * MIN, "Deploy search v4.3.0", team_people["storefront"][0],
           version="4.3.0")
    anomaly("anom:subs-blip-3", "subscriptions", T3 - 28 * MIN, "errors", "renewal job retries after deploy")
    anomaly("anom:pg-3", "postgres-orders", T3 - 22 * MIN, "saturation", "connection slots exhausted")
    anomaly("anom:pay-3", "payments", T3 - 20 * MIN, "latency", "p99 3.1s waiting on postgres-orders")
    anomaly("anom:checkout-3", "checkout", T3 - 5 * MIN, "latency", "p99 4.0s on POST /checkout")
    anomaly("anom:refunds-3", "refunds", T3 - 3 * MIN, "latency", "p99 3.6s on POST /refunds")
    anomaly("anom:subs-3", "subscriptions", T3 - 1 * MIN, "latency", "p99 3.9s on renewals")
    d["tickets"].append({"id": "ticket:CR-917", "change": "chg:pg-conn-3", "author": team_people["platform"][1],
                         "at": T3 - DAY, "title": "CR-917 Lower postgres-orders max_connections",
                         "text": "Memory pressure on the primary; cap connections at 150."})

    # --- history: past incidents with runbooks (episodic + procedural memory already on file) ----------
    owner_of = {s: tid for tid, (_, services) in TEAMS.items() for s in services}

    def past(iid, title, origin, symptom, at, cause, cause_kind, cause_svc, rb_id, rb_title, steps):
        change(cause, cause_kind, cause_svc, at - 30 * MIN, f"{cause_kind} on {cause_svc}",
               rng.choice(sum(team_people.values(), [])))
        d["runbooks"].append({"id": rb_id, "title": rb_title, "steps": steps, "service": _svc(cause_svc),
                              "kind": cause_kind, "uses": 1, "successes": 1})
        d["incidents"].append({"id": iid, "title": title, "service": _svc(origin), "symptom": symptom,
                               "opened_at": at, "resolved_at": at + 2 * HOUR, "status": "resolved",
                               "cause": cause, "runbook": rb_id, "paged_for": _svc(cause_svc),
                               "paged": rng.choice(team_people[owner_of[cause_svc]])})

    past("inc:0911", "Checkout slow during flash sale", "checkout", "latency", T1 - 60 * DAY,
         "chg:inv-880", "deploy", "inventory", "rb:inventory-rollback", "Roll back inventory deploy",
         ["Roll back the latest inventory deploy", "Warm the inventory cache", "Watch checkout p99"])
    past("inc:0877", "Refunds failing with 500s", "refunds", "errors", T1 - 45 * DAY,
         "chg:pg-disk", "config", "postgres-orders", "rb:pg-disk", "Expand postgres-orders volume",
         ["Expand the data volume", "Vacuum the refunds table", "Watch refunds error rate"])
    for n in range(5):  # unrelated history
        s = rng.choice([s["name"] for s in d["services"]])
        at = T1 - rng.randint(10, 90) * DAY
        past(f"inc:{1000 + n}", f"{s} degraded", s, rng.choice(["errors", "latency"]), at, f"chg:hist-{n}",
             rng.choice(["deploy", "config"]), s, f"rb:hist-{n}", f"Recover {s}",
             [f"Roll back the last change on {s}", f"Watch {s} health"])

    # --- noise: routine changes and blips, never inside an act window -------------------------------
    def outside_windows(t):
        return not any(t0 - WINDOW - HOUR <= t <= t0 + HOUR for t0 in (T1, T2, T3))

    svc_names = [s["name"] for s in d["services"]]
    owners = {s["name"]: s["team"].split(":")[1] for s in d["services"]}
    n = 0
    while n < 90:
        at = T1 - 14 * DAY + rng.randint(0, 17 * DAY)
        if not outside_windows(at):
            continue
        s = rng.choice(svc_names)
        kind = rng.choice(["deploy", "deploy", "config"])
        ver = f"{rng.randint(1, 9)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}"
        change(f"chg:n{n:03d}", kind, s, at, f"{'Deploy ' + s + ' v' + ver if kind == 'deploy' else 'Tune ' + s}",
               rng.choice(team_people[owners[s]]), version=ver if kind == "deploy" else None)
        n += 1
    n = 0
    while n < 30:
        at = T1 - 14 * DAY + rng.randint(0, 17 * DAY)
        if not outside_windows(at):
            continue
        s = rng.choice(svc_names)
        anomaly(f"anom:n{n:03d}", s, at, rng.choice(["latency", "errors", "saturation"]), "short blip, self-healed")
        n += 1
    return d


ACTS = {1: "alert:checkout-latency", 2: "alert:refunds-latency", 3: "alert:subscriptions-latency"}
