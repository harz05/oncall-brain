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


def test_concurrent_responders_to_one_storm_make_one_incident(store, tenant):
    from concurrent.futures import ThreadPoolExecutor

    from oncall_brain.datagen import ACTS

    seed(store, tenant)
    alerts = ["alert:checkout-latency-3", "alert:refunds-latency-3", ACTS[3]]
    with ThreadPoolExecutor(3) as pool:
        runs = list(pool.map(lambda a: respond(store.tenant(tenant), a, MockProvider()), alerts))
    assert len({r["incident_id"] for r in runs}) == 1  # whoever ran first folded the others in; the rest joined
    assert sum(r["joined"] is not None for r in runs) == 2
    o = runs[-1]["outcome"]
    assert o["root_cause"]["change"] == "chg:pg-conn-3"
    incidents = store.tenant(tenant)._graph.ro_query("MATCH (i:Incident {status:'open'}) RETURN count(i)").result_set
    assert incidents[0][0] == 1
    teams = [p["team_name"] for p in o["paged"]]
    assert len(teams) == len(set(teams))  # one page per team


def test_a_chained_storm_is_one_incident_by_wcc_and_the_far_cause_is_a_co_cause(storm):
    """search and reporting share no red service, but each shares one with checkout (redis-cache, kafka): WCC on the
    projection puts the three alerts in one incident; legacy-billing, red on its own, is a separate storm. The
    investigation follows: suspects come from every folded alert, and kafka-x, unreachable from search, is judged
    from reporting and kept as the co-cause that alone explains it."""
    repo, s = storm
    s.change("redis-cache", 40, "redis-x", "config"), s.red("redis-cache", 35)
    s.change("kafka", 38, "kafka-x"), s.red("kafka", 33), s.red("analytics", 30)
    s.red("search", 12), s.red("checkout", 10), s.red("reporting", 9)
    s.change("legacy-billing", 30, "lb-x"), s.red("legacy-billing", 20, "errors")
    origin = s.alert("search", 8)
    s.alert("checkout", 6), s.alert("reporting", 5)
    lb = s.alert("legacy-billing", 4, "errors")
    run = respond(repo, origin, MockProvider())
    o = run["outcome"]
    assert {a["service"] for a in o["storm"]["alerts"]} == {"svc:checkout", "svc:reporting"}
    step = next(x for x in run["steps"] if x.tool == "correlate_alerts")
    assert [q.name for q in step.queries][-4:] == ["storm_upstream", "project_storm", "storm_components",
                                                   "record_correlation"]
    assert step.summary.endswith("; 1 other alert(s) form 1 separate storm")
    assert o["root_cause"]["change"] == "chg:redis-x" and o["root_cause"]["explained"] == ["svc:checkout", "svc:search"]
    assert [(c["change"], c["reason"]) for c in o["co_causes"]] == [("chg:kafka-x", "also needed: it alone explains "
                                                                                    "reporting")]
    assert [(r["change"], r["tag"]) for r in o["refuted"]] == [("chg:lb-x", "no dependency path")]
    assert o["confidence"]["why"] == ("it explains 2 of 3 alerting services; 1 other change also needed to explain "
                                      "every alert")
    update = repo.read("incident_update", incident_id=run["incident_id"]).rows[0]["text"]
    assert "Also contributing: kafka-x on kafka (it alone explains reporting)" in update
    # Seen from legacy-billing's alert, the other three are one separate storm and it is investigated on its own.
    inc = call("open_incident", s.ctx, {"alert_id": lb}).data["incident"]
    out = call("correlate_alerts", s.ctx, {"incident_id": inc})
    assert out.data == {"alerts": [], "shared": [], "separate": [["svc:checkout", "svc:reporting", "svc:search"]]}
    assert out.summary.startswith("3 other alert(s) in the window share no upstream service that went red with this "
                                  "one, directly or through another alert (1 separate storm)")
