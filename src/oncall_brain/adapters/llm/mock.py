"""Deterministic 'LLM': the rule-based planner. Lets the whole demo, tests and the cloud reviewer run
without API keys. The graph still decides every branch, because the planner only sees the board."""

from typing import Any

from oncall_brain.domain.models import Decision
from oncall_brain.domain.planner import next_decision


class MockProvider:
    name = "deterministic planner"

    def decide(self, role: str, board: dict[str, Any], tools: list[dict[str, Any]]) -> Decision:
        return next_decision(role, board)
