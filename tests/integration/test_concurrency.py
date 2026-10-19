"""Uniqueness is enforced by the database, tenants run in parallel, reads never wait for a writer, and concurrent
writers on one tenant add exactly what they wrote."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from redis.exceptions import ResponseError

from oncall_brain.adapters.falkordb.repository import INDEXED_LABELS
from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.datagen import ACTS
from oncall_brain.services.respond import respond, run_tool
from oncall_brain.services.seeding import reset, seed

pytestmark = pytest.mark.integration

ALL_OPERATIONAL = {label: "OPERATIONAL" for label in INDEXED_LABELS}


def _count(repo, cypher: str) -> int:
    return repo._graph.ro_query(cypher).result_set[0][0]


def test_every_label_has_a_unique_id_constraint_that_reset_keeps_and_the_database_enforces(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    assert repo.unique_constraints() == ALL_OPERATIONAL
    services = _count(repo, "MATCH (s:Service) RETURN count(s)")
    with pytest.raises(ResponseError, match="unique constraint violation"):
        repo._graph.query("CREATE (:Service {id: 'svc:checkout', name: 'a second checkout'})")
    repo._graph.query("MERGE (s:Service {id: 'svc:checkout'}) SET s.touched = true")  # MERGE on the id updates in place
    assert _count(repo, "MATCH (s:Service) RETURN count(s)") == services
    repo.ensure_schema()  # idempotent
    assert repo.unique_constraints() == ALL_OPERATIONAL
    assert reset(store, tenant) == "restored"  # GRAPH.COPY of the pristine graph carries the constraints
    repo = store.tenant(tenant)
    assert repo.unique_constraints() == ALL_OPERATIONAL
    person = repo._graph.ro_query("MATCH (p:Person) RETURN p.id LIMIT 1").result_set[0][0]
    with pytest.raises(ResponseError, match="unique constraint violation"):
        repo._graph.query("CREATE (:Person {id: $id})", {"id": person})


def test_tenants_respond_in_parallel_and_stay_isolated(store):
    names = [f"itest_par_{os.getpid()}_{i}" for i in range(3)]
    for name in names:
        seed(store, name)
    try:
        with ThreadPoolExecutor(3) as pool:
            runs = list(pool.map(lambda n: respond(store.tenant(n), ACTS[1], MockProvider()), names))
        assert [r["outcome"]["root_cause"]["change"] for r in runs] == ["chg:pgw-pool-1"] * 3
        for name in names:
            repo = store.tenant(name)
            assert _count(repo, "MATCH (i:Incident {status: 'open'}) RETURN count(i)") == 1
            assert _count(repo, "MATCH (a)-[e]->(b) WITH a, b, type(e) AS t, count(e) AS n WHERE n > 1 "
                                "RETURN count(*)") == 0
    finally:
        for name in names:
            store.drop(name)


def test_reads_answer_while_a_writer_holds_the_tenant_lock(store, tenant):
    seed(store, tenant)
    with store.tenant(tenant).lock():  # an agent run in progress on this tenant
        with ThreadPoolExecutor(1) as pool:
            out = pool.submit(run_tool, store.tenant(tenant), "blast_radius", {"service": "svc:payments-gw"}).result(
                timeout=5)  # a read never takes the lock; waiting for it would time out here
    assert {r["service"] for r in out.data} >= {"svc:payments", "svc:checkout"}


def test_concurrent_event_writers_add_exactly_their_events_and_a_re_recorded_id_stays_one_node(store, tenant):
    seed(store, tenant)
    base = 1792121400  # a quiet day in the seeded history

    def writer(w: int) -> None:
        repo = store.tenant(tenant)
        for k in range(5):
            run_tool(repo, "record_change", {"service": "svc:inventory", "kind": "deploy", "id": f"chg:conc-{w}-{k}",
                                             "summary": f"writer {w} deploy {k}", "at": base + w * 100 + k})
            run_tool(repo, "record_change", {"service": "svc:inventory", "kind": "config", "id": "chg:conc-same",
                                             "summary": f"the same change, re-recorded by writer {w}", "at": base + 50})

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(writer, range(4)))
    repo = store.tenant(tenant)
    assert _count(repo, "MATCH (c:Change) WHERE c.id STARTS WITH 'chg:conc-' RETURN count(c)") == 4 * 5 + 1
    assert _count(repo, "MATCH (c:Change)-[:CHANGED]->() WHERE c.id STARTS WITH 'chg:conc-' "
                        "WITH c, count(*) AS n WHERE n <> 1 RETURN count(c)") == 0


def test_reads_keep_answering_while_the_tenant_is_reset(store, tenant):
    """A reset swaps the tenant graph for its pristine copy with GRAPH.COPY + RENAME, so a reader never meets a
    missing graph (delete-then-copy used to fail every read in the gap with 'Invalid graph operation on empty key')."""
    seed(store, tenant)
    stop, done, errors = threading.Event(), [0], []

    def reader() -> None:
        repo = store.tenant(tenant)
        while not stop.is_set():
            try:
                run_tool(repo, "blast_radius", {"service": "svc:payments-gw"})
                done[0] += 1
            except Exception as e:  # noqa: BLE001 - every failure is the finding
                errors.append(str(e))

    with ThreadPoolExecutor(4) as pool:
        futures = [pool.submit(reader) for _ in range(4)]
        for _ in range(8):
            assert reset(store, tenant) == "restored"
        stop.set()
        for f in futures:
            f.result()
    assert errors == []
    assert done[0] > 8
    assert store.tenants().count(tenant) == 1 and not any(n.startswith("restoring_") for n in store.db.list_graphs())


def test_racing_writers_record_one_dependency_once_without_any_lock(store, tenant):
    """The dependency key is UNIQUE (with MANDATORY, since UNIQUE skips a missing value): 12 clients racing the ingest
    MERGE for one new dependency, outside the tenant lock, leave exactly one edge. A loser's MERGE is refused by the
    database (unique constraint violation) or finds the winner's edge."""
    seed(store, tenant)
    repo = store.tenant(tenant)
    row = {"src": "svc:search", "dst": "svc:kafka", "valid_from": 1_700_000_123, "valid_to": None}
    errors: list[str] = []

    def merge(_):
        try:
            repo.write("ingest_depends_on", rows=[row])
        except ResponseError as e:
            errors.append(str(e))

    with ThreadPoolExecutor(12) as pool:
        list(pool.map(merge, range(48)))
    assert repo._graph.ro_query("MATCH (:Service {id: 'svc:search'})-[d:DEPENDS_ON]->(:Service {id: 'svc:kafka'}) "
                                "WHERE d.valid_from = 1700000123 RETURN count(d), collect(d.key)").result_set == [
        [1, ["svc:search>svc:kafka@1700000123"]]]
    assert all("unique constraint" in e for e in errors), errors
    with pytest.raises(ResponseError, match="unique constraint violation"):
        repo._graph.query("MATCH (a:Service {id: 'svc:search'}), (b:Service {id: 'svc:kafka'}) CREATE (a)-[:DEPENDS_ON "
                          "{key: 'svc:search>svc:kafka@1700000123', valid_from: 1700000123}]->(b)")


