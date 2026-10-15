"""Randomised incidents for the eval harness: datagen's org, a fresh planted cause and decoys per seed.

Per seed an alerting service is drawn and one true cause is hidden: a change on the alerting service or a
live dependency 1..3 hops down, whose anomaly travels one shortest live dependency path back to the alert.
Decoys each fool a method without the graph, and each is refuted by a different graph fact:
  a  newest change in the window, on a service the alert does not depend on (what a flat change log blames)
  b  a change on a dependency, rolled back before the alert
  c  a change on a dependency off the propagation path, with no anomaly
  d  (about half the seeds) change + anomaly on a service the alert USED to depend on (retired edge)
  e  (about half the seeds) a resolved past incident, same symptom, cause on the path, nothing changed there now
Only d can fool the anomaly-aware baseline (anomaly_pick): a goes red after the truth, b is rolled back, c is quiet.
Background changes and anomalies land outside the window. The agent only ever sees the graph.
"""

import random
import re
from collections import deque
from typing import Any

from oncall_brain.datagen import DAY, EPOCH, HOUR, MIN, T1, generate
from oncall_brain.domain.planner import WINDOW

# Appended to truth, decoy and noise summaries alike, so keyword overlap is not planted in either direction.
FLAVOURS = ["latency fix", "p99 tuning", "error handling", "retry budget", "new ranking model", "UI copy changes",
            "dependency bumps", "logging cleanup", "cache warmup", "5xx alert noise"]
KNOBS = ["pool max_connections", "timeout_ms", "retry budget", "cache TTL", "worker threads"]
ANOMALY_TEXT = {"latency": "p99 above SLO", "errors": "5xx above SLO", "saturation": "connection pool saturated"}


def live_adjacency(depends_on: list[dict], at: int) -> dict[str, list[str]]:
    """caller -> callees, using only DEPENDS_ON edges valid at `at` (same rule as the Cypher queries)."""
    adj: dict[str, list[str]] = {}
    for e in depends_on:
        if e["valid_from"] <= at and (e["valid_to"] is None or e["valid_to"] > at):
            adj.setdefault(e["src"], []).append(e["dst"])
    return adj


def hops_from(adj: dict[str, list[str]], origin: str) -> dict[str, int]:
    """Shortest hop count from origin to everything it transitively depends on (origin itself is 0)."""
    dist, todo = {origin: 0}, deque([origin])
    while todo:
        u = todo.popleft()
        for v in adj.get(u, []):
            if v not in dist:
                dist[v] = dist[u] + 1
                todo.append(v)
    return dist


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def keyword_pick(changes: list[dict], alert: dict) -> dict | None:
    """Text-similarity baseline: the in-window change whose summary shares most words with the alert name,
    ties -> newest. Stands in for search over the change log without the dependency graph."""
    window = [c for c in changes if alert["at"] - WINDOW <= c["at"] <= alert["at"]]
    return max(window, key=lambda c: (len(_words(c["summary"]) & _words(alert["name"])), c["at"]), default=None)


def anomaly_pick(changes: list[dict], anomalies: list[dict], alert: dict) -> dict | None:
    """Anomaly-aware change log, no graph: of the in-window changes not rolled back whose own service shows an
    anomaly between the change and the alert, the one whose service went red first (a cause starts the
    cascade, so it goes red before what it breaks), ties -> newest. The strongest simple non-graph rule we found:
    "newest such change" instead is always fooled by decoy a, which has its own anomaly."""
    def first_red(c: dict) -> int | None:
        return min((x["at"] for x in anomalies if x["service"] == c["service"] and c["at"] <= x["at"] <= alert["at"]),
                   default=None)

    live = [c for c in changes if alert["at"] - WINDOW <= c["at"] <= alert["at"]
            and not (c["rolled_back_at"] and c["rolled_back_at"] <= alert["at"])]
    red = [(t, c) for c in live if (t := first_red(c)) is not None]
    return min(red, key=lambda tc: (tc[0], -tc[1]["at"]), default=(None, None))[1]


