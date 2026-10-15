"""Real-LLM planner over any OpenAI-compatible /chat/completions endpoint (OpenAI, Gemini, Groq, OpenRouter,
Ollama), plus the guardrails every LLM provider shares (anthropic.py reuses them).

Each decision is one stateless request: system prompt + the incident board just read from the graph. The model
picks one registry tool or `finish`; anything off-script (unknown tool, bad args, a repeated step, HTTP error,
timeout) falls back to the deterministic planner, so a flaky model can slow the story down but not derail it.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import ValidationError

from oncall_brain.agents.loop import _target
from oncall_brain.agents.registry import REGISTRY
from oncall_brain.domain.models import Decision
from oncall_brain.domain.planner import next_decision

TIMEOUT = 15.0
ROLES = ["triage", "investigator", "comms"]  # handoffs only go forward, so a model cannot loop the roles
HUMAN_ONLY = {"resolve_incident"}  # confirming the root cause is the human's call, never an agent's
ID_PREFIX = {"service": "svc", "from_service": "svc", "to_service": "svc", "change_id": "chg"}

SYSTEM = """You are the {role} agent of an on-call team: triage -> investigator -> comms.
The user message is the incident board: the shared incident state, read fresh from a FalkorDB graph before every
decision. It lists the steps every agent already took (tool + target), the hypotheses and their status, and the
past incidents recalled from memory.
- triage: find who is hurt (blast_radius of the alerting service) and page whoever is on call for it.
- investigator: recall similar past incidents; if one matches, hypothesize_from_memory first, else
  propose_hypotheses; then check_hypothesis on each open hypothesis until one is supported.
- comms: page the owner of the culprit service, warn its dependents (blast_radius), then post_update.
Call exactly one tool per turn: one graph tool, or `finish` when your role's work is done. Never repeat a step that
is already on the board with the same target. Use ids exactly as they appear on the board."""

FINISH = {
    "name": "finish",
    "description": "End your role's turn. handoff_to: investigator (after triage) or comms (after investigator); "
                   "omit it after comms.",
    "input_schema": {"type": "object", "properties": {
        "reason": {"type": "string", "description": "One sentence: why your role is done"},
        "handoff_to": {"type": "string", "enum": ROLES[1:]}}, "required": ["reason"]},
}

# (tool name or None, args, the model's text). May raise anything on a malformed reply; guarded() falls back.
Ask = Callable[[str, str, list[dict[str, Any]]], tuple[str | None, dict[str, Any], str]]


def tool_list(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = ("name", "description", "input_schema")
    return [{k: t[k] for k in keep} for t in tools if t["name"] not in HUMAN_ONLY] + [FINISH]


def fallback(role: str, board: dict[str, Any], why: str) -> Decision:
    d = next_decision(role, board)
    return d.model_copy(update={"reason": f"LLM fallback: {why}. {d.reason}"})


def _why(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"  # never the URL or headers: they may carry the key
    return "timeout" if isinstance(e, httpx.TimeoutException) else f"bad reply ({type(e).__name__})"


def guarded(role: str, board: dict[str, Any], tools: list[dict[str, Any]], ask: Ask) -> Decision:
    """Ask the model, then accept its choice only if it is a known tool with valid args and not a repeat."""
    try:
        name, args, text = ask(SYSTEM.format(role=role), json.dumps(board, default=str), tool_list(tools))
    except Exception as e:  # any malformed reply (null message, odd shapes) must not crash the run
        return fallback(role, board, _why(e))
    if not isinstance(name, str) or not isinstance(args, dict):
        return fallback(role, board, "no usable tool call")
    if name == "finish":
        nxt = ROLES[ROLES.index(role) + 1:]
        handoff = args.get("handoff_to") if args.get("handoff_to") in nxt else (nxt[0] if nxt else None)
        return Decision(action="done", handoff_to=handoff, reason=str(args.get("reason") or text or "LLM finished"))
    if name not in REGISTRY or name in HUMAN_ONLY:
        return fallback(role, board, f"unknown tool {name!r}")
    tool = REGISTRY[name]
    fields = tool.args_model.model_fields
    args = {k: v for k, v in args.items() if k in fields}  # stray keys would skew _target and the repeat check
    if "incident_id" in fields:  # never the model's: an invented id could write into another incident
        args["incident_id"] = board["incident"]["id"]
    try:
        tool.args_model.model_validate(args)
    except ValidationError as e:
        return fallback(role, board, f"invalid args for {name} ({e.error_count()} errors)")
    # Mangled or invented ids make the tool raise mid-run; catch them here while the planner can still step in.
    if "hypothesis_id" in fields and args["hypothesis_id"] not in {
            h["id"] for h in board["hypotheses"] if h["status"] == "open"}:
        return fallback(role, board, "unknown/closed hypothesis id")
    if bad := [k for k, p in ID_PREFIX.items() if k in args and not re.fullmatch(rf"{p}:\S+", args[k])]:
        return fallback(role, board, f"malformed {bad[0]}")
    if any(s["tool"] == name and s["target"] == _target(args) for s in board["steps"]):
        return fallback(role, board, f"{name} on {_target(args) or 'this incident'} already ran")
    return Decision(action="call", tool=name, args=args, reason=text or f"LLM chose {name}")


class OpenAICompatProvider:
    def __init__(self, api_key: str, model: str, base_url: str, client: httpx.Client | None = None):
        self.model, self.url = model, base_url.rstrip("/") + "/chat/completions"
        self.name = f"{model} via openai-compatible API"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}  # ollama needs none
        self._client = client or httpx.Client(timeout=TIMEOUT)

    def decide(self, role: str, board: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        return guarded(role, board, tools, self._ask)

    def _ask(self, system: str, board: str, tools: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any], str]:
        body = {"model": self.model, "tool_choice": "auto",  # "required" is not accepted by every compatible API
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": board}],
                "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                            "parameters": t["input_schema"]}} for t in tools]}
        r = self._client.post(self.url, json=body, headers=self._headers)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        text = msg.get("content")
        text = text.strip() if isinstance(text, str) else ""  # null, or a list of parts on some servers
        calls = msg.get("tool_calls") or []
        if not calls:
            return None, {}, text
        fn = calls[0]["function"]
        args = fn.get("arguments") or {}
        return fn["name"], args if isinstance(args, dict) else json.loads(args), text
