"""Company brain: free-form questions over docs, tickets and chat, answered with graph context and sources."""

from oncall_brain.agents.registry import ToolContext, call
from oncall_brain.datagen import generate
from oncall_brain.scenarios import scenario
from oncall_brain.services import respond  # noqa: F401  (registers who_knows / change_story)
from oncall_brain.services.seeding import load, reset, seed


def _name(person_id: str) -> str:
    return next(p["name"] for p in generate(7)["people"] if p["id"] == person_id)


def _author(change_id: str) -> str:
    return next(c["author"] for c in generate(7)["changes"] if c["id"] == change_id)


def test_ask_traces_why_the_payments_gateway_pool_was_lowered(store, tenant):
    seed(store, tenant)
    out = call("ask", ToolContext(store.tenant(tenant)), {"question": "Why was the payments gateway pool lowered?"})
    d = out.data
    assert d["hits"][0]["id"] == "doc:cost-review-pgw" and d["sources"][0] == "doc:cost-review-pgw"
    assert {"ticket:CR-881", "doc:pm-load-test-pgw"} <= set(d["sources"])  # the request and the warning it ignored
    assert "chg:pgw-pool-1" in d["answer"] and _name(_author("chg:pgw-pool-1")) in d["answer"]
    assert "200 to 20" in d["answer"]  # the reason is quoted from the doc, not paraphrased
    rel = {r["id"]: r for r in d["related"]}
    assert rel["chg:pgw-pool-1"]["via"] == "doc:cost-review-pgw MENTIONS chg:pgw-pool-1"
    assert rel["svc:payments-gw"]["kind"] == "service" and rel["team:payments"]["kind"] == "team"
    assert {("doc:cost-review-pgw", "chg:pgw-pool-1", "MENTIONS"), ("chg:pgw-pool-1", "svc:payments-gw", "CHANGED"),
            ("team:payments", "svc:payments-gw", "OWNS")} <= set(out.highlight.edges)
    assert [q.name for q in out.queries] == ["search_knowledge", "knowledge_context"]
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
    d = call("ask", ctx, {"question": "why was legacy-billing retired from checkout"}).data
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
    assert rows and {r["label"] for r in rows} <= {"Service", "Person", "Doc", "Message", "Ticket"}
