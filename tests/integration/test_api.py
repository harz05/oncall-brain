"""The HTTP contract the web UI relies on, end to end against a real FalkorDB (skipped if none is reachable)."""

import json
import os
import re

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ResponseError

from oncall_brain.agents.loop import STORED_PARAMS_BUDGET
from oncall_brain.api import app as app_module
from oncall_brain.api.app import app
from oncall_brain.config import get_settings
from oncall_brain.datagen import ACTS, T1
from oncall_brain.domain.models import cypher_sha

pytestmark = pytest.mark.integration


@pytest.fixture
def api(store):  # `store` (conftest) skips the module when FalkorDB is down
    t = f"api_test_{os.getpid()}"
    store.drop(t)
    yield TestClient(app), f"/api/tenants/{t}"
    store.drop(t)


@pytest.fixture
def env(monkeypatch):
    """env(NAME=value, ...) for one test; cached settings and planner are rebuilt around it."""
    def set_env(**kv: object) -> None:
        for k, v in kv.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()
        app_module.llm.cache_clear()

    yield set_env
    monkeypatch.undo()
    get_settings.cache_clear()
    app_module.llm.cache_clear()


def test_two_act_story_over_http(api):
    c, base = api
    assert c.post(f"{base}/reset").json()["status"] == "seeded"
    assert c.post(f"{base}/reset").json()["status"] == "restored"
    alerts = [a["id"] for a in c.get(f"{base}/alerts").json()]
    assert alerts[:2] == [ACTS[1], ACTS[2]] and ACTS[3] in alerts

    # Exact step counts belong to the planner tests; here: the shape the UI reads, and warm beats cold.
    act1 = c.post(f"{base}/alerts/{ACTS[1]}/respond").json()
    o = act1["outcome"]
    assert o["root_cause"]["change"] == "chg:pgw-pool-1"
    assert o["root_cause"]["live_path"] == ["svc:checkout", "svc:payments", "svc:payments-gw"]
    assert o["baseline_pick"]["change"] == "chg:search-420" and not o["baseline_correct"]
    assert act1["steps"][1]["queries"][0]["name"] == "incident_board"
    assert len(c.get(f"{base}/incidents/{act1['incident_id']}/steps").json()) == len(act1["steps"])

    res = c.post(f"{base}/incidents/{act1['incident_id']}/resolve", json={"change_id": "chg:pgw-pool-1"}).json()
    assert res["data"]["runbook"] == "rb:payments-gw:config"

    warm_run = c.post(f"{base}/alerts/{ACTS[2]}/respond").json()
    warm = warm_run["outcome"]
    assert warm["memory"]["solved_by_memory"]
    # Reopened from the graph (no live trace), the incident still knows what memory did for it.
    stored = c.get(f"{base}/incidents/{warm_run['incident_id']}").json()["outcome"]["memory"]
    assert stored["solved_by_memory"] and stored["recalled"][0]["incident"] == act1["incident_id"]
    assert stored["recalled"][0]["runbook_title"]

    c.post(f"{base}/reset")
    cold = c.post(f"{base}/alerts/{ACTS[2]}/respond").json()["outcome"]
    assert cold["investigator_calls"] > warm["investigator_calls"]
    assert cold["hypotheses_checked"] > warm["hypotheses_checked"]


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
    clash = c.post(f"{base}/tools/record_ticket", json={"title": "x", "text": "y", "status": "open", "key": "CR-992",
                                                        "id": "ticket:jira-77"})  # bad input (422), not unknown (404)
    assert clash.status_code == 422 and "makes the id ticket:CR-992" in clash.json()["detail"]
    assert c.get("/api/health").json()["falkordb"] is True


def test_index_serves_the_web_ui(api):
    c, _ = api
    r = c.get("/?offline=1")  # redirects to /web/ (query kept), which serves index.html
    assert r.status_code == 200 and str(r.url).endswith("/web/?offline=1") and 'src="app.js"' in r.text
    assert c.get("/web/app.js").status_code == 200


