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


def h(cid, coverage=1, source="dependency-path", hops=1, at=0):
    return {"change_id": cid, "coverage": coverage, "source": source, "hops": hops, "at": at}


def test_leading_cause_explains_the_most_alerts_then_memory_then_nearest():
    lead, lost = leading([h("subs", coverage=1, hops=0), h("pg", coverage=3, hops=2)])
    assert lead["change_id"] == "pg" and "explains 3" in lost[0][1]
    lead, lost = leading([h("near", hops=0), h("mem", source="memory", hops=3)])
    assert lead["change_id"] == "mem" and "memory" in lost[0][1]
    lead, lost = leading([h("far", hops=3), h("near", hops=1)])
    assert lead["change_id"] == "near" and "nearer" in lost[0][1]
