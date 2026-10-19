"""Locks and counters as graph writes (adapters/falkordb/coordination.py): exactly one concurrent claimer wins, a
lapsed lease is taken over and cannot be renewed or released by its old holder, and no increment is lost."""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from redis.exceptions import LockError, LockNotOwnedError

from oncall_brain.adapters.falkordb.coordination import GRAPH, GraphLock
from oncall_brain.adapters.falkordb.repository import UDF_LIB
from oncall_brain.datagen import T1
from oncall_brain.serve import tend


def _key(name: str) -> str:
    return f"itest:{os.getpid()}:{name}:{time.time_ns()}"


def test_one_of_many_concurrent_claimers_wins(store):
    key = _key("race")
    with ThreadPoolExecutor(16) as pool:
        wins = list(pool.map(lambda i: store.coord.claim(key, 30, f"o{i}"), range(16)))
    assert wins.count(True) == 1
    assert store.coord.held(key)


def test_a_lapsed_lease_is_taken_over_and_its_old_holder_is_locked_out(store):
    key = _key("lapse")
    old = GraphLock(store.coord, key, ttl=0.2, blocking_timeout=0)
    assert old.acquire()
    with pytest.raises(LockError):  # held: a waiter with no wait gives up at once
        GraphLock(store.coord, key, ttl=5, blocking_timeout=0).__enter__()
    time.sleep(0.3)
    new = GraphLock(store.coord, key, ttl=5, blocking_timeout=0)
    assert new.acquire()  # the lapsed lease is cleared and claimed in one call
    with pytest.raises(LockNotOwnedError):
        old.reacquire()
    old.release()  # the old holder's release leaves the new holder's lease alone
    assert new.locked()
    new.reacquire()
    new.release()
    assert not new.locked()


def test_concurrent_increments_are_not_lost_and_an_expired_counter_restarts(store):
    key = _key("count")
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(lambda _: store.incr(key, ttl=30, by=2), range(160)))
    assert store.counter(key) == 320
    short = _key("short")
    store.coord._write("coord_incr", key=short, ms=100, by=5)
    time.sleep(0.2)
    assert store.counter(short) == 0
    assert store.incr(short, ttl=30) == 1


def test_a_tenant_run_lock_is_a_lease_in_the_coordination_graph(store, tenant):
    repo = store.tenant(tenant)
    with repo.lock() as lk:
        assert repo.lock().locked()
        lk.reacquire()
    assert not repo.lock().locked()
    assert "oncall_brain_coord" not in [f"tenant_{t}" for t in store.tenants()]


def test_a_restarted_database_heals_within_one_tend(store, tenant):
    """What FalkorDB Cloud Free does on a restart (no persistence): the UDF library, the coordination graph and the
    company are gone. The next query reloads the library; the watchdog (serve.tend, once a minute) puts the
    coordination constraints back, so leases are exclusive again, and re-seeds the company."""
    tend(store, tenant)
    assert store.exists(tenant)  # a missing company is seeded
    repo = store.tenant(tenant)
    before = repo.read("blast_radius", service="svc:payments-gw", at=T1, max_hops=6).rows
    store.db.udf_delete(UDF_LIB)
    assert repo.read("blast_radius", service="svc:payments-gw", at=T1, max_hops=6).rows == before
    store.db.select_graph(GRAPH).delete()
    store.coord.incr(_key("after-restart"), ttl=30)  # the first write recreates the graph, unconstrained
    tend(store, tenant)
    key = _key("healed")
    with ThreadPoolExecutor(16) as pool:
        assert list(pool.map(lambda i: store.coord.claim(key, 30, f"o{i}"), range(16))).count(True) == 1


