"""The rewritten traversals return exactly what the path-enumerating originals did (queries/reference.cypher):
on the demo graph at the three act times (and before checkout -> legacy-billing was retired), on 20 eval scenarios
and on a 100-service hub-heavy bench graph, with every service swept as origin and target where the reference is
cheap enough to sweep."""

import pytest

from oncall_brain.adapters.falkordb.queries import all_queries
from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.datagen import ACTS, DAY, T1
from oncall_brain.domain.planner import RECALL_MIN_SCORE, WINDOW
from oncall_brain.scenarios import scenario
from oncall_brain.services.respond import resolve, respond
from oncall_brain.services.seeding import load, seed
from oncall_brain.services.tools import incident_id_for
from scripts.bench import cases, org, same

pytestmark = pytest.mark.integration


def check(repo, name: str, **params) -> list[dict]:
    ref, new = repo.read(f"{name}_reference", **params).rows, repo.read(name, **params).rows
    assert same(name, ref, new), f"{name} differs from {name}_reference for {params}"
    return new


def sweep_at(repo, at: int, origins: list[str]) -> None:
    """Every service as blast_radius / storm_unexplained / live_paths target (live_paths from `origins`, or from
    every service), every pair for storm_upstream and depends_among, all at time `at`."""
    services = sorted(r["id"] for r in repo.read("service_map", at=at).rows)
    check(repo, "storm_upstream", services=services, at=at, since=at - WINDOW)
    check(repo, "depends_among", services=services, at=at)
    for target in services:
        check(repo, "blast_radius", service=target, at=at, max_hops=6)
        check(repo, "storm_unexplained", services=services, target=target, at=at)
        for origin in origins or services:
            check(repo, "live_paths", origin=origin, target=target, at=at)


def sweep(repo, incident_id: str, all_origins: bool = False) -> dict[str, list[dict]]:
    """The incident's own queries, then sweep_at its alert time."""
    head = repo.read("incident_head", incident_id=incident_id).rows[0]
    out = {"recall_similar": check(repo, "recall_similar", incident_id=incident_id),
           "path_suspects": check(repo, "path_suspects", incident_id=incident_id, window=WINDOW),
           "memory_suspects": check(repo, "memory_suspects", incident_id=incident_id, window=WINDOW,
                                    min_score=RECALL_MIN_SCORE)}
    sweep_at(repo, head["at"], [] if all_origins else [head["service"]])
    return out


def test_demo_graph_at_each_act(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    # checkout's shortest path to legacy-billing is the retired edge: the sweeps take the fallback branch.
    assert repo.read("any_path", origin="svc:checkout", target="svc:legacy-billing").rows[0]["retired_at"][0]
    sweep_at(repo, T1 - 4 * DAY, [])  # the day before it was retired, the same edge is live
    act1 = respond(repo, ACTS[1], MockProvider())
    assert sweep(repo, act1["incident_id"], all_origins=True)["path_suspects"]
    resolve(repo, act1["incident_id"], "chg:pgw-pool-1")  # act 2 then recalls act 1: memory_suspects has a row
    act2 = respond(repo, ACTS[2], MockProvider())
    assert sweep(repo, act2["incident_id"], all_origins=True)["memory_suspects"]
    act3 = respond(repo, ACTS[3], MockProvider())
    sweep(repo, act3["incident_id"], all_origins=True)


def test_odd_inputs(store, tenant):
    """Repeated, unknown and missing ids, empty lists, a service as its own origin and target."""
    seed(store, tenant)
    repo = store.tenant(tenant)
    svc = ["svc:checkout", "svc:checkout", "svc:nope", "svc:search", "svc:legacy-billing"]
    for at in (T1, T1 - 4 * DAY):
        check(repo, "storm_upstream", services=svc, at=at, since=at - WINDOW)
        check(repo, "depends_among", services=svc, at=at)
        check(repo, "depends_among", services=[], at=at)
        for target in ("svc:payments-gw", "svc:nope", "svc:checkout"):
            check(repo, "storm_unexplained", services=svc, target=target, at=at)
            check(repo, "storm_unexplained", services=[], target=target, at=at)
            check(repo, "live_paths", origin="svc:checkout", target=target, at=at)
            check(repo, "live_paths", origin="svc:nope", target=target, at=at)
            check(repo, "blast_radius", service=target, at=at, max_hops=6)
    for name in ("path_suspects", "memory_suspects", "recall_similar"):  # no such incident
        check(repo, name, incident_id="inc:nope", window=WINDOW, min_score=RECALL_MIN_SCORE)


@pytest.mark.parametrize("n", range(1, 21))
def test_eval_scenario(store, tenant, n):
    sc = scenario(n)
    repo = store.tenant(tenant)
    load(repo, sc["data"])
    inc = incident_id_for(sc["alert_id"])
    repo.write("open_incident", alert_id=sc["alert_id"], incident_id=inc)
    if recalled := repo.read("recall_similar_reference", incident_id=inc).rows:
        repo.write("record_recalls", incident_id=inc, rows=recalled)
    sweep(repo, inc)


def test_hub_heavy_bench_graph(store, tenant):
    """100 services with cycles, several retired edges, edges not live yet and many equally short paths into the
    hubs. The reference is too slow to sweep every pair here, so: the bench's cases, every service's blast radius
    and closure, and the live paths from the alerting service to every service (where ties decide the result)."""
    data, m = org(100)
    repo = store.tenant(tenant)
    load(repo, data)
    for _, name, params in cases(repo, m):
        if f"{name}_reference" in all_queries():  # who_knows and ask's queries were not rewritten
            check(repo, name, **params)
    services = sorted(d["id"] for d in data["services"])
    check(repo, "storm_upstream", services=services, at=m["at"], since=m["at"] - WINDOW)
    for s in services:
        check(repo, "blast_radius", service=s, at=m["at"], max_hops=6)
        check(repo, "live_paths", origin=m["origin"], target=s, at=m["at"])
