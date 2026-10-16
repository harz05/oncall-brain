"""Initiatives: the work behind the story's changes. An Initiative has a goal and a due date, a team DRIVES it, a
person LEADS it, tickets are PART_OF it and docs MENTION it, so "what is the Q4 cost review changing and who is on
it" is a graph walk, and the status update names the project behind the cause."""

from datetime import UTC, datetime

from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.agents.registry import ToolContext, call
from oncall_brain.datagen import ACTS, DAY, T1, T3, generate
from oncall_brain.services.respond import respond
from oncall_brain.services.seeding import seed

DATA = generate(7)
NAMES = {p["id"]: p["name"] for p in DATA["people"]}
INITIATIVES = {i["id"]: i for i in DATA["initiatives"]}
TICKETS = {t["id"]: t for t in DATA["tickets"]}
SANA = NAMES[TICKETS["ticket:CR-881"]["author"]]  # filed CR-881 and made chg:pgw-pool-1


def _day(at: int) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d")


def test_ask_walks_an_initiative_to_its_tickets_changes_people_and_decisions(store, tenant):
    seed(store, tenant)
    ctx = ToolContext(store.tenant(tenant))
    lead = NAMES[INITIATIVES["init:q4-cost-review"]["lead"]]
    out = call("ask", ctx, {"question": "what is the Q4 cost review changing"})
    d = out.data
    assert d["intent"] == "project" and [e["id"] for e in d["linked"]] == ["init:q4-cost-review"]
    assert d["answer"].startswith(f"'Q4 cost review' is active, driven by Payments, led by {lead}, due "
                                  f"{_day(T1 + 77 * DAY)}: Cut the infrastructure bill by 15%")
    work = d["answer"].split("Work: ")[1].split(" On it: ")[0]
    assert work == ("PAY-412 Remove checkout calls to legacy-billing (no change recorded); CR-881 Reduce idle "
                    f"connections on payments-gw -> chg:pgw-pool-1 (config on payments-gw by {SANA}).")
    filed = NAMES[TICKETS["ticket:PAY-412"]["author"]]
    assert f"On it: {lead} (lead), {filed} (filed PAY-412), {SANA} (filed CR-881, made pgw-pool-1)." in d["answer"]
    assert "Decisions: 'ADR-012: Retire legacy-billing from the checkout path' (decision record, by " in d["answer"]
    assert f"'Q4 cost review: payments gateway idle connections' (design note, by {SANA}, 2026-10-06)." in d["answer"]
    assert {"ticket:CR-881", "ticket:PAY-412", "doc:adr-012", "doc:cost-review-pgw"} <= set(d["sources"])
    assert {("ticket:CR-881", "init:q4-cost-review", "PART_OF"), ("ticket:CR-881", "chg:pgw-pool-1", "REQUESTED"),
            ("team:payments", "init:q4-cost-review", "DRIVES"), ("doc:adr-012", "init:q4-cost-review", "MENTIONS"),
            } <= set(out.highlight.edges)
    # "who is on" leads with the people; the service inside an initiative's name does not get linked instead.
    m = call("ask", ctx, {"question": "who is on the Q4 cost review"}).data
    assert m["intent"] == "members" and m["answer"].index("On it: ") < m["answer"].index("Work: ")
    p = call("ask", ctx, {"question": "who is on the postgres-orders capacity plan"}).data
    assert [e["id"] for e in p["linked"]] == ["init:pg-capacity"]
    assert "PLAT-233 Put PgBouncer in front of postgres-orders (no change recorded); CR-917 Lower postgres-orders " \
           "max_connections -> chg:pg-conn-3 (config on postgres-orders by " in p["answer"]
    # No rule matched: a linked initiative is still answered from the graph. A follow-up can say "it".
    t = call("ask", ctx, {"question": "tell me about the Q4 cost review"}).data
    assert t["intent"] == "project" and t["answer"].startswith("'Q4 cost review' is active")
    who = {"user": "person:hana-costa", "session": "t"}
    call("ask", ctx, {"question": "what is the Q4 cost review changing", **who})
    f = call("ask", ctx, {"question": "and who is on it?", **who}).data
    assert f["resolved"]["as"] == ["init:q4-cost-review"] and f["intent"] == "members"
    assert f["answer"].startswith('Taking "it" as Q4 cost review, from your earlier question "what is the Q4 cost '
                                  "review changing\". 'Q4 cost review' is active")


def test_the_status_update_names_the_initiative_behind_the_cause(store, tenant):
    seed(store, tenant)
    repo = store.tenant(tenant)
    ctx = ToolContext(repo)
    lead = NAMES[INITIATIVES["init:q4-cost-review"]["lead"]]
    run = respond(repo, ACTS[1], MockProvider())
    assert (f"Behind it: CR-881 is part of 'Q4 cost review' (Payments, led by {lead}, due {_day(T1 + 77 * DAY)})"
            in run["outcome"]["update_text"])
    cited = repo._graph.ro_query("MATCH (:Incident {id: $i})-[:HAS_UPDATE]->(:Message)-[:CITES]->(n:Initiative) "
                                 "RETURN collect(n.id)", {"i": run["incident_id"]}).result_set[0][0]
    assert cited == ["init:q4-cost-review"]
    # The initiative's story shows the incident its change is blamed for; "caused" once a human confirms it.
    d = call("ask", ctx, {"question": "what is the Q4 cost review changing"}).data
    assert f"chg:pgw-pool-1 (config on payments-gw by {SANA}), blamed for {run['incident_id']}" in d["answer"]
    call("resolve_incident", ctx, {"incident_id": run["incident_id"], "change_id": "chg:pgw-pool-1"})
    out = call("ask", ctx, {"question": "what is the Q4 cost review changing"})
    assert f"chg:pgw-pool-1 (config on payments-gw by {SANA}), caused {run['incident_id']}" in out.data["answer"]
    assert (run["incident_id"], "chg:pgw-pool-1", "CAUSED_BY") in out.highlight.edges
    # Act 3's cause traces to a different initiative.
    o3 = respond(repo, ACTS[3], MockProvider())["outcome"]
    lead3 = NAMES[INITIATIVES["init:pg-capacity"]["lead"]]
    assert (f"Behind it: CR-917 is part of 'postgres-orders capacity plan' (Platform, led by {lead3}, due "
            f"{_day(T3 + 30 * DAY)})" in o3["update_text"])
