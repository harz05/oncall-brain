"""How a hypothesis check turns graph facts into a verdict. Pure, so every rule is unit-tested."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckFacts:
    """Everything check_hypothesis read from the graph about one suspect change."""

    change_service: str
    alert_service: str
    rolled_back_before_alert: bool
    live_path: list[str]  # alert service -> ... -> changed service, using DEPENDS_ON edges valid at alert time
    any_path: list[str]  # same, ignoring edge validity (to tell "retired dependency" from "never connected")
    anomalous: set[str]  # services on/near the path with an anomaly between the change and the alert


@dataclass(frozen=True)
class Verdict:
    verdict: str  # "supports" | "refutes" | "inconclusive"
    reason: str


def _n(service_id: str) -> str:
    return service_id.removeprefix("svc:")


def judge(f: CheckFacts) -> Verdict:
    if f.rolled_back_before_alert:
        return Verdict("refutes", "change was rolled back before the alert fired")
    if not f.live_path:
        if f.any_path:
            return Verdict("refutes", f"{_n(f.alert_service)} no longer depends on {_n(f.change_service)} "
                                      "(dependency retired before the alert)")
        return Verdict("refutes", f"no dependency path from {_n(f.alert_service)} to {_n(f.change_service)}")
    if f.change_service not in f.anomalous:
        return Verdict("refutes", f"{_n(f.change_service)} showed no anomaly after the change")
    # The symptom must travel the dependency path from the changed service to the alerting service.
    silent = [s for s in f.live_path[1:-1] if s not in f.anomalous]
    if silent:
        return Verdict("inconclusive", f"anomaly did not propagate through {', '.join(map(_n, silent))}")
    return Verdict("supports", "anomaly propagates " + " -> ".join(_n(s) for s in reversed(f.live_path)))