def test_a_graph_from_before_the_dependency_key_gets_its_keys_and_constraints(store):
    """A pristine copy made before the key: ensure_schema backfills every dependency's key, then builds the
    constraints, which come up OPERATIONAL instead of FAILED."""
    from oncall_brain.adapters.falkordb.repository import FalkorRepository

    name = f"zz_itest_oldgraph_{os.getpid()}"
    old = store.db.select_graph(name)
    try:
        old.query("CREATE (a:Service {id: 'svc:a'})-[:DEPENDS_ON {valid_from: 1}]->(b:Service {id: 'svc:b'}), "
                  "(a)-[:DEPENDS_ON {valid_from: 5, valid_to: 9}]->(b)")
        FalkorRepository(store.db, "itest", graph=name, coord=store.coord).ensure_schema()
        assert sorted(r[0] for r in old.ro_query("MATCH ()-[d:DEPENDS_ON]->() RETURN d.key").result_set) == [
            "svc:a>svc:b@1", "svc:a>svc:b@5"]
        rel = {(c["type"], c["label"], tuple(c["properties"])): c["status"] for c in old.list_constraints()
               if c["entitytype"] == "RELATIONSHIP"}
        assert rel[("UNIQUE", "DEPENDS_ON", ("key",))] == rel[("MANDATORY", "DEPENDS_ON", ("key",))] == "OPERATIONAL"
    finally:
        old.delete()
