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
Company brain corpus (_corpus): docs (postmortems, design notes, decisions, runbook pages), tickets and chat, each
linked to the services, changes, people and incidents it talks about, with a few planted facts to ask about: why the
payments-gw pool was lowered, who designed the checkout retries, why legacy-billing left the checkout path, the
postgres-orders connection limit debate, a general rollback runbook page for services with none. Also kept outside the
act windows.
All names are fake. All times are epoch seconds.
"""

import random
from collections.abc import Callable
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
        "runbooks", "incidents", "tickets", "messages", "docs")}

    # --- org: teams, people, services, dependencies -------------------------------------------------
    names = rng.sample([f"{f} {last}" for f in FIRST for last in LAST], 24)
    # One person per first name, so the UI never shows two "Chidi"s. Renaming after the draw keeps the rng stream
    # (and so every later random choice) exactly as it was.
    spare = iter(f for f in FIRST if f not in {n.split()[0] for n in names})
    seen: set[str] = set()
    for i, n in enumerate(names):
        if n.split()[0] in seen:
            names[i] = f"{next(spare)} {n.split()[1]}"
        seen.add(names[i].split()[0])
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
    _corpus(d, team_people, outside_windows)  # last, and without rng: the story and noise above stay as they were
    return d


def _ids(xs: list[str]) -> list[str]:
    return [x if ":" in x else _svc(x) for x in xs]  # bare names are services


def _corpus(d: dict[str, list[dict]], tp: dict[str, list[str]], outside: Callable[[int], bool]) -> None:
    """Docs, tickets and chat for the company brain. Docs mention services, changes and incidents; tickets may also
    mention docs; chat may mention anything (that is the ingest order)."""
    pay, co, plat, sf, ful, dat = (tp[t] for t in ("payments", "checkout", "platform", "storefront", "fulfilment",
                                                   "data"))
    channel = {"storefront": "#storefront", "checkout": "#checkout-eng", "payments": "#payments",
               "fulfilment": "#fulfilment", "platform": "#platform", "data": "#data"}

    def ago(days: float, minutes: int = 0) -> int:
        return T1 - int(days * DAY) + minutes * MIN

    def doc(did, kind, title, author, at, text, mentions, decides=None, supersedes=None):
        d["docs"].append({"id": f"doc:{did}", "kind": kind, "title": title, "author": author, "at": at, "text": text,
                          "mentions": _ids(mentions), "decides": decides and _svc(decides),
                          "supersedes": supersedes and f"doc:{supersedes}"})

    def ticket(key, title, author, at, text, mentions, change=None):
        d["tickets"].append({"id": f"ticket:{key}", "title": f"{key} {title}", "author": author, "at": at,
                             "text": text, "change": change, "mentions": _ids(mentions)})

    def msg(chan, author, at, text, mentions):
        d["messages"].append({"id": f"msg:chat-{len(d['messages']):03d}", "channel": chan, "author": author, "at": at,
                              "text": text, "change": None, "mentions": _ids(mentions)})

    # --- planted: why the payments-gw pool went from 200 to 20 (act 1's cause) -------------------------------
    doc("pm-load-test-pgw", "postmortem", "Postmortem: payments gateway pool exhausted in the peak load test", pay[3],
        ago(210), "In the peak-season load test payments-gw (the payments gateway) ran with a connection pool of "
        "max_connections 50. The pool exhausted within minutes, payments queued behind it and checkout p99 passed 4s. "
        "We raised max_connections to 200. Rule from this postmortem: never run the gateway pool below 150 without a "
        "load test. Action items: alert on pool saturation (PAY-388), write the pool sizing runbook.",
        ["payments-gw", "payments", "checkout"])
    doc("runbook-pgw-pool", "runbook", "Runbook: sizing the payments-gw connection pool", pay[3], ago(200),
        "Keep payments-gw max_connections at 150 or more; below that the pool exhausts at the lunch peak (see the "
        "peak load test postmortem). To change it: load test first, change the config template, then watch pool "
        "saturation and payments p99 for 30 minutes. To revert: restore the previous config template.",
        ["payments-gw", "payments"])
    doc("cost-review-pgw", "design", "Q4 cost review: payments gateway idle connections", pay[1], ago(9),
        "Our payment provider bills per open connection. payments-gw (the payments gateway) keeps a pool of 200 "
        "connections but uses fewer than 20 overnight. Decision: lower the pool max_connections from 200 to 20, which "
        "cuts the gateway bill by about 40%. Requested as CR-881. Known risk: the peak load test postmortem asked for "
        "at least 150 at peak; we accept it and will raise the pool again if payments p99 moves.",
        ["payments-gw", "payments", "chg:pgw-pool-1"], decides="payments-gw")
    # --- planted: who designed the checkout retries (v2 supersedes v1, different authors) ----------------------
    doc("design-retries-v1", "design", "Design: checkout payment retries (v1, fixed interval)", co[3], ago(330),
        "checkout retries a failed payments call 5 times at a fixed 500 ms interval. Simple, but when payments is slow "
        "every checkout request turns into 5 calls.", ["checkout", "payments"], decides="checkout")
    doc("design-retries-v2", "design", "Design: checkout retries with backoff and idempotency keys", co[0], ago(120),
        "Replaces the fixed-interval retries (v1). checkout retries a payments call at most 3 times with exponential "
        "backoff and jitter, inside a retry budget of 10% of requests, so a slow payments service is not hammered. "
        "Every charge carries an idempotency key and payments-gw drops duplicates, so a retried charge is never "
        "captured twice.", ["checkout", "payments", "payments-gw"], decides="checkout", supersedes="design-retries-v1")
    # --- planted: why legacy-billing left the checkout path (the retired DEPENDS_ON edge, T1 - 3 days) ---------
    doc("design-invoicing", "design", "Design: checkout invoices from legacy-billing", pay[2], ago(390),
        "checkout calls legacy-billing synchronously to render an invoice for every order; legacy-billing reads order "
        "totals from postgres-orders.", ["checkout", "legacy-billing", "postgres-orders"], decides="legacy-billing")
    doc("adr-012", "decision", "ADR-012: Retire legacy-billing from the checkout path", pay[0], ago(3, -180),
        "Status: accepted. Decision: checkout stops calling legacy-billing; payments renders invoices instead. Why: "
        "legacy-billing returned 5xx on /invoice every week, added 300 ms to each checkout and has had no owner since "
        "the billing team merged into payments. Consequence: from today checkout no longer depends on legacy-billing, "
        "so a legacy-billing deploy cannot slow checkout. legacy-billing keeps running for old subscription invoices "
        "until Q1. Work tracked in PAY-412.", ["legacy-billing", "checkout", "payments"], decides="legacy-billing",
        supersedes="design-invoicing")
    # --- planted: the postgres-orders connection limit debate (act 3's cause) ----------------------------------
    doc("pm-pg-failover", "postmortem", "Postmortem: postgres-orders connection storm after failover", plat[0],
        ago(160), "After a failover every client reconnected at once and postgres-orders hit its connection limit "
        "(max_connections 300). payments and refunds timed out for 12 minutes. We raised the limit to 500. Action "
        "item: put PgBouncer in front of the primary (PLAT-233) so the limit can come down safely later.",
        ["postgres-orders", "payments", "refunds"])
    doc("adr-014", "decision", "ADR-014: PgBouncer in front of postgres-orders", plat[0], ago(150),
        "Status: accepted, not started. Decision: every service reaches postgres-orders through PgBouncer in "
        "transaction mode, so the server-side connection limit can drop from 500 to 150 without starving callers. "
        "Until then payments, refunds and inventory each need up to 60 server connections at peak. Tracked in "
        "PLAT-233.", ["postgres-orders", "payments", "refunds", "inventory"], decides="postgres-orders")
    doc("pg-conn-budget", "design", "Design note: postgres-orders memory and connection limit", plat[1], ago(2),
        "Each postgres-orders connection costs about 10 MB, so 500 connections leave too little memory for the buffer "
        "cache and the primary swaps under load. Proposal: lower max_connections from 500 to 150 (CR-917). Risk "
        "raised in #platform: payments, refunds and inventory open up to 60 connections each at peak, so 150 is tight "
        "until PgBouncer (PLAT-233, ADR-014) lands.",
        ["postgres-orders", "payments", "refunds", "inventory", "chg:pg-conn-3"])
    # --- the rest of the company's paperwork ---------------------------------------------------------------
    doc("adr-006", "decision", "ADR-006: Kafka retention of 3 days", plat[2], ago(300),
        "Status: superseded. Keep 3 days of events on kafka; consumers that fall further behind re-read from "
        "postgres-orders.", ["kafka", "analytics"], decides="kafka")
    doc("adr-011", "decision", "ADR-011: Kafka retention of 7 days", plat[3], ago(90),
        "Status: accepted. analytics needs a week of events to replay after the reporting backfill; 3 days was not "
        "enough. Storage cost +30% accepted.", ["kafka", "analytics", "reporting"], decides="kafka",
        supersedes="adr-006")
    doc("adr-004", "decision", "ADR-004: api-gateway rate limits per client IP", plat[2], ago(350),
        "Status: superseded. api-gateway limits every client IP to 300 requests per minute.", ["api-gateway"],
        decides="api-gateway")
    doc("adr-013", "decision", "ADR-013: api-gateway rate limits per API key", plat[3], ago(60),
        "Status: accepted. Per-IP limits throttled mobile users behind carrier NAT. Limits are now per API key: 600 "
        "requests per minute for mobile-bff and 1200 for web-frontend.", ["api-gateway", "mobile-bff", "web-frontend"],
        decides="api-gateway", supersedes="adr-004")
    doc("design-search-cache", "design", "Design: search results cache in redis-cache", sf[0], ago(100),
        "search caches result pages in redis-cache for 5 minutes. A new ranking model changes every result, so each "
        "search deploy flushes the cache: expect a cache miss spike right after a deploy. It is harmless unless "
        "redis-cache itself is saturated.", ["search", "redis-cache"], decides="search")
    doc("design-fraud-rules", "design", "Design: fraud-check rules engine", pay[0], ago(140),
        "fraud-check scores each payment against rules cached in redis-cache within a 50 ms budget; on timeout "
        "payments lets the charge through and flags it for review.", ["fraud-check", "payments", "redis-cache"],
        decides="fraud-check")
    doc("design-refunds", "design", "Design: idempotent refunds", pay[3], ago(110),
        "refunds writes a refund intent to postgres-orders before calling payments, so a retried refund never pays "
        "out twice.", ["refunds", "payments", "postgres-orders"], decides="refunds")
    doc("design-subs-cycles", "design", "Design: subscription billing cycles (v8)", pay[0], ago(12),
        "Renewals move from a nightly batch to per-subscription billing cycles. The renewal job retries a failed "
        "charge 3 times, so a short blip in subscriptions right after a deploy is expected and self-heals.",
        ["subscriptions", "payments"], decides="subscriptions")
    doc("design-promotions", "design", "Design: promotion stacking rules", co[1], ago(80),
        "pricing asks promotions for every cart line; at most one percentage and one fixed discount stack.",
        ["promotions", "pricing", "cart"], decides="promotions")
    doc("design-warehouse-sync", "design", "Design: warehouse-sync nightly batch window", ful[0], ago(70),
        "warehouse-sync reconciles stock with the warehouses in one batch at 02:00 UTC, off the checkout peak; "
        "inventory serves cached stock while it runs.", ["warehouse-sync", "inventory"], decides="warehouse-sync")
    doc("design-shipping-notify", "design", "Design: shipping notifications through kafka", ful[1], ago(95),
        "shipping publishes status changes to kafka; notifications consumes them and sends email and push. A slow "
        "notifications service delays messages but never blocks shipping.", ["shipping", "notifications", "kafka"],
        decides="shipping")
    doc("design-reporting-replica", "design", "Design: reporting reads from a replica", dat[0], ago(130),
        "reporting moved its nightly queries off the postgres-orders primary to a read replica after the nightly "
        "reports slowed checkout writes. analytics still reads from kafka.",
        ["reporting", "postgres-orders", "analytics"], decides="reporting")
    doc("runbook-auth-keys", "runbook", "Runbook: rotating auth signing keys", plat[3], ago(75),
        "Publish the new key to auth, wait for api-gateway to pick it up (5 minutes), then retire the old key. Never "
        "retire first: every session fails.", ["auth", "api-gateway"])
    doc("runbook-kafka-lag", "runbook", "Runbook: kafka consumer lag", plat[2], ago(85),
        "Check which consumer group lags (notifications, analytics). Scale the consumer, not the brokers; with 7 days "
        "of retention there is time to catch up.", ["kafka", "notifications", "analytics"])
    doc("runbook-redis-failover", "runbook", "Runbook: redis-cache failover", plat[0], ago(65),
        "Promote the replica and flush nothing: search, cart, pricing and fraud-check rebuild their keys on demand. "
        "Expect a cache miss spike for 10 minutes.", ["redis-cache", "search", "cart", "pricing", "fraud-check"])
    doc("runbook-checkout-latency", "runbook", "Runbook: checkout p99 latency triage", co[0], ago(50),
        "Start from the dependency graph, not from the newest deploy: checkout calls cart, pricing, payments, "
        "inventory and auth, and payments calls payments-gw and postgres-orders. Find the deepest service that went "
        "red first; a saturated payments-gw or postgres-orders pool shows up as checkout latency.",
        ["checkout", "cart", "pricing", "payments", "inventory", "auth", "payments-gw", "postgres-orders"])
    doc("runbook-inventory-cache", "runbook", "Runbook: warming the inventory cache", ful[2], ago(58),
        "After an inventory rollback, warm the cache from the warehouse-sync snapshot before reopening traffic; a cold "
        "cache kept checkout slow during the flash sale (inc:0911).", ["inventory", "warehouse-sync", "inc:0911"])
    # Mentions no service on purpose: ask offers it for any service that has no runbook of its own.
    doc("runbook-rollback", "runbook", "Runbook: rolling back a bad deploy", plat[0], ago(40),
        "For any service without a runbook of its own. Find the change first: the newest deploy or config change on "
        "the service or on anything it depends on, not the newest deploy anywhere. Roll back a bad deploy by "
        "redeploying the previous version from the pipeline; revert a config change by restoring the previous config "
        "template. Then watch p99 and errors for 15 minutes and say in #incidents what you rolled back.", [])
    # A postmortem and an #incidents wrap-up per past incident, written by whoever was paged.
    names = {p["id"]: p["name"] for p in d["people"]}
    changes = {c["id"]: c for c in d["changes"]}
    runbooks = {r["id"]: r for r in d["runbooks"]}
    for inc in d["incidents"]:
        c, rb = changes[inc["cause"]], runbooks[inc["runbook"]]
        culprit = c["service"].removeprefix("svc:")
        doc("pm-" + inc["id"].removeprefix("inc:"), "postmortem", f"Postmortem: {inc['title']}", inc["paged"],
            inc["resolved_at"] + 2 * DAY, f"{inc['service'].removeprefix('svc:')} {inc['symptom']} for two hours. "
            f"Root cause: a {c['kind']} on {culprit} ({c['id']}). {names[inc['paged']]} was paged for {culprit} and "
            f"fixed it with '{rb['title']}': {'; '.join(rb['steps'])}.",
            [inc["id"], inc["service"], c["service"], c["id"]])
        msg("#incidents", inc["paged"], inc["resolved_at"], f"{inc['id']} resolved: {inc['title']}. Cause: {c['kind']} "
            f"on {culprit} ({c['id']}); fixed with '{rb['title']}'.", [inc["id"], c["id"], c["service"]])

    ticket("PAY-388", "Alert on payments-gw pool saturation", pay[3], ago(205),
           "Action item from the peak load test postmortem: page payments before the gateway pool saturates. "
           "Status: open.", ["payments-gw", "doc:pm-load-test-pgw"])
    ticket("PAY-412", "Remove checkout calls to legacy-billing", co[1], ago(6),
           "Per ADR-012: checkout gets invoices from payments; delete the legacy-billing client. Status: done.",
           ["checkout", "legacy-billing", "doc:adr-012"])
    ticket("PLAT-233", "Put PgBouncer in front of postgres-orders", plat[0], ago(158),
           "Action item from the failover postmortem, decided in ADR-014. Status: open, not started.",
           ["postgres-orders", "doc:adr-014", "doc:pm-pg-failover"])
    ticket("CHK-301", "Checkout retries v2: backoff, jitter, idempotency keys", co[0], ago(118),
           "Implements the checkout retries v2 design. Status: done.", ["checkout", "payments-gw",
                                                                        "doc:design-retries-v2"])
    ticket("DATA-77", "Move reporting to the read replica", dat[0], ago(128), "Status: done.",
           ["reporting", "postgres-orders", "doc:design-reporting-replica"])
    ticket("PLAT-198", "Per-API-key rate limits on api-gateway", plat[3], ago(62), "Implements ADR-013. Status: done.",
           ["api-gateway", "mobile-bff", "doc:adr-013"])
    ticket("PLAT-240", "Raise kafka retention to 7 days", plat[3], ago(88), "Implements ADR-011. Status: done.",
           ["kafka", "doc:adr-011"])
    ticket("FUL-54", "Move the warehouse-sync batch to 02:00 UTC", ful[0], ago(69), "Status: done.",
           ["warehouse-sync", "inventory", "doc:design-warehouse-sync"])
    ticket("STO-140", "Flush the search cache on ranking model changes", sf[1], ago(99), "Status: done.",
           ["search", "redis-cache", "doc:design-search-cache"])
    ticket("PAY-430", "Subscription billing cycles (v8)", pay[0], ago(11), "Status: done.",
           ["subscriptions", "doc:design-subs-cycles"])

    for chan, author, at, text, mentions in [
        ("#payments", pay[1], ago(8), "Cost review: payments-gw holds 200 connections and uses fewer than 20 "
         "overnight. Proposing we lower the gateway pool to 20 (CR-881); design note is up.",
         ["payments-gw", "doc:cost-review-pgw"]),
        ("#payments", pay[3], ago(8, 20), "The peak load test postmortem says keep the gateway pool at 150 or more. "
         "20 is fine at night, not at the lunch peak.", ["payments-gw", "doc:pm-load-test-pgw"]),
        ("#payments", pay[1], ago(8, 35), "Finance wants the saving this quarter. Going with 20; we can raise it "
         "again if payments p99 moves.", ["payments-gw"]),
        ("#payments", pay[0], ago(2), "CR-881 approved in the weekly change review.", ["ticket:CR-881"]),
        ("#payments", pay[3], ago(-1), "Config template 2026.10.18 goes out on the 18th across payments services; it "
         "resets per-service overrides to the template defaults.", ["payments-gw", "payments", "ticket:CR-902"]),
        ("#checkout-eng", co[0], ago(121), "Retries v2 design is up: backoff with jitter, 3 attempts, idempotency "
         "keys on every charge. It replaces the fixed 500 ms retries.", ["checkout", "doc:design-retries-v2"]),
        ("#checkout-eng", co[3], ago(120), "+1. The fixed-interval retries from my v1 design hammered payments "
         "during the last slowdown.", ["checkout", "payments", "doc:design-retries-v1"]),
        ("#checkout-eng", co[0], ago(100), "Retries v2 is live on checkout (CHK-301).", ["checkout", "ticket:CHK-301"]),
        ("#payments", pay[0], ago(3, -170), "ADR-012 accepted: checkout stops calling legacy-billing, payments "
         "renders invoices now.", ["legacy-billing", "checkout", "doc:adr-012"]),
        ("#checkout-eng", co[1], ago(3, 120), "checkout no longer calls legacy-billing as of today; PAY-412 is done.",
         ["checkout", "legacy-billing", "ticket:PAY-412"]),
        ("#payments", pay[2], ago(3, 180), "legacy-billing keeps running for old subscription invoices until Q1; its "
         "deploys no longer touch checkout.", ["legacy-billing"]),
        ("#platform", plat[1], ago(2, 10), "Design note for postgres-orders is up: each connection costs ~10 MB and "
         "the primary swaps under load. Proposing max_connections 500 -> 150.",
         ["postgres-orders", "doc:pg-conn-budget"]),
        ("#platform", plat[0], ago(2, 40), "150 is too low for payments, refunds and inventory at peak without "
         "PgBouncer. Can PLAT-233 land first?", ["postgres-orders", "payments", "ticket:PLAT-233"]),
        ("#platform", plat[1], ago(2, 55), "Memory pressure is real; going with 150 under CR-917 and watching "
         "connection slots.", ["postgres-orders", "ticket:CR-917"]),
        ("#payments", pay[2], ago(-1, -300), "FYI for CR-917: payments opens up to 60 connections to postgres-orders "
         "at the lunch peak.", ["payments", "postgres-orders", "ticket:CR-917"]),
        ("#platform", plat[3], ago(60), "api-gateway limits are per API key now (ADR-013); mobile users behind carrier "
         "NAT should stop seeing 429s.", ["api-gateway", "mobile-bff", "doc:adr-013"]),
        ("#platform", plat[2], ago(88), "kafka retention is 7 days as of today (ADR-011).", ["kafka", "doc:adr-011"]),
        ("#storefront", sf[0], ago(20), "search v4.2 ships a new ranking model; expect a cache miss spike right after "
         "the deploy while redis-cache refills.", ["search", "redis-cache", "doc:design-search-cache"]),
        ("#data", dat[0], ago(127), "reporting runs on the read replica now; nightly reports no longer touch the "
         "postgres-orders primary.", ["reporting", "postgres-orders"]),
        ("#fulfilment", ful[0], ago(68), "warehouse-sync batch moved to 02:00 UTC to stay off the checkout peak.",
         ["warehouse-sync", "inventory"]),
        ("#fulfilment", ful[2], ago(59), "Writing up the inventory cache warmup runbook after inc:0911.",
         ["inventory", "inc:0911", "doc:runbook-inventory-cache"]),
    ]:
        msg(chan, author, at, text, mentions)

    # Routine traffic tied to the noise changes: an announcement per eighth change, a ticket per third config change.
    team = {s["id"]: s["team"].removeprefix("team:") for s in d["services"]}
    noise = [c for c in d["changes"] if c["id"].startswith("chg:n") and c["id"][5:].isdigit()]  # not chg:notif-77
    for c in noise[::8]:
        if outside(c["at"] - 2 * MIN):
            msg(channel[team[c["service"]]], c["author"], c["at"] - 2 * MIN,
                f"Rolling now: {c['summary']}. Watching {c['service'].removeprefix('svc:')} dashboards.",
                [c["id"], c["service"]])
    for i, c in enumerate([c for c in noise if c["kind"] == "config"][::3][:8]):
        if outside(c["at"] - DAY):
            svc = c["service"].removeprefix("svc:")
            ticket(f"CR-{700 + i}", f"Tune {svc}", c["author"], c["at"] - DAY,
                   f"Routine tuning of {svc} after the weekly capacity review: worker threads and timeouts.",
                   [c["service"]], change=c["id"])


ACTS = {1: "alert:checkout-latency", 2: "alert:refunds-latency", 3: "alert:subscriptions-latency"}
