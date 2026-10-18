"""Regression tests for the hardening commit (f66b01f) that need no FalkorDB: health with the database down, lock
contention, Slack results, bearer checks, the storm projection guard, origin-aware leading cause, the MCP catalogue
and the plugin launcher's hint."""

import os
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import anyio
import httpx
import pytest
from mcp import Client
from redis.exceptions import LockError
from starlette.testclient import TestClient

from oncall_brain.adapters import slack
from oncall_brain.agents.registry import ToolContext
from oncall_brain.api import app as app_module
from oncall_brain.config import get_settings
from oncall_brain.domain.verdict import leading
from oncall_brain.mcp_server import build_server, catalogue
from oncall_brain.mcp_server.__main__ import http_app
from oncall_brain.services.tools import _storm_components

ROOT = Path(__file__).resolve().parents[2]
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


@pytest.fixture
def env(monkeypatch):
    """env(NAME=value, ...): settings, the API's store and its planner are rebuilt around the test."""
    def set_(**kv: str) -> None:
        for k in ("MCP_TOKEN", "API_TOKEN", "SLACK_WEBHOOK_URL", "FALKORDB_URL"):
            monkeypatch.setenv(k, "")
        for k, v in kv.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        app_module.store.cache_clear()
        app_module.llm.cache_clear()

    yield set_
    monkeypatch.undo()
    get_settings.cache_clear()
    app_module.store.cache_clear()
    app_module.llm.cache_clear()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_health_is_503_with_the_reason_when_falkordb_is_unreachable(env):
    from oncall_brain import serve  # here, so the other tests import with a pre-fix api/app.py

    env(FALKORDB_HOST="127.0.0.1", FALKORDB_PORT=str(_closed_port()))
    for client, path in ((TestClient(app_module.app), "/api/health"), (TestClient(serve.app), "/health")):
        r = client.get(path)
        body = r.json()
        assert r.status_code == 503, path
        assert body["ok"] is False and body["falkordb"] is False, path
        assert body["falkordb_error"].startswith("ConnectionError"), path


def test_a_held_tenant_lock_is_409_on_the_api_not_a_database_outage(env, monkeypatch):
    env()

    def busy(*_, **__):
        raise LockError("Unable to acquire lock within the time specified")

    monkeypatch.setattr(app_module, "store", lambda: None)
    monkeypatch.setattr(app_module, "reset", busy)
    r = TestClient(app_module.app).post("/api/tenants/acme/reset")
    assert r.status_code == 409
    assert r.json()["detail"].startswith("another agent run holds this tenant's lock")


class _BusyStore:
    def tenants(self) -> list[str]:
        return ["busy"]

    def lock(self, tenant: str):
        raise LockError("Unable to acquire lock within the time specified")


def test_a_held_tenant_lock_is_a_busy_tool_error_over_mcp():
    async def go():
        async with Client(build_server(_BusyStore())) as c:
            return await c.call_tool("reset_tenant", {"tenant": "busy"})

    out = anyio.run(go)
    assert out.is_error and out.content[0].text.startswith("tenant 'busy' is busy: another agent run holds its lock")


def test_slack_post_says_what_happened(env, monkeypatch):
    url = "https://hooks.slack.test/services/SECRET"
    env()
    assert slack.post("update") == "off"
    env(SLACK_WEBHOOK_URL=url)
    assert slack.post(None) == "nothing to post" and slack.post("") == "nothing to post"

    def answer(status: int):
        return lambda u, **_: httpx.Response(status, request=httpx.Request("POST", u))

    monkeypatch.setattr(slack.httpx, "post", answer(200))
    assert slack.post("update") == "posted"
    monkeypatch.setattr(slack.httpx, "post", answer(404))
    assert slack.post("update") == "failed: Slack answered 404 (is SLACK_WEBHOOK_URL a live incoming webhook?)"

    def refused(u, **_):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(slack.httpx, "post", refused)
    assert slack.post("update") == "failed: ConnectError reaching Slack (network, DNS or the URL)"


