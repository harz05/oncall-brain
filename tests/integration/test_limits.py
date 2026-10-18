"""The abuse limits end to end on a real FalkorDB (the counters live there): per-client throttles on the API and MCP,
the shared daily LLM budget, the concurrent-run cap, the body cap and the security headers."""

import json
import os
import time
import types
import uuid

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from oncall_brain import serve
from oncall_brain.api import app as app_module
from oncall_brain.api.app import app
from oncall_brain.api.guards import CSP
from oncall_brain.config import get_settings
from oncall_brain.datagen import ACTS
from oncall_brain.domain.planner import next_decision
from oncall_brain.mcp_server import build_server
from oncall_brain.mcp_server.__main__ import http_app
from oncall_brain.services import limits
from oncall_brain.wiring import make_store

pytestmark = pytest.mark.integration

NOW = 1_800_002_880  # 48 minutes into an hour, on a minute boundary: retries are 60 s and 12 minutes
LIMIT_ENV = ("RATE_LIMIT_PER_MIN", "WRITES_PER_MIN", "RUNS_PER_HOUR", "MAX_CONCURRENT_RUNS", "LLM_DAILY_TOKEN_CAP",
             "LLM_HOURLY_TOKEN_CAP", "MAX_BODY_BYTES", "LOCK_WAIT_SECONDS", "MCP_TOKEN", "API_TOKEN")
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}


@pytest.fixture
def env(monkeypatch, store):  # `store` skips the module when FalkorDB is down
    """env(NAME=value) for one test, with the limit clock frozen at NOW (windows are numbered from it, and every test
    uses fresh client addresses, so counts never leak between tests or runs)."""
    monkeypatch.setattr(limits, "time", types.SimpleNamespace(time=lambda: NOW))

    def set_env(**kv: object) -> None:
        for name in LIMIT_ENV:
            monkeypatch.delenv(name, raising=False)
        for k, v in kv.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()

    yield set_env
    monkeypatch.undo()
    get_settings.cache_clear()


def addr() -> str:
    return f"itest-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def client(target=app, **kw) -> TestClient:
    return TestClient(target, client=(addr(), 1), **kw)


@pytest.fixture
def seeded(store, tenant):
    c = client()
    assert c.post(f"/api/tenants/{tenant}/reset").status_code == 200
    return f"/api/tenants/{tenant}"


def refused(r, words: str, retry: int) -> bool:
    return r.status_code == 429 and r.json() == {"detail": words} and r.headers["Retry-After"] == str(retry)


def test_requests_writes_and_runs_each_trip_at_n_plus_1(env):
    env(RATE_LIMIT_PER_MIN=4)
    c = client()
    assert [c.get("/api/tools").status_code for _ in range(4)] == [200] * 4
    assert refused(c.get("/api/tools"), "Too many requests from your address: 4 per minute. Try again in 60 seconds.",
                   60)
    assert client().get("/api/tools").status_code == 200  # another address has its own window

    env(WRITES_PER_MIN=2)
    c, base = client(), "/api/tenants/nosuch"
    for _ in range(3):  # GETs are not writes
        assert c.get(f"{base}/alerts").status_code == 404
    # Ask is a write: it records the question in the asker's session
    assert c.post(f"{base}/tools/ask", json={"question": "who owns kafka"}).status_code == 404
    assert c.post(f"{base}/tools/nope", json={}).status_code == 404
    assert refused(c.post(f"{base}/alerts", json={}), "Too many writes from your address: 2 per minute. Try again in "
                   "60 seconds.", 60)  # the webhook is a write

    env(RUNS_PER_HOUR=4)
    c = client()
    assert c.post(f"{base}/alerts", json={}).status_code == 404  # no ?respond=true: a write, not a run
    assert c.post(f"{base}/alerts", params={"respond": "false"}, json={}).status_code == 404
    runs = [c.post(f"{base}/alerts/alert:x/respond"), c.post(f"{base}/alerts/alert:x/respond/stream"),
            c.post(f"{base}/alerts", params={"respond": "true"}, json={}), c.post("/api/tenants/Bad-Name/reset")]
    assert [r.status_code for r in runs] == [404, 404, 404, 422]  # counted before the route answers
    words = "Too many agent runs from your address: 4 per hour. Try again in 12 minutes."
    assert refused(c.post(f"{base}/alerts/alert:x/respond"), words, 720)
    assert refused(c.post(f"{base}/reset"), words, 720)

    env(RUNS_PER_HOUR=3)
    c = client()  # ?compare=memory replays the incident without memory: two runs
    assert c.post(f"{base}/alerts/alert:x/respond/stream", params={"compare": "memory"}).status_code == 404
    assert c.post(f"{base}/alerts/alert:x/respond").status_code == 404
    assert c.post(f"{base}/alerts/alert:x/respond").status_code == 429

    env(RATE_LIMIT_PER_MIN=1)  # an IPv6 client counts by its /64: a fresh address in it is no fresh bucket
    net = f"2001:db8:{os.getpid() % 0xffff:x}:{uuid.uuid4().hex[:4]}"
    assert TestClient(app, client=(f"{net}::1", 1)).get("/api/tools").status_code == 200
    assert TestClient(app, client=(f"{net}::2", 1)).get("/api/tools").status_code == 429


