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


def leading(supported: list[dict]) -> tuple[dict, list[tuple[dict, str]], list[tuple[dict, str]]]:
    """Several suspects survived their checks. Keep one leading cause: the one that explains the most alerting
    services, then a memory suggestion, then the one nearest the alert, then the one whose service went red first
    after it, then the newest, then by id. Another suspect is outranked only if the leader explains every alerting
    service it explains; if it explains a service the leader cannot, it is a co-cause, not ruled out.
    Returns (leader, [(outranked, why)], [(co_cause, why)])."""
    def cov(h: dict) -> set:
        return set(h.get("explained") or [])

    def key(h: dict) -> tuple:
        return (-len(cov(h)), h["source"] != "memory", h["hops"] if h["hops"] is not None else 99,
                h.get("onset") or float("inf"), -h["at"], h["change_id"])

    lead, *rest = sorted(supported, key=key)
    lc = cov(lead)
    outranked, co = [], []
    for h in rest:
        hc = cov(h)
        if hc - lc:
            co.append((h, "also needed: it alone explains " + ", ".join(sorted(_n(s) for s in hc - lc))))
            continue
        if len(hc) < len(lc):
            why = (f"{lead['change_id']} explains every alerting service this change does ({len(hc)}) and "
                   f"{len(lc) - len(hc)} more")
        elif h["source"] != "memory" and lead["source"] == "memory":
            why = f"memory (a runbook that worked before) points at {lead['change_id']}"
        elif (h["hops"] or 0) > (lead["hops"] or 0):
            why = f"{lead['change_id']} is nearer the alerting service ({lead['hops']} vs {h['hops']} hops)"
        elif (lead.get("onset") or float("inf")) < (h.get("onset") or float("inf")):
            why = f"an anomaly followed {lead['change_id']} earlier than it followed this change"
        elif lead["at"] != h["at"]:
            why = f"{lead['change_id']} is the more recent of two equally supported changes"
        else:
            why = f"tied with {lead['change_id']} on every measure; picked by id"
        outranked.append((h, "outranked: " + why))
    return lead, outranked, co
