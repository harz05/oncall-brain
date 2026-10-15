from oncall_brain.domain.verdict import CheckFacts, judge

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


def test_storm_suspect_that_cannot_reach_every_alerting_service_is_refuted():
    v = judge(facts(storm_unexplained=("svc:refunds", "svc:checkout")))
    assert v.verdict == "refutes" and "cannot explain the alerts on refunds, checkout" in v.reason
