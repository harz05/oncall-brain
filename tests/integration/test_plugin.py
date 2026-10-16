"""The Claude Code plugin under plugin/: its manifests and skills are well-formed (the Claude CLI's own validator
agrees when it is installed), an MCP client that launches the server the way Claude Code does (the plugin's stdio
launcher) sees every tool and prompt and can follow the who-owns skill to an answer, and the remote entry (Streamable
HTTP, URL and token from the environment, expanded the way Claude Code expands them) reaches a server started with
API_TOKEN."""

import json
import os
import re
import secrets
import shutil
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
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from oncall_brain.agents import registry
from oncall_brain.services import tools as _tools  # registers every tool
from oncall_brain.services.seeding import seed

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugin"


def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md needs frontmatter"
    return {k.strip(): v.strip() for k, v in (line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)}


def test_plugin_manifests_and_skills_are_well_formed():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "oncall-brain" and manifest["mcpServers"] == "./.mcp.json"
    server = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]["oncall-brain"]
    # Run through bash so a checkout on a filesystem that drops the executable bit (NTFS, some zips) still works.
    assert server["command"] == "bash" and server["args"] == ["${CLAUDE_PLUGIN_ROOT}/bin/oncall-brain-mcp"]
    assert (PLUGIN / "bin" / "oncall-brain-mcp").read_text().startswith("#!/usr/bin/env bash")
    # Remote mode: an http entry whose url and headers Claude Code expands from the environment (${VAR}, ${VAR:-default}
    # are documented for a plugin server's url and headers); with neither set it points at a local `make mcp-http`.
    remote = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]["oncall-brain-remote"]
    assert remote["type"] == "http" and remote["url"] == "${ONCALL_BRAIN_URL:-http://127.0.0.1:8001}/mcp"
    assert remote["headers"] == {"Authorization": "Bearer ${ONCALL_BRAIN_TOKEN}"}
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert [p["source"] for p in market["plugins"] if p["name"] == "oncall-brain"] == ["./plugin"]
    skills = sorted(p.parent.name for p in PLUGIN.glob("skills/*/SKILL.md"))
    assert skills == ["ask", "incident", "who-owns"]
    for skill in skills:
        fm = _frontmatter((PLUGIN / "skills" / skill / "SKILL.md").read_text())
        assert fm["name"] == skill and len(fm["description"]) > 40 and fm["argument-hint"]
    if shutil.which("claude"):  # the CLI's own validator, strict mode
        for target in (PLUGIN, ROOT / ".claude-plugin" / "marketplace.json", PLUGIN / "skills"):
            run = subprocess.run(["claude", "plugin", "validate", "--strict", str(target)],
                                 capture_output=True, text=True, timeout=120)
            assert run.returncode == 0, run.stdout + run.stderr


async def _as_claude_code_would(tenant: str):
    params = StdioServerParameters(command=str(PLUGIN / "bin" / "oncall-brain-mcp"), args=[],
                                   env={**os.environ, "ONCALL_BRAIN_HOME": str(ROOT)})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        init = await s.initialize()
        tools = {t.name for t in (await s.list_tools()).tools}
        prompts = {p.name for p in (await s.list_prompts()).prompts}
        await s.call_tool("reset_tenant", {"tenant": tenant})
        # the who-owns skill, step by step: who_knows, then ask, then the rotation
        texts = []
        for name, args in (("who_knows", {"service": "svc:kafka"}), ("ask", {"question": "who owns kafka"}),
                           ("page_on_call", {"service": "svc:kafka"})):
            res = await s.call_tool(name, {"tenant": tenant, **args})
            assert not (getattr(res, "is_error", None) or getattr(res, "isError", False)), res.content
            texts.append(json.loads(res.content[0].text))
        return init.instructions or "", tools, prompts, texts


def test_an_mcp_client_launched_through_the_plugin_sees_everything_and_can_follow_the_who_owns_skill(store, tenant):
    instructions, tools, prompts, (who, ask, oncall) = anyio.run(_as_claude_code_would, tenant)
    assert "On-call Brain" in instructions
    assert tools == set(registry.REGISTRY) | {"respond_to_alert", "reset_tenant"} and _tools.warn_owners
    assert prompts == {"work_alert", "company_question"}
    assert "Platform" in json.dumps(who) and "Platform" in json.dumps(ask) and "Platform" in oncall["summary"]
    assert all(q["cypher"] for payload in (who, ask, oncall) for q in payload["queries"])  # the Cypher is shown
    assert store.exists(tenant)  # reset_tenant seeded the demo company through the plugin's server


EXPANSION = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _expand(value: str, env: dict[str, str]) -> str:
    """What Claude Code does to a plugin server's url and headers: ${VAR} and ${VAR:-default}."""
    return EXPANSION.sub(lambda m: env.get(m.group(1), m.group(2) or ""), value)


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
    pytest.fail("the HTTP MCP server did not start")


async def _over_http(url: str, headers: dict[str, str], tenant: str):
    async with (create_mcp_http_client(headers=headers) as client,
                streamable_http_client(url, http_client=client) as (read, write), ClientSession(read, write) as s):
        init = await s.initialize()
        tools = {t.name for t in (await s.list_tools()).tools}
        res = await s.call_tool("ask", {"tenant": tenant, "question": "who owns kafka"})
        assert not (getattr(res, "is_error", None) or getattr(res, "isError", False)), res.content
        return init.instructions or "", tools, json.loads(res.content[0].text)


def test_the_remote_entry_reaches_a_deployed_server_with_the_token_and_nothing_local(store, tenant):
    """Remote mode end to end: a server started with --http and API_TOKEN (what a deployment runs), the plugin's
    oncall-brain-remote entry expanded from ONCALL_BRAIN_URL and ONCALL_BRAIN_TOKEN, no checkout-side launcher."""
    seed(store, tenant)
    port, token = _free_port(), secrets.token_hex(8)
    proc = subprocess.Popen([sys.executable, "-m", "oncall_brain.mcp_server", "--http", "--port", str(port)],
                            env={**os.environ, "API_TOKEN": token}, cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for(port)
        remote = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]["oncall-brain-remote"]
        env = {"ONCALL_BRAIN_URL": f"http://127.0.0.1:{port}", "ONCALL_BRAIN_TOKEN": token}
        url = _expand(remote["url"], env)
        headers = {k: _expand(v, env) for k, v in remote["headers"].items()}
        assert url == f"http://127.0.0.1:{port}/mcp" and headers == {"Authorization": f"Bearer {token}"}
        assert _expand(remote["url"], {}) == "http://127.0.0.1:8001/mcp"  # unset: a local `make mcp-http`
        instructions, tools, ask = anyio.run(_over_http, url, headers, tenant)
        assert "On-call Brain" in instructions
        assert tools == set(registry.REGISTRY) | {"respond_to_alert", "reset_tenant"}
        assert "Platform" in json.dumps(ask) and all(q["cypher"] for q in ask["queries"])
        # The wrong token (or none) is refused before anything else runs.
        req = urllib.request.Request(url, data=b"{}", method="POST", headers={
            "Authorization": "Bearer nope", "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=10)
        assert err.value.code == 401 and err.value.headers.get("WWW-Authenticate") == "Bearer"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
