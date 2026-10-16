"""Ownership with history: OWNS {valid_from, valid_to}, the transfer_ownership event, and what follows from it in the
graph: "who owns" flips, "who owned X at the time of inc:0911" does not, who_knows keeps the old team, and an alert
pages the owner at the alert's time, not today's."""

import pytest

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.agents.registry import ToolContext, call
from oncall_brain.datagen import ACTS, DAY, EPOCH, T1
from oncall_brain.services.respond import respond
from oncall_brain.services.seeding import reset, seed

HANDOVER = "2026-10-16 04:00 UTC"  # T1 + DAY
FLASH_SALE = "2026-08-16 04:00 UTC"  # inc:0911 opened at T1 - 60 DAY


def _owner_of(ctx: ToolContext, service: str, at: int) -> str:
    return next(r["team"] for r in call("service_map", ctx, {"at": at}).data if r["id"] == service)


def test_transfer_ownership_flips_who_owns_but_not_who_owned_at_the_time(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    before = call("ask", ctx, {"question": "who owns payments-gw"}).data
    assert before["answer"].startswith("payments-gw is owned by Payments;")
    moved_at = T1 + DAY
    out = call("transfer_ownership", ctx, {"service": "svc:payments-gw", "team": "team:platform", "at": moved_at})
    assert out.summary == f"svc:payments-gw: team:payments -> team:platform from {moved_at}"
    assert out.data["transferred"] and out.data["previous"] == "team:payments"
    # The old edge is closed, never deleted: the history is the two edges.
    assert [(e["team"], e["from"], e.get("until")) for e in out.data["history"]] == [
        ("team:payments", EPOCH, moved_at), ("team:platform", moved_at, None)]
    assert ("team:platform", "svc:payments-gw", "OWNS") in out.highlight.edges

    after = call("ask", ctx, {"question": "who owns payments-gw"})
    assert after.data["answer"].startswith(
        f"payments-gw is owned by Platform (since {HANDOVER}, before that Payments);")
    assert ("team:platform", "svc:payments-gw", "OWNS") in after.highlight.edges
    assert ("team:payments", "svc:payments-gw", "OWNS") not in after.highlight.edges
    then = call("ask", ctx, {"question": "who owned payments-gw at the time of inc:0911"}).data
    assert then["intent"] == "owner" and [e["id"] for e in then["linked"]] == ["svc:payments-gw", "inc:0911"]
    assert then["answer"].startswith(
        f"payments-gw was owned by Payments at {FLASH_SALE}, the time of inc:0911 (until {HANDOVER}, then Platform);")
    assert "members: Asha Nakamura, Lena Costa, Quinn Tanaka, Sana Brandt." in then["answer"]
    # who_knows keeps the team that ran the service: they score 2 for having owned it, the new owners 3.
    rows = call("who_knows", ctx, {"service": "svc:payments-gw"}).data
    former = {r["name"] for r in rows if r["on_former_owning_team"]}
    assert former and all(r["team"] == "Payments" and not r["on_owning_team"] for r in rows if r["name"] in former)
    assert all(r["on_owning_team"] for r in rows if r["team"] == "Platform")
    assert "owned it before" in after.data["answer"]
    # Idempotent: the owner taking over again changes nothing; an unknown team is refused.
    again = call("transfer_ownership", ctx, {"service": "svc:payments-gw", "team": "team:platform",
                                             "at": moved_at + DAY})
    assert not again.data["transferred"] and len(again.data["history"]) == 2
    assert again.summary == "team:platform already owns svc:payments-gw"
    with pytest.raises(ValueError):
        call("transfer_ownership", ctx, {"service": "svc:payments-gw", "team": "team:nope"})
    # The service map shows the owner at the time asked.
    assert _owner_of(ctx, "svc:payments-gw", moved_at - 1) == "Payments"
    assert _owner_of(ctx, "svc:payments-gw", moved_at) == "Platform"
    # The handover is memory of the tenant: a reset restores the seeded owner.
    reset(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    assert call("ask", ctx, {"question": "who owns payments-gw"}).data["answer"].startswith(
        "payments-gw is owned by Payments;")


def test_a_follow_up_can_say_it_about_an_incident(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    who = {"user": "person:hana-costa", "session": "t"}
    first = call("ask", ctx, {"question": "what happened in inc:0911", **who}).data
    assert first["intent"] == "happened" and first["answer"].startswith("What happened in inc:0911, newest first: ")
    assert first["linked"][0]["id"] == "inc:0911" and first["sources"][0] == "inc:0911"
    d = call("ask", ctx, {"question": "who owned payments-gw at the time of it", **who}).data
    assert d["resolved"]["as"] == ["inc:0911"] and d["answer"].startswith(
        f'Taking "it" as inc:0911, from your earlier question "what happened in inc:0911". payments-gw was owned by '
        f"Payments at {FLASH_SALE}, the time of inc:0911;")


def test_paging_follows_the_owner_at_alert_time(store, tenant):
    """Act 1's alert (T1) pages the team that owned payments-gw then: a handover the day after changes nothing for it,
    a handover the day before pages the new team."""
    seed(store, tenant)
    repo = store.tenant(tenant)
    call("transfer_ownership", ToolContext(repo), {"service": "svc:payments-gw", "team": "team:platform",
                                                   "at": T1 + DAY})
    o = respond(repo, ACTS[1], MockProvider())["outcome"]
    assert {p["team_name"] for p in o["paged"]} == {"Checkout", "Payments"}
    reset(store, tenant)
    repo = store.tenant(tenant)
    call("transfer_ownership", ToolContext(repo), {"service": "svc:payments-gw", "team": "team:platform",
                                                   "at": T1 - DAY})
    o = respond(repo, ACTS[1], MockProvider())["outcome"]
    assert {p["team_name"] for p in o["paged"]} == {"Checkout", "Platform"}
    assert o["root_cause"]["change"] == "chg:pgw-pool-1"  # the investigation itself does not care who owns what
