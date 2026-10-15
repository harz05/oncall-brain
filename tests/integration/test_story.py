"""The product's claims, checked against a real FalkorDB."""

import pytest

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.datagen import ACTS
from oncall_brain.services.respond import resolve, respond
from oncall_brain.services.seeding import reset, seed

pytestmark = pytest.mark.integration


def _counts(repo):
    return repo.read("incident_head", incident_id="none"), repo._graph.ro_query(
        "MATCH (n) RETURN count(n)").result_set[0][0]


def test_seeding_is_idempotent(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    n1 = _counts(repo)[1]
    seed(store, tenant)
    assert _counts(repo)[1] == n1 > 200


def test_read_tools_cannot_write(store, tenant):
    seed(store, tenant)
    with pytest.raises(Exception, match="read-only"):
        store.tenant(tenant).read("record_page", incident_id="x", person="y", at=0, service="z")


def test_act1_finds_the_planted_cause_and_refutes_every_decoy(store, tenant):
    seed(store, tenant)
    o = respond(store.tenant(tenant), ACTS[1], MockProvider())["outcome"]
    assert o["root_cause"]["change"] == "chg:pgw-pool-1"
    assert o["root_cause"]["live_path"] == ["svc:checkout", "svc:payments", "svc:payments-gw"]
    reasons = {r["change"]: r["reason"] for r in o["refuted"]}
    assert "no dependency path" in reasons["chg:search-420"]
    assert "retired" in reasons["chg:legacy-193"]
    assert "rolled back" in reasons["chg:pricing-2140"]
    assert "no anomaly" in reasons["chg:cart-310"]
    assert o["baseline_pick"]["change"] == "chg:search-420" and not o["baseline_correct"]
    assert "svc:refunds" in o["at_risk"]


def test_act2_is_solved_from_act1_memory_and_slower_without_it(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    cold = respond(repo, ACTS[2], MockProvider())["outcome"]
    assert not cold["memory"]["solved_by_memory"]

    reset(store, tenant)
    act1 = respond(repo, ACTS[1], MockProvider())
    learned = resolve(repo, act1["incident_id"], act1["outcome"]["root_cause"]["change"])
    assert learned["data"]["runbook"] == "rb:payments-gw:config"
    warm = respond(repo, ACTS[2], MockProvider())["outcome"]
    assert warm["memory"]["solved_by_memory"] and warm["root_cause"]["change"] == "chg:pgw-pool-2"
    assert warm["hypotheses_checked"] < cold["hypotheses_checked"]
    assert warm["investigator_calls"] < cold["investigator_calls"]


def test_agent_steps_persist_in_the_graph_and_respond_is_idempotent(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    run = respond(repo, ACTS[1], MockProvider())
    steps = repo.read("incident_steps", incident_id=run["incident_id"]).rows
    assert [s["tool"] for s in steps] == [s.tool for s in run["steps"]]
    assert {"triage", "investigator", "comms"} <= {s["role"] for s in steps}
    again = respond(repo, ACTS[1], MockProvider())  # board already complete: every role just hands off
    assert all(s.tool in ("open_incident", "handoff") for s in again["steps"])


def test_tenants_are_isolated(store, tenant):
    seed(store, tenant)
    other = tenant[:30] + "_b"
    store.drop(other)
    try:
        seed(store, other)
        respond(store.tenant(tenant), ACTS[1], MockProvider())
        assert not store.tenant(other).read("incident_head", incident_id="inc:checkout-latency").rows
    finally:
        store.drop(other)


def test_company_brain_who_knows_and_change_sources(store, tenant):
    from oncall_brain.agents.registry import ToolContext, call

    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    experts = call("who_knows", ctx, {"service": "svc:payments-gw"}).data
    assert experts[0]["on_owning_team"] and experts[0]["changes"] >= 1
    assert experts == sorted(experts, key=lambda r: -r["score"])
    story = call("change_story", ctx, {"change_id": "chg:pgw-pool-1"}).data
    assert {s["id"] for s in story["sources"]} == {"ticket:CR-881", "msg:pay-deploys-1"}
    assert story["team"] == "Payments"
