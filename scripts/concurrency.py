"""Concurrency benchmark: python -m scripts.concurrency [--tenants 8] [--readers 8] [--writers 8] [--seconds 3]

Measured against a live FalkorDB; the numbers in docs/PERF.md ("Concurrency") come from here.
1. Parallel tenants: N tenants each respond to act 1 at the same moment (one graph per tenant, no shared lock),
   against the same N one after another. Wall time, per-incident p50/p95; every run must find the cause.
2. Readers during agent runs: on one tenant, agent runs hold the tenant lock back to back while R clients keep
   calling read tools (blast_radius, who_knows, ask). Reads never take the lock, so they keep answering.
3. Concurrent event writers on one tenant: W clients each push K changes and K anomalies through run_tool (each
   write holds the lock for one query), and all of them keep re-recording one change id. Afterwards the graph must
   hold exactly W*K new changes, one CHANGED edge each, and one node for the shared id.
4. What the database enforces, on a scratch graph: 12 clients race CREATE on 10 ids with and without a UNIQUE
   constraint (duplicate ids, refused writes), and race MERGE of one edge (duplicate edges). The first is why node
   uniqueness is a constraint; the second is why agent runs still hold the per-tenant lock.
Timings are wall-clock in one client process (threads, round trip included). FalkorDB runs one write per graph at a
time, so these show what the constraints, the lock and one-graph-per-tenant give, not the server's raw throughput.
"""

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from redis.exceptions import ResponseError

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.datagen import ACTS
from oncall_brain.services.respond import resolve, respond, run_tool
from oncall_brain.services.seeding import reset, seed
from oncall_brain.wiring import make_store
from scripts.bench import machine, pct

PREFIX = "bench_conc_"
QUIET_DAY = 1792121400  # a day in the seeded history with nothing planted on it
TRUTH = "chg:pgw-pool-1"


def ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


def duplicates(store, tenant: str) -> tuple[int, int]:
    """(ids shared by two nodes of one label, node pairs joined twice by one edge type)."""
    g = store.tenant(tenant)._graph  # bench-only raw counts
    nodes = g.ro_query("MATCH (n) WITH labels(n)[0] AS l, n.id AS id, count(*) AS c WHERE c > 1 "
                       "RETURN count(*)").result_set[0][0]
    edges = g.ro_query("MATCH (a)-[e]->(b) WITH a, b, type(e) AS t, count(e) AS c WHERE c > 1 "
                       "RETURN count(*)").result_set[0][0]
    return nodes, edges


def parallel_tenants(store, n: int) -> dict:
    names = [f"{PREFIX}{i}" for i in range(n)]
    for t in names:
        seed(store, t)

    def run(t: str) -> tuple[float, str | None]:
        t0 = time.perf_counter()
        o = respond(store.tenant(t), ACTS[1], MockProvider())["outcome"]
        return ms(t0), (o["root_cause"] or {}).get("change")

    t0 = time.perf_counter()
    seq = [run(t) for t in names]
    seq_wall = ms(t0)
    for t in names:
        reset(store, t)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(n) as pool:
        par = list(pool.map(run, names))
    par_wall = ms(t0)
    dup = [duplicates(store, t) for t in names]
    for t in names:
        store.drop(t)
    return {"n": n, "seq_wall": seq_wall, "par_wall": par_wall, "seq_ms": [x for x, _ in seq],
            "par_ms": [x for x, _ in par], "correct": sum(c == TRUTH for _, c in par),
            "dup_nodes": sum(a for a, _ in dup), "dup_edges": sum(b for _, b in dup)}


def readers_during_runs(store, readers: int, seconds: float) -> dict:
    tenant = f"{PREFIX}reads"
    seed(store, tenant)
    stop, lat, errors = threading.Event(), [[] for _ in range(readers)], [0]
    calls = [("blast_radius", {"service": "svc:payments-gw"}), ("who_knows", {"service": "svc:payments-gw"}),
             ("ask", {"question": "why was the payments gateway pool lowered"})]

    def reader(i: int) -> None:
        repo, k = store.tenant(tenant), 0
        while not stop.is_set():
            name, args = calls[k % len(calls)]
            k += 1
            t0 = time.perf_counter()
            try:
                run_tool(repo, name, args)
            except Exception:  # counted, never raised: the point is whether reads keep answering
                errors[0] += 1
            lat[i].append(ms(t0))

    runs, llm, repo = 0, MockProvider(), store.tenant(tenant)
    with ThreadPoolExecutor(readers) as pool:
        futures = [pool.submit(reader, i) for i in range(readers)]
        deadline = time.perf_counter() + seconds
        t0 = time.perf_counter()
        while time.perf_counter() < deadline:  # the whole story, over and over: lock held most of the time
            reset(store, tenant)
            act1 = respond(repo, ACTS[1], llm)
            resolve(repo, act1["incident_id"], act1["outcome"]["root_cause"]["change"])
            respond(repo, ACTS[2], llm)
            respond(repo, ACTS[3], llm)
            runs += 3
        wall = ms(t0)
        stop.set()
        for f in futures:
            f.result()
    store.drop(tenant)
    flat = [x for xs in lat for x in xs]
    return {"readers": readers, "wall": wall, "runs": runs, "reads": len(flat), "read_ms": flat, "errors": errors[0]}