def test_a_cross_origin_write_is_refused_before_it_counts(env):
    """Any page a visitor opens can make their browser POST here; the 403 must not spend the visitor's quotas."""
    env(RUNS_PER_HOUR=1, WRITES_PER_MIN=1)
    c = client()
    for _ in range(3):
        r = c.post("/api/tenants/nosuch/reset", headers={"origin": "https://evil.example"})
        assert r.status_code == 403 and r.json() == {"detail": "cross-origin request refused"}
        assert r.headers["x-content-type-options"] == "nosniff"
    assert c.post("/api/tenants/Bad-Name/reset", headers={"origin": "http://testserver"}).status_code == 422
    assert c.get("/api/tools", headers={"origin": "https://evil.example"}).status_code == 200  # reads stay open


def test_a_write_behind_a_held_tenant_lock_gives_up_after_lock_wait_seconds(env, seeded, tenant, monkeypatch):
    """A waiter holds a server thread; waiting 120 s behind a 2-minute run let a burst of writes freeze the site."""
    env(LOCK_WAIT_SECONDS=0.3)
    short = make_store()
    monkeypatch.setattr(app_module, "store", lambda: short)
    with short.tenant(tenant).lock():  # an agent run in progress
        t0 = time.monotonic()
        r = client().post(f"{seeded}/tools/record_change", json={"service": "svc:checkout", "kind": "deploy",
                                                                 "summary": "a deploy"})
        assert r.status_code == 409 and "another agent run holds this tenant's lock" in r.json()["detail"]
        assert time.monotonic() - t0 < 5


def test_health_static_files_and_the_ui_are_never_throttled(env):
    env(RATE_LIMIT_PER_MIN=1, WRITES_PER_MIN=1, RUNS_PER_HOUR=1)
    c = client()
    for _ in range(3):
        assert c.get("/api/health").status_code == 200
        assert c.get("/web/app.js").status_code == 200 and c.get("/").status_code == 200
    with client(serve.app) as s:
        assert [s.get("/health").status_code for _ in range(3)] == [200] * 3
    assert c.get("/api/tools").status_code == 200 and c.get("/api/tools").status_code == 429