def scenario(seed: int) -> dict[str, Any]:
    """{data (datagen.generate() shape), alert_id, truth_change, baseline_change, truth_path, decoys}."""
    rng = random.Random(seed)
    data = generate(seed)
    for key in ("changes", "alerts", "anomalies", "tickets", "messages", "incidents", "runbooks"):
        data[key] = []
    at = T1
    ids = iter(rng.sample(range(100, 1000), 400))  # unique, meaningless suffixes: ids must not leak the truth
    team_of = {s["id"]: s["team"] for s in data["services"]}
    members: dict[str, list[str]] = {}
    for p in data["people"]:
        members.setdefault(p["team"], []).append(p["id"])

    def name(svc: str) -> str:
        return svc.removeprefix("svc:")

    def change(svc: str, t: int, rolled_back_at: int | None = None) -> str:
        kind = rng.choice(["deploy", "deploy", "config"])
        ver = f"{rng.randint(1, 9)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}"
        summary = (f"Deploy {name(svc)} v{ver}" if kind == "deploy" else
                   f"Set {name(svc)} {rng.choice(KNOBS)} {rng.randint(10, 500)} -> {rng.randint(10, 500)}")
        if rng.random() < 0.5:
            summary += f" ({rng.choice(FLAVOURS)})"
        cid = f"chg:{name(svc)}-{next(ids)}"
        data["changes"].append({"id": cid, "kind": kind, "service": svc, "at": t, "summary": summary,
                                "author": rng.choice(members[team_of[svc]]), "rolled_back_at": rolled_back_at,
                                "version": ver if kind == "deploy" else None})
        return cid

    def anomaly(svc: str, t: int, kind: str) -> None:
        data["anomalies"].append({"id": f"anom:{name(svc)}-{next(ids)}", "service": svc, "at": t, "kind": kind,
                                  "summary": ANOMALY_TEXT[kind]})

    # --- the alert ----------------------------------------------------------------------------------
    adj = live_adjacency(data["depends_on"], at)
    origin = rng.choice(sorted(adj))
    dist = hops_from(adj, origin)
    closure = set(dist)
    symptom = rng.choice(["latency", "errors"])
    alert = {"id": f"alert:{name(origin)}-{symptom}", "service": origin, "at": at, "act": None,
             "symptom": symptom, "name": f"{name(origin)} " + ("p99 latency above 2s" if symptom == "latency"
                                                              else "5xx error rate above 2%")}
    data["alerts"].append(alert)

    # --- the truth: a change whose anomaly walks one shortest live path back to the alert ---------------
    cause = rng.choice(sorted(s for s, h in dist.items() if h <= 3))
    path = [cause]  # cause -> ... -> origin
    while path[-1] != origin:
        cur = path[-1]
        path.append(rng.choice(sorted(u for u, vs in adj.items() if cur in vs and dist.get(u) == dist[cur] - 1)))
    t = at - rng.randint(20, 110) * MIN  # <= 4 services x <= 4 min of propagation still lands before the alert
    truth = change(cause, t)
    for i, svc in enumerate(path):
        t += rng.randint(1, 4) * MIN
        anomaly(svc, t, rng.choice(["saturation", symptom]) if i == 0 else symptom)

    # --- decoys ---------------------------------------------------------------------------------------
    decoys: dict[str, str] = {}
    off = sorted(set(team_of) - closure)
    a_svc = rng.choice(off)
    t = at - rng.randint(1, 10) * MIN  # every other in-window change is >= 12 min old: this one is the newest
    decoys["a"] = change(a_svc, t)
    anomaly(a_svc, t + MIN, "errors")
    if others := sorted(closure - {cause}):
        t = at - rng.randint(60, 115) * MIN
        decoys["b"] = change(rng.choice(others), t, rolled_back_at=t + rng.randint(10, 40) * MIN)
    if healthy := sorted(closure - set(path)):
        decoys["c"] = change(rng.choice(healthy), at - rng.randint(12, 110) * MIN)
    linked = {e["dst"] for e in data["depends_on"] if e["src"] == origin}
    if (retired := sorted(set(off) - {a_svc} - linked)) and rng.random() < 0.5:
        svc = rng.choice(retired)
        data["depends_on"].append({"src": origin, "dst": svc, "valid_from": EPOCH,
                                   "valid_to": at - rng.randint(1, 10) * DAY})
        t = at - rng.randint(12, 110) * MIN
        decoys["d"] = change(svc, t)
        anomaly(svc, t + rng.randint(1, 5) * MIN, symptom)
    changed_now = {c["service"] for c in data["changes"]}  # only in-window changes exist so far
    if (quiet := sorted(closure - changed_now)) and rng.random() < 0.5:
        svc = rng.choice(quiet)
        past = at - rng.randint(10, 60) * DAY
        cid = change(svc, past - 30 * MIN)
        kind = data["changes"][-1]["kind"]
        rb = f"rb:{name(svc)}:{kind}"
        data["runbooks"].append({"id": rb, "title": f"Roll back the last {kind} on {name(svc)}",
                                 "steps": [f"Roll back the last {kind} on {name(svc)}", f"Watch {name(origin)}"],
                                 "service": svc, "kind": kind, "uses": 1, "successes": 1})
        decoys["e"] = f"inc:past-{next(ids)}"
        data["incidents"].append({"id": decoys["e"], "title": f"{name(origin)} {symptom} spike", "service": origin,
                                  "symptom": symptom, "opened_at": past, "resolved_at": past + 2 * HOUR,
                                  "status": "resolved", "cause": cid, "runbook": rb})

    # --- noise: routine changes and blips, never inside the window ------------------------------------
    def quiet_time() -> int:
        while True:
            t = at - 14 * DAY + rng.randint(0, 17 * DAY)
            if not at - WINDOW - HOUR <= t <= at + HOUR:
                return t

    services = sorted(team_of)
    for _ in range(60):
        change(rng.choice(services), quiet_time())
    for _ in range(25):
        anomaly(rng.choice(services), quiet_time(), rng.choice(list(ANOMALY_TEXT)))

    return {"data": data, "alert_id": alert["id"], "truth_change": truth, "baseline_change": decoys["a"],
            "truth_path": path[::-1], "decoys": decoys}
