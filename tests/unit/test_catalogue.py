"""The query catalogue and the data generator are consistent with the code that uses them."""

import re
from pathlib import Path

from oncall_brain.adapters.falkordb import queries
from oncall_brain.agents import registry
from oncall_brain.datagen import ACTS, DAY, T1, T2, T3, generate
from oncall_brain.domain.planner import WINDOW
from oncall_brain.services import respond  # noqa: F401  (registers tools)
from oncall_brain.services.brain import coverage, snippet, terms

SRC = Path(__file__).parents[2] / "src"


def test_every_query_has_a_purpose_and_every_referenced_query_exists():
    qs = queries.all_queries()
    assert all(q.purpose for q in qs.values())
    used = set()
    for f in SRC.rglob("*.py"):
        used |= set(re.findall(r'\.(?:read|write)\(\s*"(\w+)"', f.read_text()))
    used |= {name for name, _ in __import__("oncall_brain.services.seeding", fromlist=["INGEST"]).INGEST}
    assert used - set(qs) == set(), "code references unknown queries"


def test_tools_have_descriptions_and_schemas():
    for spec in registry.specs():
        assert spec["description"] and spec["input_schema"]["type"] == "object"
    assert {"blast_radius", "check_hypothesis", "recall_similar", "resolve_incident", "ask"} <= set(registry.REGISTRY)
    assert registry.REGISTRY["ask"].agent and not registry.REGISTRY["ask"].writes


def test_generator_is_deterministic_and_keeps_noise_out_of_the_act_windows():
    a, b = generate(7), generate(7)
    assert a == b and generate(8) != a
    in_window = [c["id"] for c in a["changes"] if any(t - WINDOW <= c["at"] <= t for t in (T1, T2, T3))]
    assert sorted(in_window) == sorted(["chg:pgw-pool-1", "chg:search-420", "chg:legacy-193", "chg:pricing-2140",
                                        "chg:cart-310", "chg:pgw-pool-2", "chg:notif-77", "chg:fraud-512",
                                        "chg:pay-77", "chg:pg-conn-3", "chg:subs-88", "chg:search-430"])
    assert set(ACTS.values()) <= {al["id"] for al in a["alerts"]}


def test_generated_names_are_fake_and_ids_unique():
    d = generate(7)
    for key, rows in d.items():
        ids = [r["id"] for r in rows if "id" in r]
        assert len(ids) == len(set(ids)), key
    for seed in (7, 8, 11):  # one person per first name, so the UI never shows two "Chidi"s
        firsts = [p["name"].split()[0] for p in generate(seed)["people"]]
        assert len(firsts) == len(set(firsts)) == 24


def test_brain_corpus_is_linked_dated_outside_the_acts_and_plants_its_facts():
    d = generate(7)
    assert len(d["docs"]) >= 30 and len(d["messages"]) >= 40 and len(d["tickets"]) >= 20
    assert {x["kind"] for x in d["docs"]} == {"postmortem", "design", "decision", "runbook"}
    ids = {r["id"] for rows in d.values() for r in rows if "id" in r}
    for key in ("docs", "tickets", "messages"):
        for r in d[key]:
            assert set(r.get("mentions", [])) <= ids and r["author"] in ids, r["id"]
            # Only act 1's planted announcement sits in an act window; the corpus stays out of them.
            assert r["id"] == "msg:pay-deploys-1" or not any(t - WINDOW - 3600 <= r["at"] <= t + 3600
                                                             for t in (T1, T2, T3)), r["id"]
    assert {x["supersedes"] for x in d["docs"]} - {None} <= ids
    docs = {x["id"]: x for x in d["docs"]}
    pool = next(c for c in d["changes"] if c["id"] == "chg:pgw-pool-1")
    review = docs["doc:cost-review-pgw"]
    assert review["author"] == pool["author"] and "chg:pgw-pool-1" in review["mentions"] and review["at"] < pool["at"]
    retired = next(e for e in d["depends_on"] if e["valid_to"])  # checkout -> legacy-billing
    adr = docs["doc:adr-012"]
    assert adr["decides"] == retired["dst"] and 0 < retired["valid_to"] - adr["at"] < DAY
    assert docs["doc:design-retries-v2"]["supersedes"] == "doc:design-retries-v1"
    assert docs["doc:design-retries-v2"]["author"] != docs["doc:design-retries-v1"]["author"]
    assert "chg:pg-conn-3" in docs["doc:pg-conn-budget"]["mentions"]
    past = {i["id"] for i in d["incidents"]}
    assert past <= {m for x in d["docs"] if x["kind"] == "postmortem" for m in x["mentions"]}


def test_ask_terms_drop_stopwords_and_anything_the_index_would_parse():
    assert terms("Why was the payments-gw pool lowered?") == ["payments", "gw", "pool", "lowered"]
    assert terms("a the why WHO") == [] and terms("x | y* @title:(-z)") == ["title"]
    assert coverage(["lowered", "designed"], "We lower it; design note") == 2
    assert snippet(["pool"], "Intro. The pool is small. Why: cost. Later.") == "The pool is small. Why: cost."
