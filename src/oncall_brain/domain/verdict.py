"""How a hypothesis check turns graph facts into a verdict, and how several surviving suspects are ranked.
Pure, so every rule is unit-tested."""

from dataclasses import dataclass, field

INF = float("inf")
CASCADE_WINDOW = 15 * 60  # an upstream failure reaches its callers within minutes; a stale blip is not a cascade


@dataclass(frozen=True)
class CheckFacts:
    """Everything check_hypothesis read from the graph about one suspect change."""

    change_service: str
    alert_service: str
    rolled_back_before_alert: bool
    live_path: list[str]  # alert service -> ... -> changed service, using DEPENDS_ON edges valid at alert time
    any_path: list[str]  # same, ignoring edge validity (to tell "retired dependency" from "never connected")
    anomalous: set[str]  # services on/near the path with an anomaly between the change and the alert
    not_yet_live: bool = False  # the any_path dependency only started after the alert (not retired)


@dataclass(frozen=True)
class Verdict:
    verdict: str  # "supports" | "refutes"
    reason: str  # the full explanation (trace, UI)
    tag: str  # a few words for status updates
    gaps: tuple[str, ...] = field(default=())  # path services with no anomaly on record (monitoring gap?)


def _n(service_id: str) -> str:
    return service_id.removeprefix("svc:")


def judge(f: CheckFacts) -> Verdict:
    if f.rolled_back_before_alert:
        return Verdict("refutes", "change was rolled back before the alert fired", "rolled back")
    if not f.live_path:
        if f.any_path and f.not_yet_live:
            return Verdict("refutes", f"{_n(f.alert_service)} only started depending on {_n(f.change_service)} "
                                      "after the alert", "dependency not yet live")
        if f.any_path:
            return Verdict("refutes", f"{_n(f.alert_service)} no longer depends on {_n(f.change_service)} "
                                      "(dependency retired before the alert)", "dependency retired")
        return Verdict("refutes", f"no dependency path from {_n(f.alert_service)} to {_n(f.change_service)}",
                       "no dependency path")
    if f.change_service not in f.anomalous:
        return Verdict("refutes", f"{_n(f.change_service)} showed no anomaly after the change", "no anomaly after it")
    chain = " -> ".join(_n(s) for s in reversed(f.live_path))
    # The symptom should travel the dependency path from the changed service to the alerting service. A silent hop
    # in between is more often missing telemetry than a different cause, so it weakens the support instead of
    # discarding the suspect; a suspect with a complete chain still ranks ahead of it.
    silent = tuple(s for s in f.live_path[1:-1] if s not in f.anomalous)
    if silent:
        return Verdict("supports", f"anomaly on {_n(f.change_service)} reached {_n(f.alert_service)} via {chain}, "
                                   f"but nothing was recorded on {', '.join(map(_n, silent))} (monitoring gap?)",
                       "supported, with a monitoring gap", silent)
    return Verdict("supports", "anomaly propagates " + chain, "supported")


def leading(supported: list[dict], depends_on: set[tuple[str, str]] = frozenset()
            ) -> tuple[dict, list[tuple[dict, str]], list[tuple[dict, str]]]:
    """Several suspects survived their checks; keep one leading cause.

    Order: explains the most alerting services, then fewest monitoring gaps, then a memory suggestion, then nearest
    the alert, then first followed by an anomaly, then newest, then id. One causal rule overrides that order: if a
    suspect's service is upstream of the leader's (depends_on holds (leader service, its service)) and was already
    red when the leader's change landed, and the leader's service was itself already red before its change (or
    turned red within CASCADE_WINDOW of the upstream), the leader's anomaly is most likely propagation, so the
    upstream suspect leads (a cascade victim that happened to deploy mid-incident is not the cause; a stale blip
    upstream an hour earlier is not a cascade). The upstream needs no more monitoring gaps than the leader.
    Another suspect is outranked only if the leader explains every alerting service it explains; if it explains a
    service the leader cannot, it is a co-cause, not ruled out. Returns (leader, [(outranked, why)], [(co, why)])."""

    def cov(h: dict) -> set:
        return set(h.get("explained") or [])

    def onset(h: dict) -> float:
        return h.get("onset") or INF

    def upstream_first(up: dict, down: dict) -> bool:
        # A cascade: down's service depends on up's, and up's service was already red when down's change landed.
        # Evidence that down's own anomaly is propagation, not its change: down's service was already red before
        # its change (after up went red), or turned red within CASCADE_WINDOW of up. A single stale blip upstream
        # an hour earlier is neither. Up's own chain must be no weaker (coverage, monitoring gaps).
        if (down["service"], up["service"]) not in depends_on or not onset(up) < down["at"]:
            return False
        victim = (down.get("red_before") or -INF) >= onset(up)
        fast = onset(down) - onset(up) <= CASCADE_WINDOW
        return ((victim or fast) and cov(up) >= cov(down)
                and len(up.get("gaps") or []) <= len(down.get("gaps") or []))

    def key(h: dict) -> tuple:
        return (-len(cov(h)), len(h.get("gaps") or []), h["source"] != "memory",
                h["hops"] if h["hops"] is not None else 99, onset(h), -h["at"], h["change_id"])

    ranked = sorted(supported, key=key)
    lead = ranked[0]
    while (up := next((h for h in ranked if h is not lead and upstream_first(h, lead)), None)) is not None:
        lead = up
    lc = cov(lead)
    outranked, co = [], []
    for h in ranked:
        if h is lead:
            continue
        hc = cov(h)
        if hc - lc:
            co.append((h, "also needed: it alone explains " + ", ".join(sorted(_n(s) for s in hc - lc))))
            continue
        if upstream_first(lead, h):
            why = (f"{_n(h['service'])} depends on {_n(lead['service'])}, which was already red when this change "
                   f"landed: its anomaly came from upstream ({lead['change_id']})")
        elif len(hc) < len(lc):
            why = (f"{lead['change_id']} explains every alerting service this change does ({len(hc)}) and "
                   f"{len(lc) - len(hc)} more")
        elif len(h.get("gaps") or []) > len(lead.get("gaps") or []):
            why = f"{lead['change_id']} has a complete anomaly chain; this one has a monitoring gap"
        elif h["source"] != "memory" and lead["source"] == "memory":
            why = f"memory (a runbook that worked before) points at {lead['change_id']}"
        elif (h["hops"] or 0) > (lead["hops"] or 0):
            why = f"{lead['change_id']} is nearer the alerting service ({lead['hops']} vs {h['hops']} hops)"
        elif onset(lead) < onset(h):
            why = f"an anomaly followed {lead['change_id']} earlier than it followed this change"
        elif lead["at"] != h["at"]:
            why = f"{lead['change_id']} is the more recent of two equally supported changes"
        else:
            why = f"tied with {lead['change_id']} on every measure; picked by id"
        outranked.append((h, "outranked: " + why))
    return lead, outranked, co
