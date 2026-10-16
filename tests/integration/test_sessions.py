"""Conversation memory: questions live in the graph per engineer and per session, a follow-up's "it" is read from
the previous question, "what did I ask about X" is a graph query, sessions are isolated per user, and concurrent
questions in one session get consecutive numbers."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from oncall_brain.agents.registry import ToolContext, call
from oncall_brain.datagen import generate
from oncall_brain.services import respond  # noqa: F401  (registers the tools)
from oncall_brain.services.seeding import reset, seed

pytestmark = pytest.mark.integration


def _rows(repo, cypher: str, **params):
    return repo._graph.ro_query(cypher, params).result_set


def test_a_follow_up_says_it_and_what_did_i_ask_is_answered_from_the_graph(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    user = generate(7)["people"][0]["id"]
    sid = f"session:{user.removeprefix('person:')}:default"
    d1 = call("ask", ctx, {"question": "who owns payments-gw", "user": user}).data
    assert d1["intent"] == "owner" and d1["resolved"] is None
    assert d1["recorded"] == {"session": sid, "question": sid + "#1", "seq": 1}
    out = call("ask", ctx, {"question": "and who knows it?", "user": user})
    d2 = out.data
    assert d2["resolved"] == {"pronoun": "it", "as": ["svc:payments-gw"],
                              "from": {"question": sid + "#1", "seq": 1, "text": "who owns payments-gw"}}
    assert d2["intent"] == "expert" and d2["answer"].startswith(
        'Taking "it" as payments-gw, from your earlier question "who owns payments-gw". People who know payments-gw:')
    assert d2["linked"] == [{"id": "svc:payments-gw", "kind": "service", "name": "payments-gw",
                             "matched": "payments-gw", "carried": True}]
    names = [q.name for q in out.queries]
    assert names[:2] == ["session_context", "link_entities"] and names[-1] == "record_question"
    assert not out.queries[-1].readonly and all(q.readonly for q in out.queries[:-1])
    # In the graph: the person OPENED one session, its questions are ASKED in order, #2 FOLLOWS #1, #2 is ABOUT
    # payments-gw through the pronoun (carried), #1 was ANSWERED_WITH its sources in rank order.
    repo = store.tenant(tenant)
    assert _rows(repo, "MATCH (p:Person {id: $u})-[:OPENED]->(s:Session)-[:ASKED]->(q:Question) "
                       "RETURN s.id, q.seq, q.text, q.intent ORDER BY q.seq", u=user) == [
        [sid, 1, "who owns payments-gw", "owner"], [sid, 2, "and who knows it?", "expert"]]
    assert _rows(repo, "MATCH (a:Question {seq: 2})-[:FOLLOWS]->(b:Question) RETURN b.seq") == [[1]]
    assert _rows(repo, "MATCH (q:Question {seq: 2})-[a:ABOUT]->(x) RETURN x.id, a.matched, a.carried") == [
        ["svc:payments-gw", "payments-gw", True]]
    assert _rows(repo, "MATCH (q:Question {seq: 1})-[a:ANSWERED_WITH]->(d) RETURN d.id ORDER BY a.rank") == [
        [x] for x in d1["sources"]]
    assert _rows(repo, "MATCH (q:Question {seq: 2}) RETURN q.resolved") == [["and who knows payments-gw?"]]
    # "What did I ask about payments-gw" is a graph query over ABOUT, newest first; the recall is not recorded.
    d3 = call("ask", ctx, {"question": "what did I ask about payments-gw", "user": user}).data
    assert d3["intent"] == "history" and d3["recorded"] is None and [q["seq"] for q in d3["questions"]] == [2, 1]
    assert d3["answer"].startswith("You asked 2 questions about payments-gw, newest first: 'and who knows it?' "
                                   "(read as 'and who knows payments-gw?') (expert, ")
    assert d3["questions"][1]["sources"][0]["id"] == d1["sources"][0]
    # The same from the my_questions tool, through a fresh repository: the memory is in the graph, not a process.
    rows = call("my_questions", ToolContext(store.tenant(tenant)),
                {"user": user, "about": "payments-gw"}).data["questions"]
    assert [(r["seq"], r["text"]) for r in rows] == [(2, "and who knows it?"), (1, "who owns payments-gw")]
    assert rows[0]["about"] == [{"id": "svc:payments-gw", "kind": "service", "name": "payments-gw", "carried": True}]
    assert call("my_questions", ctx, {"user": user, "about": "kafka"}).data["questions"] == []
    # Without a user: no pronoun to resolve, nothing recorded, every query read-only.
    out = call("ask", ctx, {"question": "who owns it?"})
    assert out.data["resolved"] is None and out.data["recorded"] is None and all(q.readonly for q in out.queries)
    assert _rows(repo, "MATCH (q:Question) RETURN count(q)") == [[2]]
    assert call("ask", ctx, {"question": "what did I ask about kafka"}).data["answer"].startswith(
        "No conversation history: pass user")
    assert reset(store, tenant) == "restored"  # conversation memory is tenant memory: a reset clears it
    assert _rows(store.tenant(tenant), "MATCH (s:Session) RETURN count(s)") == [[0]]


def test_memory_is_per_user_and_per_session(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    call("ask", ctx, {"question": "who owns kafka", "user": "person:a"})
    assert call("ask", ctx, {"question": "is it tier 1?", "user": "person:b"}).data["resolved"] is None  # not a's
    assert call("ask", ctx, {"question": "is it tier 1?", "user": "person:a", "session": "other"}).data[
        "resolved"] is None  # another conversation of a's
    d = call("ask", ctx, {"question": "is it tier 1?", "user": "Person:A"}).data  # the user as written in the graph
    assert d["resolved"]["as"] == ["svc:kafka"] and d["recorded"]["session"] == "session:a:default"
    mine = call("my_questions", ctx, {"user": "person:a"}).data["questions"]
    assert sorted((q["key"], q["seq"], q["text"]) for q in mine) == [
        ("default", 1, "who owns kafka"), ("default", 2, "is it tier 1?"), ("other", 1, "is it tier 1?")]
    assert [q["text"] for q in call("my_questions", ctx, {"user": "person:a", "session": "other"}).data[
        "questions"]] == ["is it tier 1?"]
    assert [(q["seq"], q["text"]) for q in call("my_questions", ctx, {"user": "person:a", "about": "kafka"}).data[
        "questions"]] == [(2, "is it tier 1?"), (1, "who owns kafka")]
    assert [q["text"] for q in call("my_questions", ctx, {"user": "person:b"}).data["questions"]] == ["is it tier 1?"]
    assert call("my_questions", ctx, {"user": "person:nobody"}).data["questions"] == []
    repo = store.tenant(tenant)
    assert _rows(repo, "MATCH (s:Session) RETURN s.user, s.key, size([(s)-[:ASKED]->() | 1]) "
                       "ORDER BY s.user, s.key") == [["person:a", "default", 2], ["person:a", "other", 1],
                                                     ["person:b", "default", 1]]
    assert _rows(repo, "MATCH (:Person)-[:OPENED]->(s:Session) RETURN count(s)") == [[0]]  # not people: still works


def test_concurrent_questions_in_one_session_get_consecutive_numbers_and_one_chain(store, tenant):
    seed(store, tenant)

    def asker(i: int) -> None:
        ctx = ToolContext(store.tenant(tenant))
        for k in range(5):
            call("ask", ctx, {"question": f"who owns kafka (asker {i}, question {k})", "user": "person:load"})

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(asker, range(8)))
    repo = store.tenant(tenant)
    assert _rows(repo, "MATCH (:Session {user: 'person:load'})-[:ASKED]->(q:Question) RETURN q.seq "
                       "ORDER BY q.seq") == [[n] for n in range(1, 41)]
    assert _rows(repo, "MATCH (:Question)-[:FOLLOWS]->(:Question) RETURN count(*)") == [[39]]
    assert _rows(repo, "MATCH (q:Question) WHERE NOT (q)-[:FOLLOWS]->() RETURN q.seq") == [[1]]
