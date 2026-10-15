"""The confidence label an on-call engineer sees, from the facts the outcome carries."""

import pytest

from oncall_brain.domain.verdict import confidence

CAUSE = {"change": "chg:pgw-pool-1", "service": "svc:payments-gw", "status": "supported", "gaps": [],
         "explained": ["svc:checkout"]}


def test_no_cause_asks_for_a_human():
    c = confidence(None)
    assert c["level"] == "none" and "human" in c["why"]


def test_confirmed_beats_everything():
    assert confidence({**CAUSE, "status": "confirmed", "gaps": ["svc:payments"]})["level"] == "confirmed"


def test_complete_chain_is_very_likely_and_names_every_alert_in_a_storm():
    assert confidence(CAUSE)["level"] == "high"
    storm = confidence({**CAUSE, "explained": ["svc:a", "svc:b", "svc:c"]}, alerting=3)
    assert storm["level"] == "high" and "all 3 alerting services" in storm["why"]


@pytest.mark.parametrize("cause, alerting, co, expect", [
    ({**CAUSE, "gaps": ["svc:payments"]}, 1, 0, "nothing was recorded on payments"),
    ({**CAUSE, "explained": ["svc:a"]}, 3, 0, "explains 1 of 3 alerting services"),
    (CAUSE, 1, 2, "2 other changes also needed"),
])
def test_doubts_make_it_likely_with_the_reason(cause, alerting, co, expect):
    c = confidence(cause, alerting, co)
    assert c["level"] == "medium" and expect in c["why"]
