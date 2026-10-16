"""Company brain: free-form questions answered from the graph first (entity linking + intent routing), then from docs,
tickets and chat with their sources."""

import pytest

from oncall_brain.agents.registry import ToolContext, call
from oncall_brain.datagen import DAY, T1, generate
from oncall_brain.scenarios import scenario
from oncall_brain.services import respond  # noqa: F401  (registers who_knows / change_story)
from oncall_brain.services.brain import link, padded
from oncall_brain.services.seeding import load, reset, seed


def _name(person_id: str) -> str:
    return next(p["name"] for p in generate(7)["people"] if p["id"] == person_id)


def _author(change_id: str) -> str:
    return next(c["author"] for c in generate(7)["changes"] if c["id"] == change_id)


def _on_call(team: str, at: int) -> str:
    return _name(next(o["person"] for o in generate(7)["on_call"] if o["team"] == team and o["start"] <= at < o["end"]))


def test_ask_links_entities_by_whole_words_longest_first(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    q = padded("Does Hana Costa know the cartography of payments-gw, the checkout team, pgw-pool-1 or CR-881?")
    got = {e["id"]: e["matched"] for e in link(repo.read("link_entities", q=q).rows, q)}
    # Full name over first name, payments-gw not payments, service checkout over team Checkout, no cart in
    # cartography; a change by its short id, a ticket by its key.
    assert got == {"person:hana-costa": "hana costa", "svc:payments-gw": "payments-gw", "svc:checkout": "checkout",
                   "chg:pgw-pool-1": "pgw-pool-1", "ticket:CR-881": "cr-881"}


def test_ask_who_owns_kafka_answers_from_owns_and_the_rotation(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    out = call("ask", ctx, {"question": "who owns kafka"})
    d = out.data
    assert d["intent"] == "owner" and d["linked"] == [{"id": "svc:kafka", "kind": "service", "name": "kafka",
                                                        "matched": "kafka", "carried": False}]
    latest = max(a["at"] for a in generate(7)["alerts"])  # no `at` given: the latest alert is "now"
    assert d["answer"].startswith(f"kafka is owned by Platform; {_on_call('team:platform', latest)} (")
    assert "latest alert in the graph" in d["answer"] and "People who know kafka:" in d["answer"]
    assert ("team:platform", "svc:kafka", "OWNS") in out.highlight.edges
    assert d["hits"][0]["id"] != "doc:design-shipping-notify"  # support written by the owners, not a passing mention
    assert [q.name for q in out.queries][:3] == ["link_entities", "ownership", "who_knows"]
    at = T1 - 10 * DAY
    d = call("ask", ctx, {"question": "who is on call for kafka", "at": at}).data
    assert f"{_on_call('team:platform', at)} (" in d["answer"] and "at 2026-10-05 04:00 UTC" in d["answer"]


def test_ask_how_to_roll_back_cart_offers_the_general_page_not_an_inventory_postmortem(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    out = call("ask", ctx, {"question": "how do I roll back a bad deploy on cart"})
    d = out.data
    assert d["intent"] == "how" and d["answer"].startswith("No runbook for cart on record")
    assert d["hits"][0]["id"] == d["sources"][0] == "doc:runbook-rollback" and "general, for any service" in d[
        "answer"]
    # A service with procedural memory gets its Runbook (with its track record) and the incident it fixed.
    d = call("ask", ctx, {"question": "how do I roll back a bad deploy on inventory"}).data
    assert d["answer"].startswith("Runbook for inventory: 'Roll back inventory deploy' (rb:inventory-rollback, "
                                  "worked 1 of 1 times)") and "inc:0911" in d["answer"]


def test_ask_why_names_the_decision_of_record_and_flags_what_it_superseded(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    out = call("ask", ctx, {"question": "why was legacy-billing retired"})
    d = out.data
    assert d["intent"] == "why" and d["hits"][0]["id"] == d["sources"][0] == "doc:adr-012"
    assert d["answer"].startswith("The decision of record for legacy-billing is 'ADR-012")
    assert "it supersedes 'Design: checkout invoices from legacy-billing'" in d["answer"]
    assert {("doc:adr-012", "svc:legacy-billing", "DECIDES"),
            ("doc:adr-012", "doc:design-invoicing", "SUPERSEDES")} <= set(out.highlight.edges)
    d = call("ask", ctx, {"question": "why was pgw-pool-1 made"}).data  # a linked change: its story
    assert d["answer"].startswith(f"chg:pgw-pool-1 (config on payments-gw: 'Lower payments-gw HTTP pool max_connections"
                                  f" 200 -> 20 (cost cleanup)') was made by {_name(_author('chg:pgw-pool-1'))}")
    assert d["hits"][0]["id"] == "doc:cost-review-pgw" and "ticket:CR-881" in d["sources"]


def test_ask_who_knows_and_what_happened(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    d = call("ask", ctx, {"question": "who knows payments-gw"}).data
    assert d["intent"] == "expert"
    assert d["answer"].startswith(f"People who know payments-gw: {_name(_author('chg:pgw-pool-1'))} (Payments")
    d = call("ask", ctx, {"question": "what happened to auth"}).data
    auth = [i["id"] for i in sorted(generate(7)["incidents"], key=lambda i: -i["opened_at"])
            if "svc:auth" in (i["service"], i["paged_for"])]
    assert d["intent"] == "happened" and d["sources"][:len(auth)] == auth
    assert d["answer"].startswith(f"Incidents on auth, newest first: {auth[0]} ")


def test_ask_traces_why_the_payments_gateway_pool_was_lowered(store, tenant):
    seed(store, tenant)
    out = call("ask", ToolContext(store.tenant(tenant)), {"question": "Why was the payments gateway pool lowered?"})
    d = out.data
    # "payments" links, but no doc DECIDES payments: no graph fact to lead with, so the full-text answer stands.
    assert d["intent"] == "search" and [e["id"] for e in d["linked"]] == ["svc:payments"]
    assert d["hits"][0]["id"] == "doc:cost-review-pgw" and d["sources"][0] == "doc:cost-review-pgw"
    assert {"ticket:CR-881", "doc:pm-load-test-pgw"} <= set(d["sources"])  # the request and the warning it ignored
    assert "chg:pgw-pool-1" in d["answer"] and _name(_author("chg:pgw-pool-1")) in d["answer"]
    assert "200 to 20" in d["answer"]  # the reason is quoted from the doc, not paraphrased
    rel = {r["id"]: r for r in d["related"]}
    assert rel["chg:pgw-pool-1"]["via"] == "doc:cost-review-pgw MENTIONS chg:pgw-pool-1"
    assert rel["svc:payments-gw"]["kind"] == "service" and rel["team:payments"]["kind"] == "team"
    assert {("doc:cost-review-pgw", "chg:pgw-pool-1", "MENTIONS"), ("chg:pgw-pool-1", "svc:payments-gw", "CHANGED"),
            ("team:payments", "svc:payments-gw", "OWNS")} <= set(out.highlight.edges)
    assert [q.name for q in out.queries] == ["link_entities", "decisions_about", "search_knowledge",
                                             "knowledge_context"]
    assert all(q.readonly for q in out.queries)


def test_ask_puts_current_docs_first_and_flags_superseded_ones(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    d = call("ask", ctx, {"question": "who designed the checkout retries"}).data
    v2 = next(x for x in generate(7)["docs"] if x["id"] == "doc:design-retries-v2")
    assert d["hits"][0]["id"] == "doc:design-retries-v2" and d["answer"].count(_name(v2["author"])) >= 1
    old = next(h for h in d["hits"] if h["id"] == "doc:design-retries-v1")
    assert old["superseded_by"] == "doc:design-retries-v2" and "It replaces 'Design: checkout payment retries" in d[
        "answer"]
    d = call("ask", ctx, {"question": "why was legacy-billing retired from checkout"}).data  # checkout's ADR loses
    assert d["hits"][0]["id"] == "doc:adr-012" and "decision of record for legacy-billing" in d["answer"]
    d = call("ask", ctx, {"question": "what is the kafka retention"}).data
    assert d["hits"][0]["id"] == "doc:adr-011" and "It replaces 'ADR-006" in d["answer"]
    assert next(h for h in d["hits"] if h["id"] == "doc:adr-006")["superseded_by"] == "doc:adr-011"


def test_ask_without_content_words_or_matches_answers_plainly(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    for q in ("the", "a", "why was it?"):
        out = call("ask", ctx, {"question": q})
        assert out.data["hits"] == [] and out.data["answer"] and not out.queries  # nothing reaches the index
    out = call("ask", ctx, {"question": "zebra unicorn"})
    assert out.data["hits"] == [] and "zebra" in out.data["answer"]
    assert out.data["linked"] == [] and out.data["intent"] == "search"


def test_who_knows_counts_doc_authorship_and_change_story_cites_docs(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    experts = call("who_knows", ctx, {"service": "svc:payments-gw"}).data
    by_id = {e["person"]: e for e in experts}
    author = _author("chg:pgw-pool-1")  # also wrote the cost review and the chat about it
    assert experts[0]["person"] == author and by_id[author]["docs"] >= 2
    outsider = [e for e in experts if not e["on_owning_team"]]  # only docs can put someone off the team on the list
    assert outsider and all(e["docs"] and not e["changes"] for e in outsider)
    # Writing about a service supports hands-on evidence but never outweighs it (docs count at most 3).
    assert all(e["score"] == 3 * e["on_owning_team"] + 2 * e["changes"] + e["incidents"] + min(e["docs"], 3)
               for e in experts)
    story = call("change_story", ctx, {"change_id": "chg:pgw-pool-1"}).data
    docs = [s for s in story["sources"] if s["kind"] == "Doc"]
    assert [s["id"] for s in docs] == ["doc:cost-review-pgw"] and docs[0]["by"] == _name(author)


def test_fulltext_index_is_idempotent_survives_reset_and_scenarios_still_load(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    repo.ensure_schema()  # second time: every index already exists
    assert reset(store, tenant) == "restored"  # GRAPH.COPY carries the full-text indexes
    assert call("ask", ToolContext(repo), {"question": "postgres-orders connection limit"}).data["hits"]
    store.drop(tenant)
    data = scenario(3)["data"]  # the eval's graphs keep datagen's docs, whose changes and incidents are gone
    assert data["docs"]
    load(repo, data)
    rows = repo.read("knowledge_context", ids=["doc:cost-review-pgw"]).rows
    assert rows and {r["label"] for r in rows} <= {"Service", "Person", "Doc", "Message", "Ticket", "Initiative"}


def test_a_new_decision_record_flips_the_ask_answer_and_flags_the_old_one(store, tenant):
    """Keeping knowledge current: record_doc writes a new decision of record; ask puts it first at once."""
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    before = call("ask", ctx, {"question": "what is the kafka retention"}).data
    assert before["hits"][0]["id"] == "doc:adr-011"
    out = call("record_doc", ctx, {"kind": "decision", "id": "doc:adr-015",
                                   "title": "ADR-015: Kafka retention of 14 days",
                                   "text": "Decision: raise the kafka retention from 7 days to 14 days so a weekend "
                                           "consumer outage no longer loses events. Supersedes ADR-011.",
                                   "decides": "svc:kafka", "mentions": ["svc:kafka"], "supersedes": "doc:adr-011",
                                   "author": "person:hana-costa"})
    assert out.data["supersedes"] == "doc:adr-011" and "decision of record for svc:kafka" in out.summary
    after = call("ask", ctx, {"question": "what is the kafka retention"}).data
    assert after["hits"][0]["id"] == "doc:adr-015" and "14 days" in after["answer"]
    assert "It replaces 'ADR-011" in after["answer"]  # the old decision is named as replaced...
    old = [h for h in after["hits"] if h["id"] == "doc:adr-011"]  # ...and, if it still ranks in the top hits, flagged
    assert all(h["superseded_by"] == "doc:adr-015" for h in old)
    with pytest.raises(ValueError):
        call("record_doc", ctx, {"kind": "design", "title": "x", "text": "y", "decides": "svc:nope"})
