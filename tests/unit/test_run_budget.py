"""The per-run token cap: a model that keeps spending hands the rest of the incident to the planner."""

from oncall_brain.domain.models import Decision
from oncall_brain.services.respond import RunBudget

BOARD = {"incident": {"id": "inc:x", "service": "svc:checkout", "status": "open"}, "steps": [], "hypotheses": [],
         "recalls": []}


class SpendyModel:
    name = "spendy via test"

    def __init__(self):
        self.calls = 0

    def decide(self, role, board, tools):
        self.calls += 1
        return Decision(action="call", tool="blast_radius", args={"service": "svc:checkout"}, reason="because",
                        by="spendy", usage=100)


def test_decisions_come_from_the_model_until_the_cap_then_from_the_rules():
    model = SpendyModel()
    budget = RunBudget(model, cap=150)
    first, second = budget.decide("triage", BOARD, []), budget.decide("triage", BOARD, [])
    assert (first.by, second.by, budget.used, model.calls) == ("spendy", "spendy", 200, 2)
    third = budget.decide("triage", BOARD, [])
    assert third.by == "rules" and third.reason.startswith("LLM fallback: token cap for this run (150) reached.")
    assert third.tool == "blast_radius" and model.calls == 2  # the planner's own triage step; the model is not asked


def test_a_decision_that_never_reached_the_api_counts_nothing():
    class Flaky(SpendyModel):
        def decide(self, role, board, tools):
            self.calls += 1  # e.g. an HTTP error: the adapter's fallback reports no usage
            return Decision(action="call", tool="blast_radius", args={"service": "svc:checkout"}, reason="fallback")

    model = Flaky()
    budget = RunBudget(model, cap=10_000)
    budget.decide("triage", BOARD, [])
    assert budget.used == 0 and budget.name == "spendy via test"