def event_writers(store, writers: int, per: int) -> dict:
    tenant = f"{PREFIX}writes"
    seed(store, tenant)

    def writer(w: int) -> list[float]:
        repo, out = store.tenant(tenant), []
        for k in range(per):
            at = QUIET_DAY + w * 1000 + k * 2
            for name, args in (
                    ("record_change", {"service": "svc:inventory", "kind": "deploy", "id": f"chg:conc-{w}-{k}",
                                       "summary": f"writer {w} deploy {k}", "at": at}),
                    ("record_anomaly", {"service": "svc:inventory", "kind": "errors", "summary": "5xx up",
                                        "at": at + 1}),
                    ("record_change", {"service": "svc:inventory", "kind": "config", "id": "chg:conc-same",
                                       "summary": f"one change, re-recorded by writer {w}", "at": QUIET_DAY + 50})):
                t0 = time.perf_counter()
                run_tool(repo, name, args)
                out.append(ms(t0))
        return out

    t0 = time.perf_counter()
    with ThreadPoolExecutor(writers) as pool:
        lat = [x for xs in pool.map(writer, range(writers)) for x in xs]
    wall = ms(t0)
    g = store.tenant(tenant)._graph
    changes = g.ro_query("MATCH (c:Change) WHERE c.id STARTS WITH 'chg:conc-' RETURN count(c)").result_set[0][0]
    bad_edges = g.ro_query("MATCH (c:Change)-[:CHANGED]->() WHERE c.id STARTS WITH 'chg:conc-' "
                           "WITH c, count(*) AS n WHERE n <> 1 RETURN count(c)").result_set[0][0]
    anomalies = g.ro_query("MATCH (x:Anomaly) WHERE x.summary = '5xx up' RETURN count(x)").result_set[0][0]
    dup = duplicates(store, tenant)
    store.drop(tenant)
    return {"writers": writers, "per": per, "wall": wall, "write_ms": lat, "changes": changes,
            "expected_changes": writers * per + 1, "bad_edges": bad_edges, "anomalies": anomalies,
            "expected_anomalies": writers * per, "dup_nodes": dup[0], "dup_edges": dup[1]}


def what_the_database_enforces(store, repeats: int = 3) -> dict:
    """CREATE races on 10 node ids with and without the constraint; MERGE races on one edge."""
    db = store.db

    def race(name: str, stmt: str, constrained: bool, threads: int = 12, reps: int = 20) -> tuple[int, int, int]:
        g = db.select_graph(name)
        g.query("CREATE (:Probe {id: -1})")
        g.query("CREATE INDEX FOR (n:Probe) ON (n.id)")
        if constrained:
            g.create_node_unique_constraint("Probe", "id")
            while not all(c["status"] == "OPERATIONAL" for c in g.list_constraints()):
                time.sleep(0.02)
        refused = [0]

        def w(_: int) -> None:
            gg = db.select_graph(name)
            for k in range(reps):
                try:
                    gg.query(stmt, {"k": k % 10})
                except ResponseError:
                    refused[0] += 1

        with ThreadPoolExecutor(threads) as pool:
            list(pool.map(w, range(threads)))
        dup = g.ro_query("MATCH (n:Probe) WITH n.id AS id, count(*) AS c WHERE c > 1 RETURN count(*)").result_set[0][0]
        nodes = g.ro_query("MATCH (n:Probe) RETURN count(n)").result_set[0][0]
        g.delete()
        return dup, nodes, refused[0]

    def edge_race(name: str, threads: int = 12, reps: int = 50) -> int:
        g = db.select_graph(name)
        g.query("CREATE (:Probe {id: 'a'}), (:Probe {id: 'b'})")
        g.query("CREATE INDEX FOR (n:Probe) ON (n.id)")

        def w(_: int) -> None:
            gg = db.select_graph(name)
            for k in range(reps):
                gg.query("MATCH (a:Probe {id: 'a'}), (b:Probe {id: 'b'}) MERGE (a)-[:R {k: $k}]->(b)", {"k": k % 5})

        with ThreadPoolExecutor(threads) as pool:
            list(pool.map(w, range(threads)))
        edges = g.ro_query("MATCH (:Probe)-[r:R]->(:Probe) RETURN count(r)").result_set[0][0]
        g.delete()
        return edges - 5  # 5 distinct k values: anything above is a duplicate edge

    out = {"create_plain": [], "create_constrained": [], "edge_merge": []}
    for _ in range(repeats):
        out["create_plain"].append(race(f"{PREFIX}scratch", "CREATE (:Probe {id: $k})", False))
        out["create_constrained"].append(race(f"{PREFIX}scratch", "CREATE (:Probe {id: $k})", True))
        out["edge_merge"].append(edge_race(f"{PREFIX}scratch"))
    return out


