"""Alert storms built from live events (the event tools), each checked against what an engineer would conclude.
Scenarios come from the third review round, where each one broke an earlier version of the storm logic."""

import pytest

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.agents.registry import ToolContext, call
from oncall_brain.datagen import DAY, MIN, T3
from oncall_brain.services.respond import respond
from oncall_brain.services.seeding import seed

pytestmark = pytest.mark.integration
T = T3 + 2 * DAY  # a quiet day after the seeded acts


class Storm:
    def __init__(self, repo):
        self.ctx = ToolContext(repo)

    def change(self, svc, mins, cid, kind="deploy"):
        call("record_change", self.ctx, {"service": f"svc:{svc}", "kind": kind, "summary": f"{cid} on {svc}",
                                         "at": T - mins * MIN, "id": f"chg:{cid}"})

    def red(self, svc, mins, kind="latency"):
        call("record_anomaly", self.ctx, {"service": f"svc:{svc}", "kind": kind, "summary": kind,
                                          "at": T - mins * MIN})

    def alert(self, svc, mins, symptom="latency"):
        return call("raise_alert", self.ctx, {"service": f"svc:{svc}", "symptom": symptom, "name": f"{svc} {symptom}",
                                              "at": T - mins * MIN}).data["alert"]


@pytest.fixture
def storm(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    yield repo, Storm(repo)


def _payments_gw_outage(s):  # payments-gw config change; the slowdown reaches checkout, refunds, subscriptions
    s.change("payments-gw", 40, "pgw-x", "config")
    s.red("payments-gw", 35), s.red("payments", 33), s.red("checkout", 10), s.red("refunds", 9)


def test_unrelated_alert_sharing_only_a_quiet_cache_is_not_folded(storm):
    repo, s = storm
    _payments_gw_outage(s)
    s.change("search", 20, "search-x"), s.red("search", 15, "errors")
    s.alert("search", 8, "errors"), s.alert("checkout", 6)
    o = respond(repo, s.alert("refunds", 2), MockProvider())["outcome"]
    assert o["root_cause"]["change"] == "chg:pgw-x"
    assert {a["service"] for a in o["storm"]["alerts"]} == {"svc:checkout"}


def test_a_second_independent_cause_is_a_co_cause_not_ruled_out(storm):
    repo, s = storm
    _payments_gw_outage(s)
    s.change("cart", 30, "cart-x"), s.red("cart", 25, "errors")
    s.alert("cart", 8, "errors"), s.alert("refunds", 6)
    o = respond(repo, s.alert("checkout", 2), MockProvider())["outcome"]
    causes = {o["root_cause"]["change"], *(c["change"] for c in o["co_causes"])}
    assert causes == {"chg:cart-x", "chg:pgw-x"} and not o["refuted"]
    assert {p["team_name"] for p in o["paged"]} >= {"Payments", "Checkout"}
    assert "Also contributing" in o["update_text"]


def test_alerts_on_the_same_service_are_one_incident(storm):
    repo, s = storm
    _payments_gw_outage(s)
    s.alert("checkout", 6, "errors")
    o = respond(repo, s.alert("checkout", 2), MockProvider())["outcome"]
    assert [a["service"] for a in o["storm"]["alerts"]] == ["svc:checkout"]
    assert o["root_cause"]["change"] == "chg:pgw-x"


def test_a_memory_suspect_that_explains_part_of_a_storm_does_not_end_the_search(storm):
    repo, s = storm
    s.change("payments-gw", 40, "pgw-x", "config")
    s.red("payments-gw", 35), s.red("payments", 33), s.red("refunds", 9), s.red("subscriptions", 8)
    s.red("checkout", 7)
    s.change("inventory", 30, "inv-x"), s.red("inventory", 25)  # inc:0911's runbook points memory here
    s.alert("refunds", 6), s.alert("subscriptions", 4)
    o = respond(repo, s.alert("checkout", 2), MockProvider())["outcome"]
    assert o["root_cause"]["change"] == "chg:pgw-x"
    assert "chg:inv-x" in {r["change"] for r in o["refuted"]}


def test_of_two_changes_that_explain_everything_the_one_the_service_went_red_after_wins(storm):
    repo, s = storm
    s.change("postgres-orders", 40, "pg-a", "config"), s.change("postgres-orders", 30, "pg-b")
    s.red("postgres-orders", 37), s.red("postgres-orders", 25), s.red("payments", 35), s.red("payments", 24)
    for svc, m in (("checkout", 10), ("refunds", 9), ("subscriptions", 8)):
        s.red(svc, m)
    s.alert("checkout", 6), s.alert("refunds", 4)
    o = respond(repo, s.alert("subscriptions", 2), MockProvider())["outcome"]
    assert o["root_cause"]["change"] == "chg:pg-a"
    assert o["anomaly_baseline_correct"]
