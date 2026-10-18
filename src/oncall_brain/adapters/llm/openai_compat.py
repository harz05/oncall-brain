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
ID_PREFIX = {"service": "svc", "from_service": "svc", "to_service": "svc", "change_id": "chg"}

SYSTEM = """You are the {role} agent of an on-call team: triage -> investigator -> comms.
The user message is the incident board: the shared incident state, read fresh from a FalkorDB graph before every
decision. It lists the steps every agent already took (tool + target), the hypotheses and their status, and the
past incidents recalled from memory.
- triage: if the board's storm count is above 0, other alerts fired within 15 minutes: correlate_alerts first, so
  related alerts join this incident and their shared upstream is known. Then find who is hurt (blast_radius of the
  alerting service) and page whoever is on call for it.
- investigator: recall similar past incidents; if one matches (score 3 or more), hypothesize_from_memory first,
  else propose_hypotheses. Then check_hypothesis on every open hypothesis: one supported suspect is not proof while
  others are still open. If alerts were correlated and no supported suspect explains all of them, propose_hypotheses
  (once). If more than one suspect is supported, conclude.
- comms: page the owner of the culprit service and of any co-cause, ask who_knows the culprit service, find its
  dependents (blast_radius), warn_owners (a heads-up to the most critical impacted teams), then post_update.
Call exactly one tool per turn: one graph tool, or `finish` when your role's work is done. Never repeat a step that
is already on the board with the same target. Use ids exactly as they appear on the board.
Start every reply with one plain sentence (at most 25 words) telling the on-call engineer what you are doing and
why, as you would in an incident channel; then make the tool call."""

FINISH = {
    "name": "finish",
    "description": "End your role's turn. handoff_to: investigator (after triage) or comms (after investigator); "
                   "omit it after comms.",
    "input_schema": {"type": "object", "properties": {
        "reason": {"type": "string", "description": "One sentence: why your role is done"},
        "handoff_to": {"type": "string", "enum": ROLES[1:]}}, "required": ["reason"]},
}

# (tool name or None, args, the model's text, tokens billed). May raise anything on a malformed reply; guarded() falls
# back.
Ask = Callable[[str, str, list[dict[str, Any]]], tuple[str | None, dict[str, Any], str, int]]


def tool_list(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = ("name", "description", "input_schema")
    # Tools registered with agent=False (confirming a fix, recording graph facts) are never offered.
    return [{k: t[k] for k in keep} for t in tools if REGISTRY[t["name"]].agent] + [FINISH]


def fallback(role: str, board: dict[str, Any], why: str) -> Decision:
    d = next_decision(role, board)
    return d.model_copy(update={"reason": f"LLM fallback: {why}. {d.reason}"})


def _why(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"  # never the URL or headers: they may carry the key
    return "timeout" if isinstance(e, httpx.TimeoutException) else f"bad reply ({type(e).__name__})"


def guarded(role: str, board: dict[str, Any], tools: list[dict[str, Any]], ask: Ask, by: str = "model") -> Decision:
    """Ask the model, then accept its choice only if it is a known tool with valid args and not a repeat.
    `by` names the model on the decisions it made; fallbacks are the planner's ("rules"). Every decision carries the
    tokens its request was billed (`usage`, what RunBudget counts), fallbacks included."""
    system, payload, specs = SYSTEM.format(role=role), json.dumps(board, default=str), tool_list(tools)
    try:
        name, args, text, usage = ask(system, payload, specs)
    except Exception as e:  # any malformed reply (null message, odd shapes) must not crash the run
        # A request that reached the model is billed even if we gave up waiting (a read timeout) or could not parse
        # the reply, and no usage came back: charge an estimate (~3 characters a token, plus the output) so the budget
        # never undercounts. Refused (HTTP error) and never-sent requests cost nothing.
        sent = not isinstance(e, httpx.HTTPStatusError | httpx.TransportError) or isinstance(e, httpx.ReadTimeout)
        estimate = (len(system) + len(payload) + len(json.dumps(specs))) // 3 + 1000 if sent else 0
        return fallback(role, board, _why(e)).model_copy(update={"usage": estimate})
    return _accept(role, board, name, args, text, by).model_copy(update={"usage": usage})


def _accept(role: str, board: dict[str, Any], name: Any, args: Any, text: str, by: str) -> Decision:
    if not isinstance(name, str) or not isinstance(args, dict):
        return fallback(role, board, "no usable tool call")
    if name == "finish":
        nxt = ROLES[ROLES.index(role) + 1:]
        handoff = args.get("handoff_to") if args.get("handoff_to") in nxt else (nxt[0] if nxt else None)
        return Decision(action="done", handoff_to=handoff, by=by,
                        reason=str(args.get("reason") or text or "The model finished this role's work."))
    if name not in REGISTRY or not REGISTRY[name].agent:
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
    return Decision(action="call", tool=name, args=args, by=by,
                    reason=text or f"The model chose {name} without saying why.")


class OpenAICompatProvider:
    def __init__(self, api_key: str, model: str, base_url: str, client: httpx.Client | None = None):
        self.model, self.url = model, base_url.rstrip("/") + "/chat/completions"
        self.name = f"{model} via openai-compatible API"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}  # ollama needs none
        self._client = client or httpx.Client(timeout=TIMEOUT)

    def decide(self, role: str, board: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        return guarded(role, board, tools, self._ask, self.model)

    def _ask(self, system: str, board: str,
             tools: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any], str, int]:
        body = {"model": self.model, "tool_choice": "auto",  # "required" is not accepted by every compatible API
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": board}],
                "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                            "parameters": t["input_schema"]}} for t in tools]}
        r = self._client.post(self.url, json=body, headers=self._headers)
        r.raise_for_status()
        data = r.json()
        usage = int((data.get("usage") or {}).get("total_tokens") or 0)  # prompt + completion
        msg = data["choices"][0]["message"]
        text = msg.get("content")
        text = text.strip() if isinstance(text, str) else ""  # null, or a list of parts on some servers
        calls = msg.get("tool_calls") or []
        if not calls:
            return None, {}, text, usage
        fn = calls[0]["function"]
        args = fn.get("arguments") or {}
        return fn["name"], args if isinstance(args, dict) else json.loads(args), text, usage
