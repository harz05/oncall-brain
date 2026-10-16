"""The deployment app (oncall_brain.serve): UI + API at /, the MCP endpoint at /mcp behind a required bearer token,
/health. No FalkorDB needed: /health reports it down, the MCP handshake and the API's tool list need no graph."""

import pytest
from starlette.testclient import TestClient

from oncall_brain import serve
from oncall_brain.config import LOCAL_HOSTS, get_settings

MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "test", "version": "0"}}}
TOKENS = ("MCP_TOKEN", "API_TOKEN", "ALLOWED_HOSTS", "RENDER_EXTERNAL_HOSTNAME", "RAILWAY_PUBLIC_DOMAIN")


@pytest.fixture
def env(monkeypatch):
    def set_(**values):
        for name in TOKENS:
            monkeypatch.delenv(name, raising=False)
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield set_
    get_settings.cache_clear()


def test_mcp_is_refused_until_a_token_is_set_while_the_ui_and_api_stay_up(env):
    env()
    with TestClient(serve.app) as c:  # the context runs the startup of both halves
        assert c.get("/api/tools").status_code == 200  # the API keeps its own rule: open without API_TOKEN
        health = c.get("/health").json()
        assert health["falkordb"] in (True, False) and health["mcp"].startswith("off: MCP_TOKEN")
        refused = c.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        assert refused.status_code == 401 and refused.headers["WWW-Authenticate"] == "Bearer"
        assert "MCP_TOKEN" in refused.json()["error"]


def test_the_token_opens_mcp_at_the_exact_path_and_the_api_needs_none(env):
    env(MCP_TOKEN="t0k3n")
    with TestClient(serve.app) as c:
        assert c.get("/health").json()["mcp"] == "/mcp"
        assert c.get("/api/tools").status_code == 200  # MCP_TOKEN alone leaves the UI's API open
        wrong = c.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "authorization": "Bearer nope"})
        assert wrong.status_code == 401
        ok = c.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "authorization": "Bearer t0k3n"})
        assert ok.status_code == 200 and "oncall-brain" in ok.text  # the initialize result names the server
        assert c.post("/mcp/", json=INITIALIZE, headers=MCP_HEADERS).status_code == 404  # no redirect games


def test_one_token_can_guard_both_halves(env):
    env(API_TOKEN="shared")
    assert get_settings().mcp_bearer() == "shared"
    with TestClient(serve.app) as c:
        assert c.get("/api/tools").status_code == 401
        headers = {**MCP_HEADERS, "authorization": "Bearer shared"}
        assert c.post("/mcp", json=INITIALIZE, headers=headers).status_code == 200


def test_the_hostnames_render_and_railway_set_are_accepted_hosts(env):
    env(RENDER_EXTERNAL_HOSTNAME="oncall-brain.onrender.com", RAILWAY_PUBLIC_DOMAIN="brain.up.railway.app",
        ALLOWED_HOSTS="oncall.example.com, localhost")
    hosts = get_settings().hosts()
    assert hosts[: len(LOCAL_HOSTS)] == LOCAL_HOSTS
    assert hosts[len(LOCAL_HOSTS):] == ["oncall.example.com", "oncall-brain.onrender.com", "brain.up.railway.app"]
    env()
    assert get_settings().hosts() == LOCAL_HOSTS
