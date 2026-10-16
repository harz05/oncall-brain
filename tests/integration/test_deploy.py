"""A deployment as the Dockerfile runs it: one uvicorn process serving the web UI, the HTTP API, /health and the MCP
endpoint, driven from outside with plain HTTP and the MCP SDK's Streamable HTTP client."""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from oncall_brain.agents import registry
from oncall_brain.services import tools as _tools  # noqa: F401  (registers every tool)
from oncall_brain.services.seeding import seed

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for(port: int, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    pytest.fail("the deployment app did not start")


def _get(url: str, **headers) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


async def _mcp(url: str, token: str, tenant: str):
    async with (create_mcp_http_client(headers={"Authorization": f"Bearer {token}"}) as client,
                streamable_http_client(url, http_client=client) as (read, write), ClientSession(read, write) as s):
        await s.initialize()
        tools = {t.name for t in (await s.list_tools()).tools}
        res = await s.call_tool("ask", {"tenant": tenant, "question": "who owns kafka"})
        assert not (getattr(res, "is_error", None) or getattr(res, "isError", False)), res.content
        return tools, json.loads(res.content[0].text)


def test_one_process_serves_the_ui_the_api_health_and_a_token_guarded_mcp_endpoint(store, tenant):
    seed(store, tenant)
    port, token = _free_port(), secrets.token_hex(8)
    env = {**os.environ, "MCP_TOKEN": token, "API_TOKEN": "", "RENDER_EXTERNAL_HOSTNAME": "brain.onrender.com"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "oncall_brain.serve:app", "--port", str(port)],
                            env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for(port)
        base = f"http://127.0.0.1:{port}"
        status, body = _get(f"{base}/health")
        health = json.loads(body)
        assert status == 200 and health["falkordb"] is True and health["ok"] and health["mcp"] == "/mcp"
        assert _get(f"{base}/api/health")[0] == 200
        assert _get(f"{base}/api/tools")[0] == 200  # MCP_TOKEN alone leaves the API (and so the UI) open
        if (ROOT / "web" / "index.html").is_file():
            status, page = _get(f"{base}/")  # redirects to the UI
            assert status == 200 and b"<" in page[:200]
        # The hostname the platform set is a valid Host on both halves; an unknown one is not (DNS rebinding).
        # /health itself answers on any Host, so a platform's checker always reaches it.
        assert _get(f"{base}/api/health", Host="brain.onrender.com")[0] == 200
        assert _get(f"{base}/api/health", Host="evil.example")[0] == 400
        assert _get(f"{base}/health", Host="evil.example")[0] == 200
        rebinding = urllib.request.Request(f"{base}/mcp", data=b"{}", method="POST", headers={
            "Authorization": f"Bearer {token}", "Host": "evil.example", "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(rebinding, timeout=10)
        assert err.value.code == 421
        tools, ask = anyio.run(_mcp, f"{base}/mcp", token, tenant)
        assert tools == set(registry.REGISTRY) | {"respond_to_alert", "reset_tenant"}
        assert "Platform" in json.dumps(ask) and all(q["cypher"] for q in ask["queries"])
        assert anyio.run(_mcp, f"{base}/mcp/", token, tenant)[0] == tools  # a trailing slash is the same endpoint
        req = urllib.request.Request(f"{base}/mcp", data=b"{}", method="POST", headers={
            "Authorization": "Bearer nope", "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=10)
        assert err.value.code == 401 and err.value.headers.get("WWW-Authenticate") == "Bearer"
    finally:
        proc.terminate()
        proc.wait(timeout=15)
