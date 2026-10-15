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


def leading(supported: list[dict]) -> tuple[dict, list[tuple[dict, str]]]:
    """Several suspects are supported: keep the one that explains the most correlated alerts, then a memory
    suggestion, then the one nearest the alert, then the newest. Returns (leader, [(other, why it lost)])."""
    def key(h: dict) -> tuple:
        return (-(h.get("coverage") or 1), h["source"] != "memory", h["hops"] if h["hops"] is not None else 99,
                -h["at"])

    ranked = sorted(supported, key=key)
    lead, lc = ranked[0], ranked[0].get("coverage") or 1
    out = []
    for h in ranked[1:]:
        hc = h.get("coverage") or 1
        if hc < lc:
            why = f"{lead['change_id']} explains {lc} of the correlated alerts, this change {hc}"
        elif (h["source"] != "memory") and lead["source"] == "memory":
            why = f"memory (a runbook that worked before) points at {lead['change_id']}"
        elif (h["hops"] or 0) > (lead["hops"] or 0):
            why = f"{lead['change_id']} is nearer the alerting service ({lead['hops']} vs {h['hops']} hops)"
        else:
            why = f"{lead['change_id']} is the more recent of two equally supported changes"
        out.append((h, "outranked: " + why))
    return lead, out