def test_mcp_bearer_check_names_a_missing_token_and_takes_any_scheme_case(env):
    env(MCP_TOKEN="t0k3n")
    with TestClient(http_app("127.0.0.1")) as c:
        empty = c.post("/mcp", json=PING, headers={**MCP_HEADERS, "authorization": "Bearer "})
        assert empty.status_code == 401 and empty.json()["error"].startswith("no bearer token sent")
        wrong = c.post("/mcp", json=PING, headers={**MCP_HEADERS, "authorization": "Bearer nope"})
        assert wrong.status_code == 401 and wrong.json()["error"].startswith("wrong API token")
        lower = c.post("/mcp", json=PING, headers={**MCP_HEADERS, "authorization": "bearer t0k3n"})
        assert lower.status_code != 401


def test_api_token_takes_a_lowercase_bearer_scheme(env):
    env(API_TOKEN="t0k3n")
    c = TestClient(app_module.app)
    assert c.get("/api/tools", headers={"authorization": "Bearer nope"}).status_code == 401
    assert c.get("/api/tools", headers={"authorization": "bearer t0k3n"}).status_code == 200


class _Scratch:
    def __init__(self, rows: list[dict]):
        self.rows, self.dropped = rows, False

    def write(self, name: str, **_):
        return SimpleNamespace(name=name, rows=[])

    def read(self, name: str, **_):
        return SimpleNamespace(name=name, rows=self.rows)

    def drop_graph(self) -> None:
        self.dropped = True


def test_storm_components_raises_when_the_projection_loses_services():
    edges = [{"alerting": "svc:checkout", "red": "svc:payments-gw"},
             {"alerting": "svc:refunds", "red": "svc:payments-gw"}]
    scratch = _Scratch([{"service": "svc:checkout", "component": 0}, {"service": "svc:payments-gw", "component": 0}])
    ctx = ToolContext(SimpleNamespace(scratch=lambda _: scratch))
    with pytest.raises(RuntimeError, match=r"storm projection lost \['svc:refunds'\]"):
        _storm_components(ctx, edges, [])
    assert scratch.dropped
    scratch.rows.append({"service": "svc:refunds", "component": 0})
    assert _storm_components(ctx, edges, []) == {"svc:checkout": 0, "svc:payments-gw": 0, "svc:refunds": 0}


def _suspect(cid: str, explained: list[str]) -> dict:
    return {"change_id": cid, "explained": explained, "source": "dependency-path", "hops": 1, "at": 0, "onset": None,
            "service": f"svc:{cid}"}


def test_leading_never_picks_a_suspect_that_does_not_explain_the_origin():
    wide = _suspect("wide", ["svc:refunds", "svc:subscriptions"])  # explains more folded alerts, not the origin
    narrow = _suspect("narrow", ["svc:checkout"])
    assert leading([wide, narrow])[0]["change_id"] == "wide"  # without an origin, coverage wins
    lead, lost, co = leading([wide, narrow], origin="svc:checkout")
    assert lead["change_id"] == "narrow" and not lost
    assert [h["change_id"] for h, _ in co] == ["wide"]


def test_mcp_catalogue_marks_ask_as_writing():
    tools = catalogue()
    assert tools["ask"][0].annotations.read_only_hint is False  # it records the question in the asker's session
    assert tools["my_questions"][0].annotations.read_only_hint is True  # a recall writes nothing


def test_plugin_launcher_says_when_the_interpreter_cannot_import_oncall_brain(tmp_path):
    keep = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME")}
    r = subprocess.run(["bash", str(ROOT / "plugin" / "bin" / "oncall-brain-mcp")], cwd=tmp_path, capture_output=True,
                       text=True, timeout=30, env={**keep, "ONCALL_BRAIN_PYTHON": "/usr/bin/python3"})
    assert r.returncode == 1
    assert "/usr/bin/python3 cannot import oncall_brain" in r.stderr and "ONCALL_BRAIN_PYTHON" in r.stderr
