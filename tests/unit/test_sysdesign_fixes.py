"""The system-design review's fixes that need no database: the timeout circuit breaker, the lease renewed on every
step, and Slack escaping."""

import httpx

from oncall_brain.adapters import slack
from oncall_brain.domain.models import Decision
from oncall_brain.services import respond as respond_svc
from oncall_brain.services.respond import RunBudget

BOARD = {"incident": {"id": "inc:x", "service": "svc:checkout", "status": "open"}, "steps": [], "hypotheses": [],
         "recalls": []}


class TimingOut:
    name = "slow via test"

    def __init__(self):
        self.calls = 0

    def decide(self, role, board, tools):
        self.calls += 1  # what the adapter returns when the client gave up waiting
        return Decision(action="call", tool="blast_radius", args={"service": "svc:checkout"},
                        reason="LLM fallback: timeout. planner reason", usage=500)


def test_two_timeouts_in_a_row_hand_the_rest_of_the_run_to_the_rules():
    model = TimingOut()
    budget = RunBudget(model, cap=0)
    budget.decide("triage", BOARD, []), budget.decide("triage", BOARD, [])
    third = budget.decide("triage", BOARD, [])
    assert model.calls == 2 and third.by == "rules"
    assert "the model did not answer 2 times in a row" in third.reason


def test_an_answer_between_timeouts_resets_the_breaker():
    class Mixed(TimingOut):
        def decide(self, role, board, tools):
            self.calls += 1
            reason = "LLM fallback: timeout. x" if self.calls % 2 else "because"
            return Decision(action="call", tool="blast_radius", args={"service": "svc:checkout"}, reason=reason)

    model = Mixed()
    budget = RunBudget(model, cap=0)
    for _ in range(5):
        budget.decide("triage", BOARD, [])
    assert model.calls == 5  # timeout, answer, timeout, answer, timeout: never two in a row


def test_respond_renews_the_tenant_lease_on_every_step(monkeypatch):
    class Lease:
        renewed = 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def reacquire(self):
            Lease.renewed += 1

    class Repo:
        tenant = "t"

        def lock(self):
            return Lease()

    seen = []

    def fake_respond(repo, alert_id, llm, on_step):
        for i in range(3):
            on_step(i)
        return {"outcome": {}}

    monkeypatch.setattr(respond_svc, "_respond", fake_respond)
    respond_svc.respond(Repo(), "alert:x", object(), seen.append)
    assert Lease.renewed == 3 and seen == [0, 1, 2]  # the caller's on_step still gets every step


def test_slack_text_cannot_ping_a_channel_or_hide_a_link(monkeypatch):
    sent = {}
    monkeypatch.setattr(slack, "get_settings", lambda: type("S", (), {"slack_webhook_url": "https://hooks.example"})())
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: sent.update(json) or httpx.Response(
        200, request=httpx.Request("POST", url)))
    assert slack.post("cause: <!channel> see <https://evil|docs> & co") == "posted"
    # a code block: Slack neither links URLs nor resolves mentions in it
    assert sent["text"] == "```\ncause: &lt;!channel&gt; see &lt;https://evil|docs&gt; &amp; co\n```"
