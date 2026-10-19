"""Every named query's plan, as FalkorDB's own planner gives it (GRAPH.EXPLAIN): it starts from an index unless it is
on the list below, which says why that query reads a whole label. A new query that scans fails here, and so does a
listed one that no longer scans, so the list stays true. The time-window queries are also checked by label."""

import re

import pytest

from oncall_brain.adapters.falkordb.coordination import GRAPH as COORD
from oncall_brain.adapters.falkordb.queries import all_queries, get
from oncall_brain.datagen import T1
from oncall_brain.services.seeding import seed

pytestmark = pytest.mark.integration

SCANS = {  # query -> why it reads every node of a label (all small, bounded labels)
    "data_version": "the one Meta node",
    "ingest_meta": "the one Meta node",
    "link_entities": "matches the question's words against every entity name: that is the lookup",
    "list_alerts": "the inbox: every alert",
    "ownership": "the latest alert's time, and the teams named in $ids or owning a service in them (6 teams)",
    "resolve_service": "compares a typed name with every service name",
    "service_incidents": "incidents tied to the given ids through IMPACTS or CAUSED_BY (tens of incidents)",
    "service_map": "the map: every service",
    "topology_at": "the whole dependency graph at one time, for algo.pageRank's projection",
    "who_knows": "ranks every person by what ties them to the service",
    "coord_sweep": "deletes every expired lease and counter; runs once per 500 coordination writes",
    "coord_dedupe_leases": "the repair after a database restart, run only when a constraint FAILED: every lease",
    "coord_dedupe_counters": "the same repair for counters",
    "coord_runs_in_flight": "counts the live run leases, once per deploy (deploy/aws/host.sh)",
    "backfill_dependency_keys": "keys every dependency of a graph from before the key, once, at ensure_schema",
}
SCAN = re.compile(r"(Node By Label Scan \| \(\w+:\w+\)|All Node Scan \| \(\w+\))")
LISTS = {"rows", "services", "edges", "ids", "tokens", "path", "explained", "gaps", "sources", "entities"}


def _dummy(param: str):  # typed values: a null parameter can give the planner a worse plan than the real call gets
    if param in LISTS:
        return []
    if param in {"at", "since", "until", "window", "ms", "by", "limit", "max_hops", "min_score", "onset", "red_before",
                 "seed"} or param.endswith(("_at", "_ms")):
        return 1
    return "x:none"


def _plan(graph, cypher: str, params: dict) -> str:
    return "\n".join(str(op) for op in graph.explain(cypher, params).plan)


def test_every_query_starts_from_an_index_unless_listed(store, tenant):
    seed(store, tenant)
    store.coord.incr("itest:plans", ttl=5)  # the coordination graph exists
    tenant_graph, coord_graph = store.tenant(tenant)._graph, store.db.select_graph(COORD)
    scanning = {}
    for name, q in all_queries().items():
        if q.file == "reference.cypher":  # tests and bench only
            continue
        params = {p: _dummy(p) for p in set(re.findall(r"\$(\w+)", q.cypher))}
        plan = _plan(coord_graph if q.file == "coordination.cypher" else tenant_graph, q.cypher, params)
        if SCAN.search(plan):
            scanning[name] = sorted(set(SCAN.findall(plan)))
    assert set(scanning) == set(SCANS), {
        "scans, not listed": {n: scanning[n] for n in set(scanning) - set(SCANS)},
        "listed, no longer scans": sorted(set(SCANS) - set(scanning))}


W = 3600
WINDOWS = {  # time-window query -> (params, the event label its filter must reach through an index)
    "recent_changes": ({"since": T1 - W, "until": T1}, "Change"),
    "anomalies_between": ({"services": ["svc:payments-gw"], "since": T1 - W, "until": T1}, "Anomaly"),
    "storm_alerts": ({"incident_id": "inc:x", "since": T1 - W, "until": T1 + W}, "Alert"),
}


@pytest.mark.parametrize("name", sorted(WINDOWS))
def test_a_time_window_query_starts_from_an_index(store, tenant, name):
    seed(store, tenant)
    params, label = WINDOWS[name]
    plan = _plan(store.tenant(tenant)._graph, get(name).cypher, params)
    assert not re.search(rf"Node By Label Scan \| \(\w+:{label}\)", plan), plan
    assert "Index Scan" in plan, plan


def test_query_plan_profiles_a_read_explains_a_write_without_running_it(store, tenant):
    """The Plan button's tool: a read is profiled (it runs again, each operation with its rows); a write is only
    explained, so asking for its plan changes nothing; the coordination queries are not offered."""
    from oncall_brain.agents.registry import ToolContext, call
    from oncall_brain.services import respond  # noqa: F401  (registers the tools)

    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    read = call("query_plan", ctx, {"query": "blast_radius",
                                    "params": {"service": "svc:payments-gw", "at": T1, "max_hops": 6}}).data
    assert read["ran"] and read["kind"] == "GRAPH.PROFILE" and any("Records produced" in ln for ln in read["plan"])
    before = store.tenant(tenant)._graph.ro_query("MATCH (e:Evidence) RETURN count(e)").result_set
    write = call("query_plan", ctx, {"query": "record_evidence", "params": {
        "hypothesis_id": "hyp:x", "evidence_id": "ev:x", "verdict": "supports", "reason": "r", "tag": "t", "path": [],
        "at": 1, "explained": [], "onset": None, "gaps": [], "red_before": None}}).data
    assert not write["ran"] and write["kind"] == "GRAPH.EXPLAIN"
    assert store.tenant(tenant)._graph.ro_query("MATCH (e:Evidence) RETURN count(e)").result_set == before
    with pytest.raises(ValueError, match="no product query named 'coord_claim'"):
        call("query_plan", ctx, {"query": "coord_claim"})
    with pytest.raises(ValueError, match="blast_radius needs its parameters: at, max_hops, service"):
        call("query_plan", ctx, {"query": "blast_radius"})
