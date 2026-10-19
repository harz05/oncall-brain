"""Hot-query latency on bigger, hub-heavy dependency graphs.

python -m scripts.bench [--sizes 25,100,300,1000] [--reps 15] [--no-doc]

Each size gets its own tenant (perf_<n>), dropped at the end. 25 is the demo graph (datagen.generate(7): act 1's alert,
act 3's storm); the other sizes come from org(n): a seeded, layered service map (edge -> gateways -> domain -> platform
-> infra) where a few caches, queues and databases take most of the fan-in, with a few retired and not-yet-live
DEPENDS_ON edges and some callbacks against the layering (cycles), plus changes and anomalies in the alert window, an
alert storm, past incidents with runbooks, people, docs, tickets and chat. Every hot query runs N times in its reference
form (queries/reference.cypher: the text before the rewrite) and its shipped form, and both must return the same rows.
Prints the table and writes docs/PERF.md (with GRAPH.PROFILE of the main queries).
"""

import argparse
import platform
import random
import re
import sys
from pathlib import Path

from oncall_brain.adapters.falkordb.queries import all_queries
from oncall_brain.datagen import ACTS, DAY, EPOCH, HOUR, MIN, T1, T3, generate
from oncall_brain.domain.planner import RECALL_MIN_SCORE, WINDOW
from oncall_brain.scenarios import hops_from, live_adjacency
from oncall_brain.services.brain import PER_LABEL, TOP, terms
from oncall_brain.services.seeding import load
from oncall_brain.services.tools import incident_id_for
from oncall_brain.wiring import make_store

DOC = Path(__file__).parents[1] / "docs" / "PERF.md"
AT = T1
LAYERS = (("edge", 3), ("gw", 5), ("dom", 52), ("plat", 25), ("infra", 15))  # % of the services, top to bottom
INFRA = ["redis", "kafka", "postgres", "memcached", "rabbitmq", "mysql", "s3", "elastic"]
WORDS = ["pool", "timeout", "latency", "retry", "cache", "connection", "limit", "deploy", "rollback", "queue", "lag",
         "disk", "memory", "errors", "budget", "config", "failover", "index", "migration", "throttle"]
QUESTION = "why was the postgres connection pool limit lowered"