def test_x_forwarded_for_counts_only_from_a_trusted_proxy(env):
    """uvicorn's proxy headers decide the address (FORWARDED_ALLOW_IPS, default 127.0.0.1); the app never reads
    X-Forwarded-For itself, so a direct client cannot pick a fresh bucket per request."""
    env(RATE_LIMIT_PER_MIN=2)
    behind = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")
    direct = TestClient(behind, client=(addr(), 1))
    codes = [direct.get("/api/tools", headers={"X-Forwarded-For": addr()}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    proxy, a, b = TestClient(behind, client=("127.0.0.1", 1)), addr(), addr()
    assert [proxy.get("/api/tools", headers={"X-Forwarded-For": a}).status_code for _ in range(3)] == [200, 200, 429]
    assert proxy.get("/api/tools", headers={"X-Forwarded-For": b}).status_code == 200  # another real client


class Metered:
    """A paid model as the budget sees it: wiring's run_token_cap marks it metered; each decision reports usage."""

    name = "metered via test"
    run_token_cap = 0

    def decide(self, role, board, tools):
        return next_decision(role, board).model_copy(update={"by": "metered", "usage": 1000})


def test_the_daily_llm_budget_hands_the_next_run_to_the_rules_and_health_shows_it(env, seeded, store, monkeypatch):
    key = f"oncall_brain:itest_llm_tokens:{uuid.uuid4().hex}:"
    monkeypatch.setattr(limits, "DAILY_PREFIX", key)
    monkeypatch.setattr(app_module, "llm", lambda: Metered())
    env(LLM_DAILY_TOKEN_CAP=3000)
    try:
        c = client()
        assert c.get("/api/health").json()["llm_budget"] == {"cap": 3000, "used_today": 0, "hourly_cap": 0,
                                                             "used_this_hour": 0}
        first = c.post(f"{seeded}/alerts/{ACTS[1]}/respond").json()
        decided = [s for s in first["steps"] if s["tool"] != "open_incident"]
        assert [s["by"] for s in decided[:4]] == ["metered"] * 3 + ["rules"] and first["llm_tokens"] == 3000
        reason = "LLM fallback: today's LLM budget (3,000 tokens) is spent; the rules planner decides until 00:00 UTC."
        assert decided[3]["reason"].startswith(reason)
        assert first["outcome"]["root_cause"]["change"] == "chg:pgw-pool-1"  # the rules finish the incident
        assert c.get("/api/health").json()["llm_budget"]["used_today"] == 3000

        second = c.post(f"{seeded}/alerts/{ACTS[2]}/respond").json()
        decided = [s for s in second["steps"] if s["tool"] != "open_incident"]
        assert decided and all(s["by"] == "rules" and s["reason"].startswith(reason) for s in decided)
        assert second["llm_tokens"] == 0
    finally:
        store.db.connection.delete(limits.DailyBudget.key())


def test_a_full_run_slot_is_429_on_the_api_and_the_same_words_in_the_stream_and_over_mcp(env, seeded, store, tenant):
    env(MAX_CONCURRENT_RUNS=2)
    busy = "2 agent runs are already in progress; try again in a minute"
    c = client()
    with limits.run_slot(2), limits.run_slot(2):  # two runs in progress in this process
        r = c.post(f"{seeded}/alerts/{ACTS[1]}/respond")
        assert r.status_code == 429 and r.json() == {"detail": busy} and r.headers["Retry-After"] == "60"
        with c.stream("POST", f"{seeded}/alerts/{ACTS[1]}/respond/stream") as s:
            assert [json.loads(line) for line in s.iter_lines() if line] == [{"error": busy}]

        async def over_mcp():
            async with Client(build_server(store)) as m:
                return await m.call_tool("respond_to_alert", {"tenant": tenant, "alert_id": ACTS[1]})

        res = anyio.run(over_mcp)
        assert res.is_error and res.content[0].text == busy
    assert c.post(f"{seeded}/alerts/{ACTS[1]}/respond").status_code == 200  # slots free again


def test_a_body_over_the_cap_is_413_by_length_and_when_chunked_on_the_api_and_mcp(env):
    env()  # MAX_BODY_BYTES defaults to 65,536
    c, url = client(), "/api/tenants/nosuch/tools/ask"
    words = {"detail": "request body too large: the limit is 65,536 bytes"}
    big = json.dumps({"question": "x" * 70_000})
    r = c.post(url, content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json() == words
    chunked = c.post(url, content=(big[i:i + 10_000].encode() for i in range(0, len(big), 10_000)),
                     headers={"content-type": "application/json"})
    assert chunked.status_code == 413 and chunked.json() == words and "content-length" not in chunked.request.headers
    assert c.post(url, json={"question": "who owns kafka"}).status_code == 404  # a normal body passes
    for path in ("/web/", "/docs", "/"):  # every path, not only /api/: the guard reads any request's body
        assert c.post(path, content=big).status_code == 413
    with client(serve.app) as s:  # POST /health falls through to the API
        assert s.post("/health", content=big).status_code == 413
    with TestClient(http_app("127.0.0.1"), base_url="http://localhost:8001", client=(addr(), 1)) as m:
        assert m.post("/mcp", content=big, headers=MCP_HEADERS).status_code == 413
        assert m.post("/mcp", content=(big[i:i + 10_000].encode() for i in range(0, len(big), 10_000)),
                      headers=MCP_HEADERS).status_code == 413
        assert m.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS).status_code == 200


def test_security_headers_on_the_ui_static_files_and_health_and_hsts_only_over_https(env):
    env()
    c = client()
    for r in (c.get("/", follow_redirects=False), c.get("/web/"), c.get("/api/health")):
        assert r.headers["content-security-policy"] == CSP and r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer" and "camera=()" in r.headers["permissions-policy"]
        assert "strict-transport-security" not in r.headers
    assert client(base_url="https://testserver").get("/api/health").headers["strict-transport-security"] == (
        "max-age=31536000")
    with client(serve.app) as s:  # the deployment app: its own routes too, once each
        for r in (s.get("/health"), s.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS), s.get("/web/")):
            assert r.headers["x-content-type-options"] == "nosniff" and r.headers.get_list(
                "content-security-policy") == [CSP]


def _mcp_session(m: TestClient) -> dict[str, str]:
    r = m.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    headers = {**MCP_HEADERS, "mcp-session-id": r.headers["mcp-session-id"], "mcp-protocol-version": "2025-06-18"}
    m.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
    return headers


def _call(m: TestClient, headers: dict[str, str], name: str, args: dict) -> dict:
    r = m.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                              "params": {"name": name, "arguments": args}})
    return json.loads(next(line[5:] for line in r.text.splitlines() if line.startswith("data:")))["result"]