def test_nul_input_and_falkordb_errors_are_not_500(api, monkeypatch):
    c, base = api
    assert c.get(f"{base}/incidents/a%00b/steps").status_code == 422
    assert c.post(f"{base}/incidents/i/resolve", json={"change_id": "a\x00b"}).status_code == 422

    def fork_failed() -> list[str]:
        raise ResponseError("GRAPH.COPY failed, could not fork\nerrCtx: MATCH (n) RETURN n")

    monkeypatch.setattr(app_module.store(), "tenants", fork_failed)
    r = c.get("/api/tenants")
    assert r.status_code == 503 and "could not fork" in r.json()["detail"] and "MATCH" not in r.json()["detail"]


def test_bad_llm_provider_keeps_health_up_and_respond_says_503(api, env):
    c, base = api
    c.post(f"{base}/reset")
    env(LLM_PROVIDER="nope", LLM_API_KEY="k", LLM_BASE_URL="")
    h = c.get("/api/health").json()
    assert h["ok"] is False and h["planner"].startswith("<error: planner misconfigured")
    r = c.post(f"{base}/alerts/{ACTS[1]}/respond")
    assert r.status_code == 503 and "LLM_PROVIDER" in r.json()["detail"]


def test_tenant_cap_blocks_new_tenants_only(api, env):
    c, base = api
    c.post(f"{base}/reset")
    env(MAX_TENANTS=1)  # our tenant already exists, so any new one is over the cap
    assert c.post(f"{base}/reset").json()["status"] == "restored"
    r = c.post(f"/api/tenants/api_cap_{os.getpid()}/reset")
    assert r.status_code == 429 and "MAX_TENANTS" in r.json()["detail"]


