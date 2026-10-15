"""The HTTP contract the web UI relies on, end to end against a real FalkorDB (skipped if none is reachable)."""

import os

import pytest
from fastapi.testclient import TestClient

from oncall_brain.api.app import app
from oncall_brain.datagen import ACTS

pytestmark = pytest.mark.integration


@pytest.fixture
def api(store):  # `store` (conftest) skips the module when FalkorDB is down
    t = f"api_test_{os.getpid()}"
    store.drop(t)
    yield TestClient(app), f"/api/tenants/{t}"
    store.drop(t)


def test_two_act_story_over_http(api):
    c, base = api
    assert c.post(f"{base}/reset").json()["status"] == "seeded"
    assert c.post(f"{base}/reset").json()["status"] == "restored"
    assert [a["id"] for a in c.get(f"{base}/alerts").json()] == [ACTS[1], ACTS[2]]

    act1 = c.post(f"{base}/alerts/{ACTS[1]}/respond").json()
    o = act1["outcome"]
    assert (len(act1["steps"]), o["investigator_calls"], o["hypotheses_checked"]) == (17, 8, 5)
    assert o["root_cause"]["change"] == "chg:pgw-pool-1"
    assert o["root_cause"]["live_path"] == ["svc:checkout", "svc:payments", "svc:payments-gw"]
    assert o["baseline_pick"]["change"] == "chg:search-420" and not o["baseline_correct"]
    assert act1["steps"][1]["queries"][0]["name"] == "incident_board"
    assert len(c.get(f"{base}/incidents/{act1['incident_id']}/steps").json()) == 17

    res = c.post(f"{base}/incidents/{act1['incident_id']}/resolve", json={"change_id": "chg:pgw-pool-1"}).json()
    assert res["data"]["runbook"] == "rb:payments-gw:config"

    warm = c.post(f"{base}/alerts/{ACTS[2]}/respond").json()
    o = warm["outcome"]
    assert (len(warm["steps"]), o["investigator_calls"], o["hypotheses_checked"]) == (12, 3, 1)
    assert o["memory"]["solved_by_memory"]

    c.post(f"{base}/reset")
    cold = c.post(f"{base}/alerts/{ACTS[2]}/respond").json()["outcome"]
    assert (cold["investigator_calls"], cold["hypotheses_checked"]) == (5, 3)


def test_graph_tools_and_errors(api):
    c, base = api
    assert c.get(f"{base}/alerts").status_code == 404  # tenant not seeded yet
    c.post(f"{base}/reset")
    g = c.get(f"{base}/graph").json()
    assert all(e["target"] for e in g["edges"])
    assert {"source": "svc:checkout", "target": "svc:legacy-billing", "live": False} in g["edges"]
    assert "service_map" in {t["name"] for t in c.get("/api/tools").json()}
    path = c.post(f"{base}/tools/dependency_path", json={"from_service": "svc:checkout",
                                                          "to_service": "svc:payments-gw"}).json()
    assert path["data"] == ["svc:checkout", "svc:payments", "svc:payments-gw"]

    assert c.post(f"{base}/alerts/alert:nope/respond").status_code == 404
    assert c.get("/api/tenants/Bad-Name/alerts").status_code == 422
    assert c.post(f"{base}/tools/nope", json={}).status_code == 404
    bad = c.post(f"{base}/tools/dependency_path", json={})
    assert bad.status_code == 422 and isinstance(bad.json()["detail"], str)
    assert c.get("/api/health").json()["falkordb"] is True


def test_index_serves_the_web_ui(api):
    c, _ = api
    r = c.get("/")
    assert r.status_code == 200 and "/web/app.js" in r.text
    assert c.get("/web/app.js").status_code == 200
