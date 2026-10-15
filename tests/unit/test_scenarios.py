"""The eval's generator plants what it claims to plant (checked independently of its own BFS helpers)."""

from oncall_brain.domain.planner import WINDOW
from oncall_brain.scenarios import anomaly_pick, keyword_pick, scenario

SEEDS = range(1, 81)  # enough seeds that every perturbation occurs


def _live(d, at):
    return {(e["src"], e["dst"]) for e in d["depends_on"] if e["valid_from"] <= at and (e["valid_to"] or at + 1) > at}


def _closure(edges, origin):
    seen = {origin}
    while grown := {b for a, b in edges if a in seen} - seen:
        seen |= grown
    return seen


def _in_window(d, svc, since):
    """Times of anomalies on svc between since and the alert (the window check_hypothesis reads)."""
    at = d["alerts"][0]["at"]
    return [x["at"] for x in d["anomalies"] if x["service"] == svc and since <= x["at"] <= at]


def _change(d, cid):
    return next(c for c in d["changes"] if c["id"] == cid)


def test_deterministic_per_seed_with_unique_ids():
    assert scenario(3) == scenario(3) and scenario(3) != scenario(4)
    tags = [sorted(scenario(s)["perturbations"]) for s in SEEDS]
    assert tags == [sorted(scenario(s)["perturbations"]) for s in SEEDS]
    assert {t for ts in tags for t in ts} == {"gap", "innocent", "noise", "noise-on-c"} and [] in tags
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
        assert set(path) - set(sc["perturbations"].get("gap", [])) <= hit, seed


def test_gap_silences_exactly_one_intermediate_hop():
    for seed in SEEDS:
        sc = scenario(seed)
        if gap := sc["perturbations"].get("gap"):
            d, path = sc["data"], sc["truth_path"]
            assert len(gap) == 1 and gap[0] in path[1:-1], seed
            assert not _in_window(d, gap[0], _change(d, sc["truth_change"])["at"]), seed


def test_innocent_change_lands_downstream_on_the_truth_path_after_the_cause_went_red():
    for seed in SEEDS:
        sc = scenario(seed)
        if not (inn := sc["perturbations"].get("innocent")):
            continue
        d, path = sc["data"], sc["truth_path"]
        truth, c = _change(d, sc["truth_change"]), _change(d, inn[0])
        onset = min(_in_window(d, truth["service"], truth["at"]))
        assert c["service"] in path[:-1] and c["service"] not in sc["perturbations"].get("gap", []), seed
        assert onset < c["at"] and not c["rolled_back_at"], seed
        assert _in_window(d, c["service"], c["at"] + 1), seed  # its own service goes red after it


def test_noise_is_off_the_truth_path_and_noise_on_c_makes_c_look_red():
    for seed in SEEDS:
        sc = scenario(seed)
        d, alert = sc["data"], sc["data"]["alerts"][0]
        closure = _closure(_live(d, alert["at"]), alert["service"])
        noise = [x for x in d["anomalies"] if x["id"] in sc["perturbations"].get("noise", [])]
        assert len(noise) == len(sc["perturbations"].get("noise", [])) <= 3
        assert all(alert["at"] - WINDOW <= x["at"] < alert["at"] for x in noise), seed
        assert all(x["service"] in closure - set(sc["truth_path"]) for x in noise), seed
        if "c" in sc["decoys"]:
            c = _change(d, sc["decoys"]["c"])
            assert bool(_in_window(d, c["service"], c["at"])) == ("noise-on-c" in sc["perturbations"]), seed


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


def test_anomaly_baseline_blames_the_service_that_went_red_first_from_plain_rows():
    # Plain dicts, no store: the baseline never touches the graph.
    alert = {"at": 10_000}
    ch = [{"id": "cause", "service": "s1", "at": 9_000, "rolled_back_at": None},
          {"id": "newest", "service": "s2", "at": 9_900, "rolled_back_at": None},
          {"id": "rolled", "service": "s3", "at": 8_000, "rolled_back_at": 8_500},
          {"id": "quiet", "service": "s4", "at": 8_000, "rolled_back_at": None}]
    an = [{"service": "s1", "at": 9_100}, {"service": "s2", "at": 9_950}, {"service": "s3", "at": 8_100},
          {"service": "s4", "at": 7_000}]
    assert anomaly_pick(ch, an, alert)["id"] == "cause"
    assert anomaly_pick(ch[1:], an, alert)["id"] == "newest"
    assert anomaly_pick(ch[2:], an, alert) is None


def test_anomaly_baseline_is_deterministic_and_only_the_retired_edge_or_a_red_c_fools_it():
    for seed in SEEDS:
        sc, again = scenario(seed), scenario(seed)["data"]
        d = sc["data"]
        pick = anomaly_pick(d["changes"], d["anomalies"], d["alerts"][0])
        assert pick == anomaly_pick(again["changes"], again["anomalies"], again["alerts"][0])
        assert pick["id"] in {sc["truth_change"], sc["decoys"].get("d"), *sc["perturbations"].get("noise-on-c", [])}