def org(n: int, seed: int = 1) -> tuple[dict, dict]:
    """A datagen-shaped company with n services, and the inputs the hot queries get (origin, hub, storm, ...)."""
    rng = random.Random(seed)
    d: dict[str, list[dict]] = {k: [] for k in ("teams", "people", "services", "depends_on", "on_call", "changes",
                                                "alerts", "anomalies", "runbooks", "incidents", "tickets",
                                                "messages", "docs")}
    kinds = [k for k, pct in LAYERS for _ in range(n * pct // 100)]
    kinds += ["infra"] * (n - len(kinds))
    first = {k: kinds.index(k) for k, _ in LAYERS}
    sid = [f"svc:{INFRA[i % len(INFRA)] if k == 'infra' else k}-{i}" for i, k in enumerate(kinds)]

    def pick(lo: int, hi: int, k: tuple[int, int], skew: float) -> list[int]:
        """Distinct targets in [lo, hi), Zipf-like: the first ones (the hubs) get most of the fan-in."""
        pool = list(range(lo, hi))
        w = [1 / (1 + j) ** skew for j in range(len(pool))]
        want = min(rng.randint(*k), len(pool))
        out: set[int] = set()
        while len(out) < want:
            out.add(rng.choices(pool, w)[0])
        return sorted(out)

    infra, plat, dom = (first["infra"], n), (first["plat"], first["infra"]), (first["dom"], first["plat"])
    deps: set[tuple[int, int]] = set()
    for i, k in enumerate(kinds):  # a service calls services below it (or later in its own layer)
        if k == "edge":
            targets = pick(first["gw"], first["dom"], (2, 3), 0.5)
        elif k == "gw":
            targets = pick(*dom, (8, 14), 0.3)
        elif k == "dom":
            targets = pick(i + 1, dom[1], (2, 6), 0.6) + pick(*plat, (1, 2), 1.0) + pick(*infra, (1, 3), 1.2)
        elif k == "plat":
            targets = pick(i + 1, plat[1], (1, 3), 0.6) + pick(*infra, (1, 3), 1.2)
        else:
            targets = pick(i + 1, n, (0, 1), 1.5)
        deps |= {(i, j) for j in targets if j != i}
    for _ in range(len(deps) // 50):  # callbacks against the layering: real dependency maps have cycles
        a = rng.randrange(first["dom"] + 1, first["infra"])
        deps.add((a, rng.randrange(first["dom"], a)))
    edges = [{"src": sid[a], "dst": sid[b], "valid_from": EPOCH, "valid_to": None} for a, b in sorted(deps)]
    for e in rng.sample(edges, max(3, len(edges) // 150)):  # a few dependencies retired before the alert
        e["valid_to"] = AT - rng.randint(1, 20) * DAY
    for e in rng.sample([e for e in edges if e["valid_to"] is None], 2):  # and two that only start after it
        e["valid_from"] = AT + DAY
    d["depends_on"] = edges

    teams = max(3, n // 8)
    team_of = {s: f"team:t{i * teams // n}" for i, s in enumerate(sid)}
    members: dict[str, list[str]] = {}
    for t in range(teams):
        d["teams"].append({"id": f"team:t{t}", "name": f"Team {t}"})
        for p in range(4):
            pid = f"person:p{t}-{p}"
            members.setdefault(f"team:t{t}", []).append(pid)
            d["people"].append({"id": pid, "name": f"Person {t}-{p}", "handle": f"@p{t}.{p}", "team": f"team:t{t}"})
        d["on_call"].append({"person": members[f"team:t{t}"][0], "team": f"team:t{t}", "start": AT - 7 * DAY,
                             "end": AT + 7 * DAY})
    d["services"] = [{"id": s, "name": s[4:], "tier": 1 if kinds[i] in ("edge", "gw", "infra") else 2,
                      "team": team_of[s]} for i, s in enumerate(sid)]

    def change(svc: str, at: int, kind: str | None = None, rolled_back_at: int | None = None) -> dict:
        c = {"id": f"chg:b{len(d['changes'])}", "kind": kind or rng.choice(["deploy", "deploy", "config"]),
             "service": svc, "at": at, "summary": f"{rng.choice(WORDS)} change on {svc[4:]}",
             "author": rng.choice(members[team_of[svc]]), "rolled_back_at": rolled_back_at, "version": None}
        d["changes"].append(c)
        return c

    def anomaly(svc: str, at: int) -> None:
        d["anomalies"].append({"id": f"anom:b{len(d['anomalies'])}", "service": svc, "at": at,
                               "kind": rng.choice(["latency", "errors", "saturation"]), "summary": "above SLO"})

    origin = sid[first["dom"]]  # top of the domain layer: called by the gateways, a deep closure below it
    closure = hops_from(live_adjacency(edges, AT), origin)
    window = [change(rng.choice(sid), AT - rng.randint(5, 115) * MIN) for _ in range(10 + n // 25)]
    window += [change(rng.choice(sorted(closure)), AT - rng.randint(5, 115) * MIN) for _ in range(4)]
    window[0]["rolled_back_at"] = window[0]["at"] + 10 * MIN
    for c in window:
        if rng.random() < 0.6:
            anomaly(c["service"], min(AT, c["at"] + rng.randint(1, 5) * MIN))
    for _ in range(n // 20):
        anomaly(rng.choice(sid), AT - rng.randint(1, 119) * MIN)
    for _ in range(2 * n):  # background, outside the window
        change(rng.choice(sid), AT - 3 * HOUR - rng.randint(0, 14 * DAY))
    for _ in range(n):
        anomaly(rng.choice(sid), AT - 3 * HOUR - rng.randint(0, 14 * DAY))

    storm = rng.sample(sid[first["dom"] + 1:first["dom"] + 20], 2)
    d["alerts"] = [{"id": f"alert:{s[4:]}-latency", "service": s, "at": AT - (k and rng.randint(2, 12) * MIN),
                    "act": None, "symptom": "latency", "name": f"{s[4:]} p99 latency above 2s"}
                   for k, s in enumerate([origin, *storm])]

    in_closure = [c for c in window if c["service"] in closure]
    for k in range(max(5, n // 10)):  # past incidents; the first few point memory at a change in today's window
        src = in_closure[k % len(in_closure)] if k < 3 else None
        svc = src["service"] if src else rng.choice(sid)
        kind = src["kind"] if src else rng.choice(["deploy", "config"])
        past = AT - (k + 2) * DAY if k < 3 else AT - rng.randint(5, 90) * DAY - k * MIN  # the recent ones recall first
        cause = change(svc, past - 30 * MIN, kind)
        rb = f"rb:{svc[4:]}:{kind}"
        if rb not in {r["id"] for r in d["runbooks"]}:
            d["runbooks"].append({"id": rb, "title": f"Roll back the last {kind} on {svc[4:]}", "steps": ["roll back"],
                                  "service": svc, "kind": kind, "uses": rng.randint(1, 4), "successes": 1})
        d["incidents"].append({"id": f"inc:b{k}", "title": f"{origin[4:]} slow", "service": origin if k < 3 or
                               rng.random() < 0.3 else rng.choice(sid), "symptom": rng.choice(["latency", "errors"])
                               if k >= 3 else "latency", "opened_at": past, "resolved_at": past + 2 * HOUR,
                               "status": "resolved", "cause": cause["id"], "runbook": rb, "paged_for": svc,
                               "paged": rng.choice(members[team_of[svc]])})

    people = [p["id"] for p in d["people"]]
    for k in range(n):
        svcs = rng.sample(sid, 2)
        text = " ".join(rng.sample(WORDS, 6)) + f" on {svcs[0][4:]}"
        when = AT - rng.randint(3, 300) * DAY
        if k % 2 == 0:
            d["docs"].append({"id": f"doc:b{k}", "kind": rng.choice(["postmortem", "design", "decision", "runbook"]),
                              "title": f"{svcs[0][4:]} {rng.choice(WORDS)}", "author": rng.choice(people), "at": when,
                              "text": text, "mentions": svcs, "decides": svcs[0] if k % 10 == 0 else None,
                              "supersedes": f"doc:b{k - 2}" if k % 14 == 0 and k else None})
        else:
            d["tickets"].append({"id": f"ticket:B-{k}", "title": f"B-{k} {rng.choice(WORDS)} on {svcs[0][4:]}",
                                 "author": rng.choice(people), "at": when, "text": text, "mentions": svcs,
                                 "change": rng.choice(d["changes"])["id"]})
        d["messages"].append({"id": f"msg:b{k}", "channel": f"#{team_of[svcs[0]][5:]}", "author": rng.choice(people),
                              "at": when, "text": text, "change": None, "mentions": svcs})

    callers: dict[str, int] = {}
    for e in edges:
        callers[e["dst"]] = callers.get(e["dst"], 0) + 1
    hub = max(sorted(closure), key=lambda s: callers.get(s, 0))  # the shared database / cache most services reach
    outside = next(s for s in sid if s not in closure)
    return d, {"alert": d["alerts"][0]["id"], "origin": origin, "at": AT, "hub": hub, "outside": outside,
               "storm": sorted([origin, *storm]), "storm_at": AT, "edges": len(edges)}


def demo() -> tuple[dict, dict]:
    d = generate(7)
    return d, {"alert": ACTS[1], "origin": "svc:checkout", "at": T1, "hub": "svc:postgres-orders",
               "outside": "svc:search", "storm": ["svc:checkout", "svc:refunds", "svc:subscriptions"], "storm_at": T3,
               "edges": len(d["depends_on"])}


def cases(repo, m: dict) -> list[tuple[str, str, dict]]:
    """(label, query, params): each hot query with the inputs the tools give it."""
    inc = incident_id_for(m["alert"])
    repo.write("open_incident", alert_id=m["alert"], incident_id=inc)
    recalled = repo.read("recall_similar_reference", incident_id=inc).rows
    if recalled:  # memory_suspects reads the RECALLS edges that recall_similar's tool writes
        repo.write("record_recalls", incident_id=inc, rows=recalled)
    suspects = repo.read("path_suspects_reference", incident_id=inc, window=WINDOW).rows
    words = terms(QUESTION)
    hits = repo.read("search_knowledge", query="|".join(words), limit=PER_LABEL).rows
    o, at, st = m["origin"], m["at"], m["storm_at"]
    return [
        ("path_suspects", "path_suspects", {"incident_id": inc, "window": WINDOW}),
        ("memory_suspects", "memory_suspects", {"incident_id": inc, "window": WINDOW, "min_score": RECALL_MIN_SCORE}),
        ("recall_similar", "recall_similar", {"incident_id": inc}),
        ("live_paths (to the hub)", "live_paths", {"origin": o, "target": m["hub"], "at": at}),
        ("live_paths (no path)", "live_paths", {"origin": o, "target": m["outside"], "at": at}),
        ("blast_radius (alerting service)", "blast_radius", {"service": o, "at": at, "max_hops": 6}),
        ("blast_radius (the hub)", "blast_radius", {"service": m["hub"], "at": at, "max_hops": 6}),
        ("storm_upstream", "storm_upstream", {"services": m["storm"], "at": st, "since": st - WINDOW}),
        ("storm_unexplained", "storm_unexplained", {"services": [*m["storm"][1:], m["outside"]], "target": m["hub"],
                                                    "at": st}),
        ("depends_among (suspects)", "depends_among",
         {"services": sorted({r["service"] for r in suspects})[:8], "at": at}),
        ("who_knows (the hub)", "who_knows", {"service": m["hub"]}),
        ("ask: search_knowledge", "search_knowledge", {"query": "|".join(words), "limit": PER_LABEL}),
        ("ask: knowledge_context", "knowledge_context", {"ids": [h["id"] for h in hits][:TOP]}),
    ]


UNORDERED = {"storm_upstream", "storm_unexplained", "depends_among"}  # no ORDER BY in either form


def canon(name: str, rows: list[dict]) -> list:
    if name == "blast_radius":  # a service that is its own caller (a live cycle): FalkorDB 4.22's nodes(p) may list
        # that cycle backwards in the reference; the rewrite lists it in edge order. Same cycle either way.
        rows = [dict(r, path=min(r["path"], r["path"][::-1])) if r["path"][0] == r["path"][-1] else r for r in rows]
    return sorted(map(repr, rows)) if name in UNORDERED else rows


def same(name: str, a: list[dict], b: list[dict]) -> bool:
    """Identical rows, in the same order unless the query does not define one."""
    return canon(name, a) == canon(name, b)


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, round(p / 100 * (len(s) - 1)))]


def timed(repo, name: str, params: dict, reps: int) -> tuple[list, list[float]]:
    rows = repo.read(name, **params).rows  # warm-up: plan cache
    return rows, [repo.read(name, **params).ms for _ in range(reps)]


def profile(repo, name: str, params: dict) -> str:
    # ponytail: reaches into the repository's graph handle; GRAPH.PROFILE is a bench-only need.
    return "\n".join(repo._graph.profile(all_queries()[name].cypher, params).plan)


def bench(store, n: int, reps: int) -> tuple[dict, list[dict], dict]:
    data, m = demo() if n == 25 else org(n)
    tenant = f"perf_{n}"
    store.drop(tenant)
    repo = store.tenant(tenant)
    load(repo, data)
    out, profiles = [], {}
    try:
        for label, name, params in cases(repo, m):
            ref = f"{name}_reference" if f"{name}_reference" in all_queries() else None
            new_rows, new_ms = timed(repo, name, params, reps)
            ref_rows, ref_ms = timed(repo, ref, params, reps) if ref else (new_rows, None)
            ok = same(name, ref_rows, new_rows)
            out.append({"label": label, "rows": len(new_rows), "same": ok, "ref": ref_ms, "new": new_ms})
            if ref and n == 300 and label in PROFILED:
                profiles[label] = (profile(repo, ref, params), profile(repo, name, params))
            print(f"{n:>5} {label:<34} rows {len(new_rows):>4}  same={ok}  "
                  + (f"ref p50 {pct(ref_ms, 50):8.2f} ms  " if ref_ms else " " * 23)
                  + f"new p50 {pct(new_ms, 50):8.2f} ms")
    finally:
        store.drop(tenant)
    return m, out, profiles


PROFILED = ("path_suspects", "blast_radius (the hub)", "storm_upstream")

INTRO = """\
# Query performance

A FalkorDB review measured the core traversal on a hub-heavy graph (292 services, 1,790 edges): the pattern
`MATCH p = (o)-[:DEPENDS_ON*0..6]->(s) WHERE all(r IN relationships(p) WHERE <valid at $at>)` lists every path
before it filters (`Filter` sits above `Conditional Variable Length Traverse` in the plan), so its cost grows with
the number of paths, not with the size of the graph. This page measures the hot queries before and after the
rewrite, on graphs up to 1,000 services. Generated by `python -m scripts.bench --sizes {sizes} --reps {reps}`;
rerunning reproduces the graphs exactly (seeded), the timings only roughly.
"""

METHOD = """\
## Method

- **Graphs.** 25 services is the demo graph (`datagen.generate(7)`: act 1's alert on checkout at T1, act 3's
  storm at T3). The other sizes come from `scripts/bench.py:org(n)`, seeded: a layered service map (3% edge, 5%
  gateways, 52% domain, 25% platform, 15% caches/queues/databases), each service calling 2-14 services below it
  with Zipf-like weights so a few caches, queues and databases take most of the fan-in, plus callbacks against the
  layering (about 2% of edges, so there are cycles). About 1 in 150 edges is retired before the alert and 2 only
  start after it. On top: changes and anomalies in the 2 h alert window and 14 days of background, a 3-alert storm,
  past incidents with runbooks (3 of them point memory at a change in today's window), 4 people per 8 services,
  and docs, tickets and chat for `ask`.
- **Inputs** are what the tools pass: an incident opened on the top domain service (deep dependency closure),
  `live_paths` to the most-called shared service in its closure (the hub) and to a service it cannot reach,
  `blast_radius` on the alerting service (what triage does) and on the hub (what breaks if the database goes),
  the storm's services, the in-window suspects' services for `depends_among`, and `ask`'s search for
  "{question}".
- **Timing.** Each query runs once to warm the plan cache, then {reps} times; ms are measured in the Python client
  around `GRAPH.RO_QUERY` (round trip and result parsing included), median and p95. One client, nothing else
  running against the database.
- **Same answer.** Before timing, the reference text (`queries/reference.cypher`, the statement as it was before
  the rewrite) and the shipped text run on the same inputs and must return identical rows, in the same order when the
  query has an `ORDER BY`. `storm_upstream`, `storm_unexplained` and `depends_among` have none, in either form, and
  are compared as multisets (the tools build sets from them; `check_hypothesis` also names the unexplained storm
  services in the order returned, which the reference left to its aggregation and the shipped form keeps in input
  order). One intended difference: a service that is its own caller through a live dependency cycle gets that cycle
  as its `blast_radius` path, and the reference may list it backwards (FalkorDB 4.22 returns such a path's nodes in
  either direction), so for that row either direction counts as equal; the shipped form lists it in edge order. The
  demo and eval graphs have no live cycles. Result: **{same}**. `tests/integration/test_query_equivalence.py`
  checks the same on the demo graph at T1/T2/T3 (and before its retired edge was retired), on 20 eval scenarios
  and on the 100-service graph, sweeping every service as origin or target.
- **Machine.** {machine}
"""

CHANGES = """\
## What changed

Each rewrite keeps the 6-hop bound and the rule that every edge on a path must be valid at the alert time
(`valid_from <= at` and `valid_to` null or later).

1. **Few candidates: start from them, then `shortestPath`, checked.** `path_suspects` starts from the changes in
   the window (the `Change.at` range index), `memory_suspects` from the recalled runbooks, `recall_similar` from
   resolved incidents, `storm_unexplained` and `depends_among` from the given services. For each candidate pair,
   `shortestPath((o)-[:DEPENDS_ON*0..6]->(s))` in `WITH` ignores validity, so it is a lower bound: if every edge
   on it is live at the alert time, its length is the answer (no shorter path exists at all); if there is none,
   there is no live path either. Only when it crosses a retired (or not yet live) edge does the query run a
   validity-filtered traversal, for that pair alone, inside a `CALL {{}}` subquery (`PROFILE` shows the
   traversal's input filtered down to those pairs). That traversal puts the validity test on the variable-length
   relationship itself (`[e:DEPENDS_ON*0..6] ... WHERE e.valid_from <= at AND (...)`): FalkorDB then applies it to
   each hop while traversing (no `Filter` operation in the plan; when it cannot, the query fails with a type error
   instead of filtering silently), so retired edges are never expanded.
2. **Whole closures: breadth-first, one hop per `CALL {{}}`.** `storm_upstream` (everything each alerting service
   depends on) and `blast_radius` (everything that depends on a service) expand a frontier six times, keeping only
   edges live at the alert time and deduplicating each level, so each service is expanded at most once per level:
   about 6 x (edges in the closure) instead of one step per path. A service's first level is its distance.
   `blast_radius` also returns a shortest path per caller, and when several are equally short the reference
   returns the one its depth-first traversal meets first; each level therefore carries one path per caller, taken
   through the caller's first parent in level order, with callers ordered by that parent and then by descending
   node id, which is the order FalkorDB's traversal visits neighbours in. Same rows, same paths.
   `storm_upstream` also reads the services that went red once, from the `Anomaly.at` range index, instead of
   scanning anomalies for every row (that scan alone is about 38 ms at 1,000 services, in either form).
3. **`live_paths`: an early exit, nothing else.** It returns up to 20 actual paths, and which 20 (among equally
   long ones) and in what order is the order the traversal meets them. The per-hop filter of (1) changes that
   order, so the traversal stays exactly as it was; a `shortestPath` check in front returns at once when the
   target is not reachable within 6 hops at all.

Unchanged, measured for reference: `who_knows` (linear in people, no path enumeration), `ask`'s
`search_knowledge` (full-text indexes) and `knowledge_context` (id lookups).
"""

LIMITS = """\
## Limitations

- **Our generator, our laptop.** The graphs are synthetic and seeded by us; real dependency maps differ in depth,
  fan-out and cycles, and the old queries' cost depends on the number of paths, so the speedups here are an
  example, not a bound. The reviewer's graph (292 services, 1,790 edges) has far more paths per service than ours:
  their upstream closure took 1,653 ms, while `path_suspects` (the same closure) takes 12 ms in its reference form on
  our 300-service graph. Ours gets expensive in the other direction, into a hub (`blast_radius`).
- **Single client, warm cache, localhost.** No concurrency, no network, the whole graph in memory.
- **The fallback is still a path traversal, for the pairs that need it.** When the unfiltered shortest path
  crosses an edge not live at the alert time, that pair's live distance comes from the validity-filtered
  variable-length traversal, whose cost is the number of live paths between the two services. With few retired
  edges this is rare; a graph where most shortest paths cross retired edges would pay it often.
- **`live_paths` still lists every live path from the origin** within 6 hops; only an unreachable target is cheap
  now. It is called once per checked suspect.
- **Tie-breaking relies on FalkorDB's traversal order.** `blast_radius` reproduces the reference's choice among
  equally short paths by ordering by node id the way FalkorDB 4.22's depth-first traversal visits neighbours.
  If a later FalkorDB visits them differently, the two could pick different (equally short, live) paths;
  the equivalence test would flag it.
- **At demo size nothing is faster.** On 25 services every query takes about a millisecond either way, and the
  rewritten ones can be a fraction of a millisecond slower (more operations in the plan). The 200-incident eval
  (`docs/EVAL.md`) has the same accuracy and the same per-incident latency within noise.
- **Equal results are tested, not proven**: on these graphs, the demo at four times, 20 eval scenarios and the
  100-service graph.
"""


def machine(store) -> str:
    mods = [dict(zip(m[::2], m[1::2], strict=False)) for m in store.db.connection.execute_command("MODULE", "LIST")]
    ver = next((int(m["ver"]) for m in mods if m["name"] == "graph"), 0)
    cpu = next((ln.split(":", 1)[1].strip() for ln in Path("/proc/cpuinfo").read_text().splitlines()
                if ln.startswith("model name")), platform.processor()) if Path("/proc/cpuinfo").exists() else ""
    return (f"FalkorDB {ver // 10000}.{ver // 100 % 100}.{ver % 100} (native module, not Docker) on {cpu}, "
            f"{platform.system()} {platform.release()}, glibc {platform.libc_ver()[1]}, Python "
            f"{platform.python_version()}, client and server on the same laptop.")


def report(results: dict[int, tuple[dict, list[dict]]], profiles: dict, reps: int, where: str) -> str:
    sizes = sorted(results)
    labels = [r["label"] for r in results[sizes[0]][1]]

    def cell(r: dict, p: float) -> str:
        new = pct(r["new"], p)
        if r["ref"] is None:
            return f"{new:.1f}"
        ref = pct(r["ref"], p)
        return f"{ref:.1f} → {new:.1f}" + (f" ({ref / new:.0f}x)" if ref / new >= 1.5 else "")

    def table(p: float) -> list[str]:
        head = "| query | " + " | ".join(f"{n} svc, {results[n][0]['edges']} edges" for n in sizes) + " |"
        lines = [head, "|---" * (len(sizes) + 1) + "|"]
        for i, label in enumerate(labels):
            changed = results[sizes[0]][1][i]["ref"] is not None
            lines.append(f"| {label}{'' if changed else ' (unchanged)'} | "
                         + " | ".join(cell(results[n][1][i], p) for n in sizes) + " |")
        return lines

    def ops(plan: str) -> str:
        recs = [int(x) for x in re.findall(r"Records produced: (\d+)", plan)]
        return f"{len(recs)} operations, {sum(recs):,} records produced in total"

    same = all(r["same"] for n in sizes for r in results[n][1])
    lines = [INTRO.format(sizes=",".join(map(str, sizes)), reps=reps),
             METHOD.format(question=QUESTION, reps=reps, machine=where,
                           same="identical in every case below" if same else "DIFFERENT somewhere: see the log"),
             CHANGES,
             "## Results", "",
             "Milliseconds per call, reference → shipped (speedup when 1.5x or more).", "",
             "### p50", "", *table(50), "", "### p95", "", *table(95), "",
             "## GRAPH.PROFILE, 300 services", "",
             "What each form does on the same input (`GRAPH.PROFILE` runs the query once and counts the records "
             "each operation produced). The reference's cost is the `Conditional Variable Length Traverse`: one "
             "record per path.", ""]
    for label, (ref, new) in profiles.items():
        lines += [f"- **{label}**: reference {ops(ref)}; shipped {ops(new)}."]
    for label, (ref, new) in profiles.items():
        lines += ["", f"<details><summary>{label}: plans</summary>", "", "Reference:", "", "```", ref, "```", "",
                  "Shipped:", "", "```", new, "```", "", "</details>"]
    lines += ["", LIMITS]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sizes", default="25,100,300,1000")
    p.add_argument("--reps", type=int, default=15)
    p.add_argument("--no-doc", action="store_true", help="print only; leave docs/PERF.md alone")
    a = p.parse_args()
    store = make_store()
    results, profiles = {}, {}
    for n in map(int, a.sizes.split(",")):
        m, rows, prof = bench(store, n, a.reps)
        results[n] = (m, rows)
        profiles |= prof
    doc = report(results, profiles, a.reps, machine(store))
    print(doc.split("## Results", 1)[1].split("### p95", 1)[0])
    if not a.no_doc:
        DOC.write_text(doc + "\n")
        print(f"wrote {DOC}")
    return 0 if all(r["same"] for _, rows in results.values() for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
