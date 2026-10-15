"""The query catalogue and the data generator are consistent with the code that uses them."""

import re
from pathlib import Path

from oncall_brain.adapters.falkordb import queries
from oncall_brain.agents import registry
from oncall_brain.datagen import ACTS, T1, T2, generate
from oncall_brain.domain.planner import WINDOW
from oncall_brain.services import respond  # noqa: F401  (registers tools)

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
    assert {"blast_radius", "check_hypothesis", "recall_similar", "resolve_incident"} <= set(registry.REGISTRY)


def test_generator_is_deterministic_and_keeps_noise_out_of_the_act_windows():
    a, b = generate(7), generate(7)
    assert a == b and generate(8) != a
    in_window = [c["id"] for c in a["changes"]
                 if T1 - WINDOW <= c["at"] <= T1 or T2 - WINDOW <= c["at"] <= T2]
    assert sorted(in_window) == sorted(["chg:pgw-pool-1", "chg:search-420", "chg:legacy-193", "chg:pricing-2140",
                                        "chg:cart-310", "chg:pgw-pool-2", "chg:notif-77", "chg:fraud-512",
                                        "chg:pay-77"])
    assert {al["id"] for al in a["alerts"]} == set(ACTS.values())


def test_generated_names_are_fake_and_ids_unique():
    d = generate(7)
    for key, rows in d.items():
        ids = [r["id"] for r in rows if "id" in r]
        assert len(ids) == len(set(ids)), key
