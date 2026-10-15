"""The MCP server, driven in-process by the official SDK client against a real FalkorDB."""

import json
import os

import anyio
import pytest
from mcp import Client

from oncall_brain.agents import registry
from oncall_brain.mcp_server import build_server

pytestmark = pytest.mark.integration


async def _session(store, tenant: str) -> tuple[set[str], dict, dict, bool]:
    async with Client(build_server(store)) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        reset = await c.call_tool("reset_tenant", {"tenant": tenant})
        blast = await c.call_tool("blast_radius", {"tenant": tenant, "service": "svc:payments-gw"})
        missing = await c.call_tool("blast_radius", {"service": "svc:payments-gw"})
        return names, json.loads(reset.content[0].text), json.loads(blast.content[0].text), missing.is_error


def test_mcp_exposes_every_registry_tool_and_runs_them_on_a_tenant(store):
    tenant = f"mcp_test_{os.getpid()}"
    store.drop(tenant)
    try:
        names, reset, blast, missing_tenant_is_error = anyio.run(_session, store, tenant)
    finally:
        store.drop(tenant)
    assert names == set(registry.REGISTRY) | {"respond_to_alert", "reset_tenant"}
    assert reset["graph"] == "seeded"
    services = {r["service"] for r in blast["data"]}
    assert {"svc:payments", "svc:checkout"} <= services
    q = blast["queries"][0]
    assert q["name"] == "blast_radius" and q["readonly"] and q["rows"] == len(blast["data"]) and "MATCH" in q["cypher"]
    assert missing_tenant_is_error
