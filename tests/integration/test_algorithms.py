"""Graph algorithms that decide something. Criticality is PageRank over the dependencies live at alert time
(`algo.pageRank` on a point-in-time projection): it orders the blast radius and decides which impacted teams get a
heads-up first."""

import pytest

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.datagen import ACTS, T1
from oncall_brain.services.respond import respond, run_tool
from oncall_brain.services.seeding import seed

pytestmark = pytest.mark.integration

DAY = 24 * 3600


def _rows(repo, cypher: str, **params) -> list[dict]:
    res = repo._graph.ro_query(cypher, params)
    return [dict(zip([h[1] for h in res.header], r, strict=False)) for r in res.result_set]


def test_criticality_comes_from_the_dependencies_live_at_alert_time_not_from_history(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    first = run_tool(repo, "blast_radius", {"service": "svc:payments-gw", "at": T1})
    assert [r["rank"] for r in first.data] == list(range(1, len(first.data) + 1))
    assert first.data == sorted(first.data, key=lambda r: (r["tier"], -r["score"], r["hops"], r["service"]))
    assert [q.name for q in first.queries] == ["blast_radius", "topology_at", "project_topology", "criticality"]
    assert "algo.pageRank" in first.queries[3].cypher
    live = _rows(repo, "MATCH ()-[r:DEPENDS_ON]->() WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR "
                       "r.valid_to > $at) RETURN count(r) AS n", at=T1)[0]["n"]
    assert first.queries[2].rows[0]["edges"] == live  # the projection holds exactly the live edges
    assert not [g for g in store.db.list_graphs() if g.startswith("scratch_")]  # and is dropped afterwards

    # History that must not count: until yesterday every service depended on the least critical impacted service,
    # and from tomorrow every service will again. Over the whole graph PageRank crowns it; at alert time it has
    # not one live dependent, so its place in the order does not move.
    target = first.data[-1]["service"]
    repo._graph.query("MATCH (s:Service), (t:Service {id: $t}) WHERE s.id <> t.id "
                      "CREATE (s)-[:DEPENDS_ON {valid_from: $from, valid_to: $to}]->(t)",
                      {"t": target, "from": T1 - 30 * DAY, "to": T1 - DAY})
    repo._graph.query("MATCH (s:Service), (t:Service {id: $t}) WHERE s.id <> t.id "
                      "CREATE (s)-[:DEPENDS_ON {valid_from: $from}]->(t)", {"t": target, "from": T1 + DAY})
    whole = {r["service"]: r["score"] for r in _rows(
        repo, "CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node, score RETURN node.id AS service, score")}
    assert max(whole, key=whole.get) == target
    again = run_tool(repo, "blast_radius", {"service": "svc:payments-gw", "at": T1})
    assert [r["service"] for r in again.data] == [r["service"] for r in first.data]
    assert again.data[-1]["service"] == target
    assert again.queries[2].rows[0]["edges"] == live


def test_comms_warns_the_most_critical_impacted_teams_first_and_skips_the_paged_ones(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    run = respond(repo, ACTS[1], MockProvider())
    step = next(s for s in run["steps"] if s.tool == "warn_owners")
    assert step.role == "comms"
    warned = run["outcome"]["warned"]
    assert 1 <= len(warned) <= 2
    paged_teams = {p["team"] for p in run["outcome"]["paged"]}
    assert paged_teams and not {w["team"] for w in warned} & paged_teams
    assert [w["rank"] for w in warned] == sorted(w["rank"] for w in warned)
    ranks = {r["service"]: r["rank"] for r in _rows(
        repo, "MATCH (:Incident {id: $i})-[x:IMPACTS]->(s:Service) WHERE x.rank IS NOT NULL "
              "RETURN s.id AS service, x.rank AS rank", i=run["incident_id"])}
    assert ranks and warned[0]["rank"] == min(ranks[s] for s in ranks if s in {w["service"] for w in warned})
    assert "Heads-up (most relied-on first): " + warned[0]["handle"] in run["outcome"]["update_text"]
    # a second run does not warn anyone twice
    respond(repo, ACTS[1], MockProvider())
    assert _rows(repo, "MATCH (:Incident {id: $i})-[w:WARNED]->() RETURN count(w) AS n",
                 i=run["incident_id"])[0]["n"] == len(warned)
