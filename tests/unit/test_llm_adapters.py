"""Both real-LLM adapters against canned HTTP replies (httpx.MockTransport): parsing, finish/handoff, guardrails."""

import json

import httpx
import pytest

from oncall_brain.adapters.llm.anthropic import AnthropicProvider
from oncall_brain.adapters.llm.openai_compat import OpenAICompatProvider
from oncall_brain.agents import registry
from oncall_brain.services import tools as _tools  # noqa: F401  (registers the tools)

TOOLS = registry.specs()


def board(*steps: tuple[str, str]) -> dict:
    return {"incident": {"id": "inc:x", "status": "open", "service": "svc:checkout", "alert": "alert:x", "at": 0,
                         "symptom": "latency"},
            "steps": [{"tool": t, "target": target, "role": "triage"} for t, target in steps],
            "hypotheses": [], "recalls": [], "cause_service": None}


def openai_reply(tool: str, args: dict, text: str = "") -> dict:
    call = {"id": "c1", "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}
    return {"choices": [{"message": {"role": "assistant", "content": text or None, "tool_calls": [call]}}]}


def anthropic_reply(tool: str, args: dict, text: str = "") -> dict:
    content = [{"type": "thinking", "thinking": ""}] + ([{"type": "text", "text": text}] if text else [])
    return {"content": content + [{"type": "tool_use", "id": "t1", "name": tool, "input": args}],
            "stop_reason": "tool_use"}


def make(kind: str, reply: dict | None = None, status: int = 200, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=reply or {})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    if kind == "openai":
        return OpenAICompatProvider("k-test", "gemini-2.5-flash", "https://example.test/v1beta/openai/", client=client)
    return AnthropicProvider("k-test", client=client)


REPLY = {"openai": openai_reply, "anthropic": anthropic_reply}
KINDS = ["openai", "anthropic"]


def test_openai_request_and_tool_call_parsing():
    seen: list[httpx.Request] = []
    p = make("openai", openai_reply("blast_radius", {"service": "svc:checkout"}, "Who is hurt?"), seen=seen)
    d = p.decide("triage", board(), TOOLS)
    assert (d.action, d.tool, d.reason) == ("call", "blast_radius", "Who is hurt?")
    assert d.args == {"service": "svc:checkout", "incident_id": "inc:x"}  # incident filled in like the loop does
    req = seen[0]
    assert str(req.url) == "https://example.test/v1beta/openai/chat/completions"
    assert req.headers["authorization"] == "Bearer k-test"
    names = [t["function"]["name"] for t in json.loads(req.content)["tools"]]
    assert "finish" in names and "check_hypothesis" in names and "resolve_incident" not in names
    assert p.name == "gemini-2.5-flash via openai-compatible API"


def test_anthropic_request_and_tool_use_parsing():
    seen: list[httpx.Request] = []
    p = make("anthropic", anthropic_reply("page_on_call", {"service": "svc:checkout"}), seen=seen)
    d = p.decide("triage", board(("blast_radius", "svc:checkout")), TOOLS)
    assert (d.action, d.tool, d.reason) == ("call", "page_on_call", "LLM chose page_on_call")
    req = seen[0]
    body = json.loads(req.content)
    assert req.headers["x-api-key"] == "k-test" and req.headers["anthropic-version"] == "2023-06-01"
    assert body["model"] == "claude-sonnet-5-5" and body["tool_choice"]["type"] == "auto"
    assert {t["name"] for t in body["tools"]} >= {"finish", "blast_radius"}


@pytest.mark.parametrize("kind", KINDS)
def test_finish_hands_off_and_defaults_the_next_role(kind):
    d = make(kind, REPLY[kind]("finish", {"reason": "impact known", "handoff_to": "investigator"})).decide(
        "triage", board(), TOOLS)
    assert (d.action, d.handoff_to, d.reason) == ("done", "investigator", "impact known")
    d = make(kind, REPLY[kind]("finish", {"reason": "cause found"})).decide("investigator", board(), TOOLS)
    assert d.handoff_to == "comms"
    d = make(kind, REPLY[kind]("finish", {"reason": "posted", "handoff_to": "triage"})).decide("comms", board(), TOOLS)
    assert d.handoff_to is None  # never backwards: the roles cannot loop


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(("tool", "args", "steps", "why"), [
    ("drop_tables", {}, [], "unknown tool 'drop_tables'"),
    ("resolve_incident", {"change_id": "chg:1"}, [], "unknown tool 'resolve_incident'"),
    ("check_hypothesis", {}, [], "invalid args for check_hypothesis"),
    ("blast_radius", {"service": "svc:checkout"}, [("blast_radius", "svc:checkout")], "blast_radius on svc:checkout"),
])
def test_off_script_choices_fall_back_to_the_planner(kind, tool, args, steps, why):
    d = make(kind, REPLY[kind](tool, args)).decide("triage", board(*steps), TOOLS)
    assert d.reason.startswith(f"LLM fallback: {why}")
    assert d.tool == ("page_on_call" if steps else "blast_radius")  # what the deterministic planner picks


@pytest.mark.parametrize("kind", KINDS)
def test_http_error_falls_back_to_the_planner(kind):
    d = make(kind, status=500).decide("triage", board(), TOOLS)
    assert d.reason.startswith("LLM fallback: HTTP 500") and d.tool == "blast_radius"
    assert "k-test" not in d.reason


def test_make_llm_picks_preset_and_vendor_key(monkeypatch):
    from oncall_brain.adapters.llm.mock import MockProvider
    from oncall_brain.config import Settings
    from oncall_brain.wiring import make_llm

    for var in ("LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    gemini = make_llm(Settings(_env_file=None, llm_provider="gemini", google_api_key="g"))
    assert isinstance(gemini, OpenAICompatProvider) and "generativelanguage" in gemini.url
    assert "sk-zz9" not in repr(Settings(_env_file=None, llm_api_key="sk-zz9"))  # keys never printed
    assert isinstance(make_llm(Settings(_env_file=None, llm_provider="openai", gemini_api_key="g")), MockProvider)
    assert make_llm(Settings(_env_file=None, llm_provider="ollama")).url == "http://localhost:11434/v1/chat/completions"
