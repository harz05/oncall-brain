"""Real-LLM planner over the Anthropic Messages API (raw HTTP, no SDK). Same prompt, tool list and guardrails
as the OpenAI-compatible adapter; only the wire format differs."""

from typing import Any

import httpx

from oncall_brain.adapters.llm.openai_compat import TIMEOUT, guarded
from oncall_brain.domain.models import Decision

DEFAULT_MODEL = "claude-sonnet-5-5"
URL = "https://api.anthropic.com/v1/messages"
# Server-side retry of a safety-classifier decline on Anthropic's recommended model (Claude API only).
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1")


class AnthropicProvider:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, client: httpx.Client | None = None):
        self.model = model
        self.name = f"{model} via Anthropic Messages API"
        self.last_usage = 0  # input + output tokens of the last request, for the per-run cap
        self._headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        if model in FALLBACK_MODELS:
            self._headers["anthropic-beta"] = FALLBACK_BETA
        self._client = client or httpx.Client(timeout=TIMEOUT)

    def decide(self, role: str, board: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        return guarded(role, board, tools, self._ask, self.model)

    def _ask(self, system: str, board: str, tools: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any], str]:
        # Forced tool_choice ("any"/"tool") is rejected by current models: auto + one call at most + the prompt.
        body: dict[str, Any] = {
            "model": self.model, "max_tokens": 4096, "system": system, "tools": tools,
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
            "output_config": {"effort": "low"},  # one routing decision per call; keeps us inside the timeout
            "messages": [{"role": "user", "content": board}]}
        if "anthropic-beta" in self._headers:
            body["fallbacks"] = "default"
        r = self._client.post(URL, json=body, headers=self._headers)
        r.raise_for_status()
        msg = r.json()
        usage = msg.get("usage") or {}
        self.last_usage = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        text = " ".join(b["text"] for b in msg["content"] if b["type"] == "text").strip()
        use = next((b for b in msg["content"] if b["type"] == "tool_use"), None)
        if msg["stop_reason"] != "tool_use" or use is None:  # end_turn, max_tokens, refusal: no usable call
            return None, {}, text
        return use["name"], use["input"], text
