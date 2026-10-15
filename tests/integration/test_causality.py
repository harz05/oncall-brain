"""Two failure modes a mock judge demonstrated with the event tools, kept as regression tests."""

import pytest

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.services.respond import respond
from oncall_brain.services.seeding import seed
from tests.integration.test_storms import Storm

pytestmark = pytest.mark.integration


@pytest.fixture
def s(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    yield repo, Storm(repo)


def test_a_deploy_on_a_cascade_victim_is_not_blamed(s):
    """payments-gw breaks first; payments (nearer the alert) happens to deploy half a minute later and goes red.
    Nearest-first would blame the payments deploy; the graph shows payments-gw, upstream, was red before it."""
    repo, st = s
    st.change("payments-gw", 30, "gw-x", "config"), st.red("payments-gw", 28)
    st.change("payments", 27.5, "pay-x"), st.red("payments", 26.7), st.red("checkout", 10)
    o = respond(repo, st.alert("checkout", 2), MockProvider())["outcome"]
    assert o["root_cause"]["change"] == "chg:gw-x"
    assert "already red when this change landed" in {r["change"]: r["reason"] for r in o["refuted"]}["chg:pay-x"]


def test_a_monitoring_gap_on_a_middle_hop_still_names_the_cause(s):
    repo, st = s
    st.change("payments-gw", 30, "gw-x", "config"), st.red("payments-gw", 28), st.red("checkout", 10)  # payments silent
    o = respond(repo, st.alert("checkout", 2), MockProvider())["outcome"]
    assert o["root_cause"]["change"] == "chg:gw-x" and "monitoring gap" in o["root_cause"]["reason"]
    assert "check its monitoring" in o["update_text"]


def test_a_stale_upstream_blip_is_not_a_cascade(s):
    """payments-gw had one blip an hour earlier and an unrelated change; the real cause is a fresh payments deploy."""
    repo, st = s
    st.change("payments-gw", 100, "gw-old", "config"), st.red("payments-gw", 95, "errors")
    st.change("payments", 30, "pay-x"), st.red("payments", 28), st.red("checkout", 10)
    o = respond(repo, st.alert("checkout", 2), MockProvider())["outcome"]
    assert o["root_cause"]["change"] == "chg:pay-x"


def test_a_dependency_that_starts_after_the_alert_is_not_called_retired(s):
    from oncall_brain.agents.registry import ToolContext, call
    from tests.integration.test_storms import MIN, T

    repo, st = s
    st.change("search", 20, "search-x"), st.red("search", 15), st.red("shipping", 10)
    call("add_dependency", ToolContext(repo), {"caller": "svc:shipping", "callee": "svc:search", "at": T + 10 * MIN})
    o = respond(repo, st.alert("shipping", 2), MockProvider())["outcome"]
    reasons = {r["change"]: r["reason"] for r in o["refuted"]}
    assert "only started depending on search after the alert" in reasons["chg:search-x"]
