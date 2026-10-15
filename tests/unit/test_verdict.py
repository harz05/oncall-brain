from oncall_brain.domain.verdict import CheckFacts, judge, leading

PATH = ["svc:checkout", "svc:payments", "svc:payments-gw"]


def facts(**kw):
    base = dict(change_service="svc:payments-gw", alert_service="svc:checkout", rolled_back_before_alert=False,
                live_path=PATH, any_path=[], anomalous=set(PATH))
    return CheckFacts(**{**base, **kw})


def test_supported_when_anomaly_propagates_along_live_path():
    v = judge(facts())
    assert v.verdict == "supports" and "payments-gw -> payments -> checkout" in v.reason


def test_rollback_beats_everything():
    assert judge(facts(rolled_back_before_alert=True)).verdict == "refutes"


def test_retired_dependency_vs_no_dependency():
    assert "retired" in judge(facts(live_path=[], any_path=PATH)).reason
    assert "no dependency path" in judge(facts(live_path=[], any_path=[])).reason


def test_healthy_suspect_is_refuted():
    v = judge(facts(anomalous={"svc:checkout", "svc:payments"}))
    assert v.verdict == "refutes" and "no anomaly" in v.reason


def test_gap_in_propagation_is_inconclusive():
    assert judge(facts(anomalous={"svc:checkout", "svc:payments-gw"})).verdict == "inconclusive"


def test_change_on_the_alerting_service_itself():
    assert judge(facts(change_service="svc:checkout", live_path=["svc:checkout"],
                       anomalous={"svc:checkout"})).verdict == "supports"


def h(cid, explained=("svc:a",), source="dependency-path", hops=1, at=0, onset=None, svc="svc:x"):
    return {"change_id": cid, "explained": list(explained), "source": source, "hops": hops, "at": at, "onset": onset,
            "service": svc}


def test_leading_cause_explains_the_most_then_memory_then_nearest_then_first_red():
    lead, lost, co = leading([h("subs", ["svc:s"], hops=0), h("pg", ["svc:s", "svc:c", "svc:r"], hops=2)])
    assert lead["change_id"] == "pg" and "2 more" in lost[0][1] and not co
    lead, lost, _ = leading([h("near", hops=0), h("mem", source="memory", hops=3)])
    assert lead["change_id"] == "mem" and "memory" in lost[0][1]
    lead, lost, _ = leading([h("far", hops=3), h("near", hops=1)])
    assert lead["change_id"] == "near" and "nearer" in lost[0][1]
    # epoch-like times: "early" landed at 10 and its service went red at 13; "late" landed at 20, red at 25
    lead, lost, _ = leading([h("late", at=20, onset=25), h("early", at=10, onset=13)])
    assert lead["change_id"] == "early" and "earlier" in lost[0][1]


def test_a_suspect_explaining_a_service_the_leader_cannot_is_a_co_cause():
    lead, lost, co = leading([h("cart", ["svc:cart", "svc:checkout"], hops=1),
                              h("pgw", ["svc:checkout", "svc:refunds"], hops=2)])
    assert lead["change_id"] == "cart" and not lost and co[0][0]["change_id"] == "pgw"
    assert "refunds" in co[0][1]


def test_exact_ties_are_broken_by_id_and_say_so():
    lead, lost, _ = leading([h("b"), h("a")])
    assert lead["change_id"] == "a" and "picked by id" in lost[0][1]
