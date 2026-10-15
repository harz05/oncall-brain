"""The MCP server, driven in-process by the official SDK client against a real FalkorDB."""

import json
import os

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from oncall_brain.agents import registry
from oncall_brain.mcp_server import build_server
from oncall_brain.mcp_server.__main__ import http_app

pytestmark = pytest.mark.integration


async def _session(store, tenant: str) -> tuple[set[str], dict, dict, bool, str | None]:
    async with Client(build_server(store)) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        reset = await c.call_tool("reset_tenant", {"tenant": tenant})
        blast = await c.call_tool("blast_radius", {"tenant": tenant, "service": "svc:payments-gw"})
        missing = await c.call_tool("blast_radius", {"service": "svc:payments-gw"})
        # FalkorDB raises ResponseError on NUL in a parameter: a tool error, and the session keeps working.
        nul = await c.call_tool("blast_radius", {"tenant": tenant, "service": "svc:\x00"})
        nul_error = nul.content[0].text if nul.is_error else None
        await c.list_tools()
        return names, json.loads(reset.content[0].text), json.loads(blast.content[0].text), missing.is_error, nul_error


def test_mcp_exposes_every_registry_tool_and_runs_them_on_a_tenant(store):
    tenant = f"mcp_test_{os.getpid()}"
    store.drop(tenant)
    try:
        names, reset, blast, missing_tenant_is_error, nul_error = anyio.run(_session, store, tenant)
    finally:
        store.drop(tenant)
    assert names == set(registry.REGISTRY) | {"respond_to_alert", "reset_tenant"}
    assert reset["graph"] == "seeded"
    services = {r["service"] for r in blast["data"]}
    assert {"svc:payments", "svc:checkout"} <= services
    q = blast["queries"][0]
    assert q["name"] == "blast_radius" and q["readonly"] and q["rows"] == len(blast["data"]) and "MATCH" in q["cypher"]
    assert missing_tenant_is_error
    assert nul_error and nul_error.startswith("ResponseError")


def test_mcp_over_http_refuses_foreign_host_and_origin():
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
    h = {"Accept": "application/json, text/event-stream"}
    with TestClient(http_app("0.0.0.0"), base_url="http://localhost:8001") as c:  # the docker bind address
        assert c.post("/mcp", json=init, headers=h).status_code == 200
        assert c.post("/mcp", json=init, headers={**h, "Host": "evil.example:8001"}).status_code == 421
        assert c.post("/mcp", json=init, headers={**h, "Origin": "http://evil.example"}).status_code == 403