def report(where: str, a: dict, b: dict, c: dict, d: dict) -> str:
    p = lambda xs, q: f"{pct(xs, q):.1f}"  # noqa: E731
    lines = [
        "## Concurrency", "",
        "Generated by `python -m scripts.concurrency` (one client process, threads, wall-clock round trips).", "",
        f"- **Machine.** {where}", "",
        "### Parallel tenants (one graph each, no shared lock)", "",
        "| | wall ms | per incident p50 ms | per incident p95 ms | right cause | duplicate ids / edges |",
        "|---|---|---|---|---|---|",
        f"| {a['n']} tenants one after another | {a['seq_wall']:.0f} | {p(a['seq_ms'], 50)} | {p(a['seq_ms'], 95)} | "
        f"{a['n']}/{a['n']} | |",
        f"| {a['n']} tenants at the same moment | {a['par_wall']:.0f} | {p(a['par_ms'], 50)} | {p(a['par_ms'], 95)} | "
        f"{a['correct']}/{a['n']} | {a['dup_nodes']} / {a['dup_edges']} |", "",
        "### Readers while agent runs hold the tenant lock", "",
        "| readers | agent runs (lock held) | reads completed | read p50 ms | read p95 ms | read p99 ms | "
        "slowest read ms | read errors |",
        "|---|---|---|---|---|---|---|---|",
        f"| {b['readers']} | {b['runs']} in {b['wall']:.0f} ms | {b['reads']} | {p(b['read_ms'], 50)} | "
        f"{p(b['read_ms'], 95)} | {p(b['read_ms'], 99)} | {max(b['read_ms']):.0f} | {b['errors']} |", "",
        "### Concurrent event writers on one tenant (each write takes the lock for one query)", "",
        "| writers x events | wall ms | write p50 ms | write p95 ms | write p99 ms | slowest write ms | "
        "changes (expected) | anomalies (expected) | changes with != 1 CHANGED edge | duplicate ids / edges |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| {c['writers']} x {c['per']} | {c['wall']:.0f} | {p(c['write_ms'], 50)} | {p(c['write_ms'], 95)} | "
        f"{p(c['write_ms'], 99)} | {max(c['write_ms']):.0f} | "
        f"{c['changes']} ({c['expected_changes']}) | {c['anomalies']} ({c['expected_anomalies']}) | {c['bad_edges']} | "
        f"{c['dup_nodes']} / {c['dup_edges']} |", "",
        "### What the database enforces (scratch graph, 12 clients, 3 repeats)", "",
        "| race | duplicate ids per repeat | nodes | refused writes |",
        "|---|---|---|---|",
        f"| CREATE on 10 ids, no constraint | {', '.join(str(x[0]) for x in d['create_plain'])} | "
        f"{', '.join(str(x[1]) for x in d['create_plain'])} | 0 |",
        f"| CREATE on 10 ids, UNIQUE constraint | {', '.join(str(x[0]) for x in d['create_constrained'])} | "
        f"{', '.join(str(x[1]) for x in d['create_constrained'])} | "
        f"{', '.join(str(x[2]) for x in d['create_constrained'])} |",
        f"| MERGE one edge (5 keys, 600 calls) | duplicate edges: {', '.join(map(str, d['edge_merge']))} | | |", "",
    ]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tenants", type=int, default=8)
    p.add_argument("--readers", type=int, default=8)
    p.add_argument("--writers", type=int, default=8)
    p.add_argument("--per", type=int, default=25, help="events per writer")
    p.add_argument("--seconds", type=float, default=3.0, help="how long readers run while agent runs hold the lock")
    p.add_argument("--out", type=Path, help="write the markdown section here instead of stdout")
    a = p.parse_args()
    store = make_store()
    text = report(machine(store), parallel_tenants(store, a.tenants), readers_during_runs(store, a.readers, a.seconds),
                  event_writers(store, a.writers, a.per), what_the_database_enforces(store))
    if a.out:
        a.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