def test_api_token_guards_api_but_not_health_or_ui(api, env):
    c, _ = api
    env(API_TOKEN="s3cret")
    assert c.get("/api/tools").status_code == 401
    assert c.get("/api/tools", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/api/tools", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert c.get("/api/health").status_code == 200 and c.get("/").status_code == 200


def test_cross_origin_writes_and_unknown_hosts_are_refused(api):
    c, base = api
    tool = f"{base}/tools/nope"  # 404 (no such tenant) once past the guards; never touches the graph
    assert c.post(tool, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post(tool, headers={"Origin": "null"}).status_code == 403
    assert c.post(tool, headers={"Origin": "http://testserver"}).status_code == 404
    assert c.post(tool).status_code == 404  # no Origin: curl, scripts
    assert c.get("/api/tools", headers={"Origin": "https://evil.example"}).status_code == 200  # reads stay open
    assert c.get("/api/tools", headers={"Host": "evil.example"}).status_code == 400  # DNS rebinding



def test_inbox_stream_webhook_and_stored_incident(api):
    """The product surfaces: inbox rows with state, the step stream, a stored incident, the alert webhook."""
    c, base = api
    c.post(f"{base}/reset")
    rows = {a["id"]: a for a in c.get(f"{base}/alerts").json()}
    assert rows[ACTS[1]]["incident"] is None and rows[ACTS[1]]["has_cause"] is False

    with c.stream("POST", f"{base}/alerts/{ACTS[1]}/respond/stream") as r:
        lines = [json.loads(line) for line in r.iter_lines() if line]
    steps = [x["step"] for x in lines if "step" in x]
    result = [x["result"] for x in lines if "result" in x][0]
    assert lines[-1] is result or "result" in lines[-1]
    assert len(steps) == len(result["steps"]) and steps[0]["tool"] == "open_incident" and steps[0]["by"] == "rules"
    assert result["outcome"]["confidence"]["level"] == "high" and result["outcome"]["sources"]
    assert result["slack"] == "off" and result["llm_tokens"] == 0  # the rule planner spends nothing

    rows = {a["id"]: a for a in c.get(f"{base}/alerts").json()}
    row = rows[ACTS[1]]
    assert row["incident"] == result["incident_id"] and row["has_cause"] and row["has_update"]
    inc = c.get(f"{base}/incidents/{result['incident_id']}").json()
    assert inc["status"] == "open" and inc["outcome"]["root_cause"]["change"] == "chg:pgw-pool-1"
    assert inc["outcome"]["root_cause"]["author"] == "Sana Brandt" and inc["outcome"]["confidence"]["level"] == "high"
    assert len(inc["steps"]) == len(steps) and {s["by"] for s in inc["steps"]} == {"rules"}

    # The webhook: a quiet week earlier, so nothing on the story's paths is a suspect.
    quiet = T1 - 7 * 24 * 3600
    cart = {"service": "svc:cart", "symptom": "errors", "name": "cart 5xx above 1%", "at": quiet}
    r = c.post(f"{base}/alerts", json=cart)
    assert r.status_code == 200 and r.json()["alert"].startswith("alert:cart-errors-")
    assert {a["id"]: a for a in c.get(f"{base}/alerts").json()}[r.json()["alert"]]["incident"] is None
    run = c.post(f"{base}/alerts", params={"respond": "true"},
                 json={"service": "svc:refunds", "symptom": "latency", "name": "refunds slow", "at": quiet + 60}).json()
    assert run["incident_id"].startswith("inc:refunds-latency-") and run["outcome"]["update_text"]
    stored = c.get(f"{base}/incidents/{run['incident_id']}").json()
    assert stored["outcome"]["confidence"]["level"] in ("none", "high", "medium")
    assert c.post(f"{base}/alerts", json={"service": "svc:nope", "symptom": "errors", "name": "x"}).status_code == 404


def test_a_stored_incident_keeps_the_queries_behind_every_step(api):
    """"Show me why" on an incident opened from the inbox: each stored step names its queries, with their row counts,
    ms, params and Cypher sha, and the Cypher comes from the catalogue endpoint, whose sha says it is the text that
    ran. The params cap is tests/unit/test_stored_queries.py."""
    c, base = api
    c.post(f"{base}/reset")
    run = c.post(f"{base}/alerts/{ACTS[1]}/respond").json()
    stored = c.get(f"{base}/incidents/{run['incident_id']}").json()["steps"]
    assert len(stored) == len(run["steps"])
    for live, kept in zip(run["steps"], stored, strict=True):
        assert [q["name"] for q in kept["queries"]] == [q["name"] for q in live["queries"]]
        assert [q["row_count"] for q in kept["queries"]] == [len(q["rows"]) for q in live["queries"]]
        assert [q["readonly"] for q in kept["queries"]] == [q["readonly"] for q in live["queries"]]
        assert sum(len(json.dumps(q["params"])) for q in kept["queries"] if q["params"] is not None) \
            <= STORED_PARAMS_BUDGET
        for lq, kq in zip(live["queries"], kept["queries"], strict=True):
            assert kq["params"] in (None, lq["params"]) and kq["sha"] == cypher_sha(lq["cypher"])
    board = stored[1]["queries"][0]
    assert board["name"] == "incident_board" and board["params"]["incident_id"] == run["incident_id"]
    assert c.get(f"{base}/incidents/{run['incident_id']}/steps").json() == stored

    q = c.get("/api/queries/incident_board").json()
    assert q["cypher"] == run["steps"][1]["queries"][0]["cypher"] and q["purpose"] and q["sha"] == board["sha"]
    assert c.get("/api/queries/no_such_query").status_code == 404


def test_the_documented_webhook_sample_finds_the_cause_on_the_demo_company(api):
    """The curl on the Connect page and in docs/MCP.md is what a judge pastes first: it must land on the story."""
    c, base = api
    c.post(f"{base}/reset")
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    samples = [re.search(r"-d '(\{.*?\})'", open(os.path.join(root, f)).read()).group(1)
               for f in ("docs/MCP.md", "web/app.js")]
    assert samples[0] == samples[1]  # the docs and the page show the same body
    body = json.loads(samples[0])
    assert body["at"] == T1
    run = c.post(f"{base}/alerts", params={"respond": "true"}, json=body).json()
    assert run["outcome"]["root_cause"]["change"] == "chg:pgw-pool-1"
    assert run["outcome"]["confidence"]["level"] == "high"