def test_a_restart_burst_loads_the_udf_library_once_and_never_replaces_code_that_matches(store, tenant):
    """After a restart every request thread misses oncall.live_upstream at once. Reloading it from each of them (two
    REPLACEs close together while queries run) can crash FalkorDB 4.22 (#3357), so the loader takes one lock, LOADs
    only a missing library, and REPLACEs only code that differs."""
    from oncall_brain.adapters.falkordb import repository

    tend(store, tenant)
    store.db.udf_delete(UDF_LIB)
    repository._udf_loaded.discard(store.db)
    loads = []
    real = store.db.udf_load
    store.db.udf_load = lambda *a, **k: (loads.append(k.get("replace", a[2] if len(a) > 2 else False)), real(*a, **k))
    try:
        with ThreadPoolExecutor(16) as pool:
            rows = list(pool.map(lambda _: store.tenant(tenant).read(
                "blast_radius", service="svc:payments-gw", at=T1, max_hops=6).rows, range(32)))
        assert all(r == rows[0] for r in rows) and rows[0]
        assert loads == [False]  # one LOAD, no REPLACE
        repository._udf_loaded.discard(store.db)
        repository.ensure_udfs(store.db)
        assert loads == [False]  # the server already holds this code: nothing is loaded again
    finally:
        del store.db.udf_load
    assert store.db.connection.ping()


def test_a_failed_constraint_after_a_restart_is_repaired_without_losing_a_count(store):
    """After a database restart, claims made before the watchdog's check can leave two Lease nodes with one key, so
    the UNIQUE constraint comes up FAILED. recheck removes the extra nodes (a counter's counts are summed, not lost),
    drops the failed constraint and builds it again, instead of failing every lease and counter for good."""
    from oncall_brain.adapters.falkordb.coordination import Coordination

    co = Coordination(store.db)
    g = store.db.select_graph("zz_itest_coord_" + str(os.getpid()))
    import oncall_brain.adapters.falkordb.coordination as coordination

    real, coordination.GRAPH = coordination.GRAPH, g.name
    try:
        assert co.claim("k", 30, "a")  # builds the graph and its constraints
        g.delete()  # the restart; co keeps its cached graph
        assert co.claim("k", 30, "a") and co.claim("k", 30, "b")  # no constraint yet: both succeed
        co.incr("c", ttl=30, by=2)
        g.query("CREATE (:Counter {key: 'c', n: 3, exp: timestamp() + 30000})")  # a second counter, same key
        co.recheck()
        status = {c["label"]: c["status"] for c in g.list_constraints() if c["type"] == "UNIQUE"}
        assert status == {"Lease": "OPERATIONAL", "Counter": "OPERATIONAL"}, status
        assert g.ro_query("MATCH (l:Lease {key: 'k'}) RETURN count(l)").result_set == [[1]]
        assert co.counter("c") == 5
        assert not co.claim("k", 30, "c")  # exclusive again
    finally:
        coordination.GRAPH = real
        if g.name in store.db.list_graphs():
            g.delete()


def test_a_failing_sweep_never_fails_the_write_it_rides_on(store, monkeypatch):
    from redis.exceptions import ResponseError

    from oncall_brain.adapters.falkordb import coordination

    co, key = coordination.Coordination(store.db), _key("sweep")
    real_get = coordination.queries.get

    def get(name):
        if name == "coord_sweep":
            raise ResponseError("Max pending queries exceeded")
        return real_get(name)

    monkeypatch.setattr(coordination.queries, "get", get)
    monkeypatch.setattr(coordination, "SWEEP_EVERY", 1)  # every write sweeps
    lock = GraphLock(co, key, ttl=30, blocking_timeout=0)
    with lock:
        assert lock.token
    assert not co.held(key)  # released: the lease is not left behind


def test_runs_in_flight_counts_run_leases_only(store, tenant):
    """What deploy/aws/host.sh waits on before restarting the app: a tenant's run lease counts, a scoped lease (an
    engineer's conversation session) does not."""
    base = store.coord.runs_in_flight()
    with store.tenant(tenant).lock():
        assert store.coord.runs_in_flight() == base + 1
        with store.tenant(tenant).lock("session_x"):
            assert store.coord.runs_in_flight() == base + 1
    assert store.coord.runs_in_flight() == base