def test_mcp_over_http_counts_requests_and_runs_per_client(env):
    env(RUNS_PER_HOUR=1)
    with TestClient(http_app("127.0.0.1"), base_url="http://localhost:8001", client=(addr(), 1)) as m:
        headers = _mcp_session(m)
        first = _call(m, headers, "reset_tenant", {"tenant": "Bad-Name"})  # refused by the store, counted as a run
        assert first["isError"] and "tenant must match" in first["content"][0]["text"]
        assert not _call(m, headers, "blast_radius", {"tenant": "Bad-Name", "service": "svc:x"})["content"][0][
            "text"].startswith("Too many")  # a plain tool is not a run
        second = _call(m, headers, "respond_to_alert", {"tenant": "Bad-Name", "alert_id": "alert:x"})
        assert second["isError"] and second["content"][0]["text"] == (
            "Too many agent runs from your address: 1 per hour. Try again in 12 minutes.")

    env(WRITES_PER_MIN=1)
    with TestClient(http_app("127.0.0.1"), base_url="http://localhost:8001", client=(addr(), 1)) as m:
        headers = _mcp_session(m)
        first = _call(m, headers, "record_change", {"tenant": "Bad-Name", "service": "svc:x", "kind": "deploy",
                                                    "summary": "s"})
        assert "tenant must match" in first["content"][0]["text"]  # counted as a write, then refused by the store
        assert "Too many" not in _call(m, headers, "service_map", {"tenant": "Bad-Name"})["content"][0]["text"]
        again = _call(m, headers, "ask", {"tenant": "Bad-Name", "question": "who owns kafka"})  # Ask writes too
        assert again["isError"] and again["content"][0]["text"] == (
            "Too many writes from your address: 1 per minute. Try again in 60 seconds.")

    env(RATE_LIMIT_PER_MIN=2)
    with TestClient(http_app("127.0.0.1"), base_url="http://localhost:8001", client=(addr(), 1)) as m:
        codes = [m.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS) for _ in range(3)]
        assert [r.status_code for r in codes] == [200, 200, 429] and codes[2].headers["Retry-After"] == "60"
        assert codes[2].json()["detail"].startswith("Too many requests from your address: 2 per minute.")
