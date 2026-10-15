"""The product's claims, checked against a real FalkorDB."""

import pytest

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.datagen import ACTS
from oncall_brain.services.respond import resolve, respond
from oncall_brain.services.seeding import reset, seed

pytestmark = pytest.mark.integration


def _counts(repo):
    g = repo._graph
    return (g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0],
            g.ro_query("MATCH ()-[e]->() RETURN count(e)").result_set[0][0])


def test_ingest_is_idempotent_and_seed_rebuilds_from_scratch(store, tenant):
    from oncall_brain.datagen import generate
    from oncall_brain.services.seeding import load

    seed(store, tenant)
    repo = store.tenant(tenant)
    before = _counts(repo)
    load(repo, generate(7))  # MERGE on stable ids: a second load changes nothing
    assert _counts(repo) == before and before[0] > 200
    respond(repo, ACTS[1], MockProvider())  # dirty the graph, then re-seed: back to exactly the seed
    seed(store, tenant)
    assert _counts(repo) == before
    reset(store, tenant)
    assert _counts(repo) == before


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


def test_who_knows_still_works_after_incidents_paged_people(store, tenant):
    from oncall_brain.agents.registry import ToolContext, call

    seed(store, tenant)
    repo = store.tenant(tenant)
    respond(repo, ACTS[1], MockProvider())  # writes PAGED edges, which used to crash who_knows
    experts = call("who_knows", ToolContext(repo), {"service": "svc:payments-gw"}).data
    assert experts and any(e["incidents"] >= 1 for e in experts)


def test_concurrent_responders_do_not_duplicate_work_or_edges(store, tenant):
    from concurrent.futures import ThreadPoolExecutor

    seed(store, tenant)
    repo = store.tenant(tenant)
    with ThreadPoolExecutor(4) as pool:
        runs = list(pool.map(lambda _: respond(store.tenant(tenant), ACTS[1], MockProvider()), range(4)))
    checks = sum(s.tool == "check_hypothesis" for r in runs for s in r["steps"])
    assert checks == 5  # the lock serialises runs; later runs find a finished board and only hand off
    dup = repo._graph.ro_query(
        "MATCH (a)-[e]->(b) WITH a, b, type(e) AS t, count(e) AS n WHERE n > 1 RETURN count(*)").result_set[0][0]
    assert dup == 0


def test_a_bad_tool_choice_falls_back_instead_of_aborting(store, tenant):
    from oncall_brain.domain.models import Decision
    from oncall_brain.domain.planner import next_decision

    class SloppyLLM:  # follows the planner but drops the hyp: prefix, like a careless model
        name = "sloppy"

        def decide(self, role, board, tools):
            d = next_decision(role, board)
            if d.tool == "check_hypothesis":
                return Decision(action="call", tool=d.tool, reason="llm", args={
                    "hypothesis_id": d.args["hypothesis_id"].removeprefix("hyp:")})
            return d

    seed(store, tenant)
    o = respond(store.tenant(tenant), ACTS[1], SloppyLLM())["outcome"]
    assert o["root_cause"]["change"] == "chg:pgw-pool-1" and o["update_text"]


def test_step_budget_hands_on_instead_of_failing(store, tenant, monkeypatch):
    from oncall_brain.agents import loop

    monkeypatch.setattr(loop, "MAX_STEPS_PER_ROLE", 4)
    seed(store, tenant)
    run = respond(store.tenant(tenant), ACTS[1], MockProvider())
    assert any("budget" in s.reason for s in run["steps"]) and run["outcome"]["update_text"]


def test_stale_pristine_copy_is_rebuilt(store, tenant):
    seed(store, tenant)
    store.tenant(tenant).write("ingest_meta", version="old-generator", seed=7)
    store.snapshot(tenant)
    assert reset(store, tenant) == "seeded"
    assert reset(store, tenant) == "restored"


def test_confirmed_cause_survives_a_recheck_and_update_rewrite(store, tenant):
    from oncall_brain.agents.registry import ToolContext, call

    seed(store, tenant)
    repo = store.tenant(tenant)
    run = respond(repo, ACTS[1], MockProvider())
    resolve(repo, run["incident_id"], "chg:pgw-pool-1")
    ctx = ToolContext(repo)
    call("check_hypothesis", ctx, {"hypothesis_id": "hyp:checkout-latency:pgw-pool-1"})
    board = call("incident_board", ctx, {"incident_id": run["incident_id"]}).data
    assert {h["status"] for h in board["hypotheses"] if h["change_id"] == "chg:pgw-pool-1"} == {"confirmed"}
    text = call("post_update", ctx, {"incident_id": run["incident_id"]}).data["text"]
    assert "Likely cause" in text and "Next action" in text


def test_live_events_drive_a_new_investigation(store, tenant):
    """Knowledge kept current through the event tools: a brand-new alert is investigated end to end, and a
    dependency retired a minute ago already changes the verdict."""
    from oncall_brain.agents.registry import ToolContext, call
    from oncall_brain.datagen import DAY, T1

    seed(store, tenant)
    repo = store.tenant(tenant)
    ctx = ToolContext(repo)
    t = T1 + DAY  # a quiet day in the seeded history
    call("record_change", ctx, {"service": "svc:inventory", "kind": "deploy", "summary": "Deploy inventory v9",
                                "at": t - 1800, "id": "chg:inv-9"})
    call("record_change", ctx, {"service": "svc:cart", "kind": "config", "summary": "Tune cart TTL",
                                "at": t - 900, "id": "chg:cart-ttl"})
    for svc, dt in (("svc:inventory", 1700), ("svc:cart", 800), ("svc:checkout", 600)):
        call("record_anomaly", ctx, {"service": svc, "kind": "errors", "summary": "5xx up", "at": t - dt})
    call("retire_dependency", ctx, {"caller": "svc:checkout", "callee": "svc:cart", "at": t - 3600})
    assert call("retire_dependency", ctx, {"caller": "svc:checkout", "callee": "svc:cart", "at": t}).data == {
        "retired": 0}  # idempotent: nothing live left to retire
    alert = call("raise_alert", ctx, {"service": "svc:checkout", "symptom": "errors", "name": "checkout 5xx",
                                      "at": t}).data["alert"]
    o = respond(repo, alert, MockProvider())["outcome"]
    assert o["root_cause"]["change"] == "chg:inv-9"
    reasons = {r["change"]: r["reason"] for r in o["refuted"]}
    assert "no longer depends on cart" in reasons["chg:cart-ttl"]  # the edge retired an hour ago


def test_act3_alert_storm_is_correlated_and_only_then_solved(store, tenant):
    class NoCorrelation(MockProvider):
        def decide(self, role, board, tools):
            return super().decide(role, {**board, "storm": 0}, tools)

    seed(store, tenant)
    repo = store.tenant(tenant)
    run = respond(repo, ACTS[3], MockProvider())
    corr = next(s for s in run["steps"] if s.tool == "correlate_alerts").data
    assert {a["service"] for a in corr["alerts"]} == {"svc:checkout", "svc:refunds"}
    assert corr["shared"][0]["service"] == "svc:payments"  # betweenness: where the dependency paths converge
    o = run["outcome"]
    assert o["root_cause"]["change"] == "chg:pg-conn-3" and o["checks_to_culprit"] == 1
    assert "cannot explain the alerts" in {r["change"]: r["reason"] for r in o["refuted"]}["chg:subs-88"]
    assert not o["runbook"]  # no runbook led here, so none is suggested
    reset(store, tenant)
    assert respond(repo, ACTS[3], NoCorrelation())["outcome"]["root_cause"]["change"] == "chg:subs-88"
