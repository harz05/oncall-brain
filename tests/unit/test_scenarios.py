"""The eval's generator plants what it claims to plant (checked independently of its own BFS helpers)."""

from oncall_brain.domain.planner import WINDOW
from oncall_brain.scenarios import keyword_pick, scenario

SEEDS = range(1, 31)


def _live(d, at):
    return {(e["src"], e["dst"]) for e in d["depends_on"] if e["valid_from"] <= at and (e["valid_to"] or at + 1) > at}


def _closure(edges, origin):
    seen = {origin}
    while grown := {b for a, b in edges if a in seen} - seen:
        seen |= grown
    return seen


def test_deterministic_per_seed_with_unique_ids():
    assert scenario(3) == scenario(3) and scenario(3) != scenario(4)
    for key, rows in scenario(3)["data"].items():
        ids = [r["id"] for r in rows if "id" in r]
        assert len(ids) == len(set(ids)), key


def test_truth_is_in_the_window_on_a_live_path_the_anomaly_travels():
    for seed in SEEDS:
        sc = scenario(seed)
        d = sc["data"]
        alert = next(a for a in d["alerts"] if a["id"] == sc["alert_id"])
        c = next(c for c in d["changes"] if c["id"] == sc["truth_change"])
        path = sc["truth_path"]
        assert alert["at"] - WINDOW <= c["at"] <= alert["at"] and not c["rolled_back_at"]
        assert path[0] == alert["service"] and path[-1] == c["service"] and len(path) <= 4
        assert set(zip(path, path[1:], strict=False)) <= _live(d, alert["at"])
        hit = {x["service"] for x in d["anomalies"] if c["at"] <= x["at"] <= alert["at"]}
        assert set(path) <= hit, seed


def test_flat_baseline_decoy_is_the_newest_in_window_change_and_off_path():
    for seed in SEEDS:
        sc = scenario(seed)
        d = sc["data"]
        alert = d["alerts"][0]
        window = [c for c in d["changes"] if alert["at"] - WINDOW <= c["at"] <= alert["at"]]
        newest = max(window, key=lambda c: c["at"])
        assert newest["id"] == sc["baseline_change"] != sc["truth_change"]
        assert sum(c["at"] == newest["at"] for c in window) == 1
        assert newest["service"] not in _closure(_live(d, alert["at"]), alert["service"])


def test_keyword_baseline_prefers_word_overlap_then_recency():
    alert = {"at": 10_000, "name": "checkout p99 latency above 2s"}
    changes = [{"id": "old-match", "at": 9_000, "summary": "Deploy checkout v1 (latency fix)"},
               {"id": "new", "at": 9_900, "summary": "Deploy search v2"},
               {"id": "outside", "at": 1, "summary": "checkout latency p99 above"}]
    assert keyword_pick(changes, alert)["id"] == "old-match"
    assert keyword_pick(changes[1:], alert)["id"] == "new"
