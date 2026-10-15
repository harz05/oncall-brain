"""Deterministic stand-in for an LLM: the rule-based planner. Lets the whole demo, tests and reviewers run
without API keys. Fixed rules choose each step; their inputs are only what the graph returns (the board)."""

from typing import Any

from oncall_brain.domain.models import Decision
from oncall_brain.domain.planner import next_decision


class MockProvider:
    name = "deterministic planner"

    def decide(self, role: str, board: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        return next_decision(role, board)
