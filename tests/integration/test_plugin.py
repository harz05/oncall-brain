"""The Claude Code plugin under plugin/: its manifests and skills are well-formed (the Claude CLI's own validator
agrees when it is installed), and an MCP client that launches the server the way Claude Code does (the plugin's
stdio launcher) sees every tool and prompt and can follow the who-owns skill to an answer."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from oncall_brain.agents import registry
from oncall_brain.services import tools as _tools  # registers every tool

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
    assert server["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/oncall-brain-mcp"
    assert os.access(PLUGIN / "bin" / "oncall-brain-mcp", os.X_OK)
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
