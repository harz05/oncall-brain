"""Templates for what agents write back: the status update and a learned runbook. Pure functions."""

from typing import Any


def status_update(facts: dict[str, Any], refuted: list[dict[str, Any]], origin: str,
                  co_causes: list[dict[str, Any]] = ()) -> str:
    """IMPACTS edges written by triage have via = the alerting service (or none); edges written by comms
    have via = the culprit service, so those are 'also at risk'."""
    impacts = [i for i in facts["impacts"] if i.get("service")]
    direct = sorted({i["service"] for i in impacts if i.get("via") in (None, origin)})
    at_risk = sorted({i["service"] for i in impacts if i["service"] not in direct})
    status = ("resolved, cause confirmed" if facts.get("cause_status") == "confirmed"
              else "cause identified, fix pending" if facts.get("change")
              else "investigating, no change-related cause found yet")
    lines = [f"[{facts['alert']}] status: {status}"]
    lines.append("Impact: " + ", ".join(_short(s) for s in direct))
    if facts.get("change"):
        label = "Cause (confirmed)" if facts.get("cause_status") == "confirmed" else "Likely cause"
        by = f", by {facts['author']}" if facts.get("author") else ""
        lines.append(f"{label}: {facts['change_summary']} ({_short(facts['cause_service'])}{by}).")
    for c in co_causes:
        lines.append(f"Also contributing: {c['change'].removeprefix('chg:')} on {_short(c['service'])} "
                     f"({c['reason']})")
    if refuted:
        lines.append("Ruled out: " + "; ".join(
            f"{r['change'].removeprefix('chg:')} on {_short(r['service'])} ({r['reason']})" for r in refuted))
    paged = [p for p in facts["paged"] if p.get("handle")]
    if paged:
        lines.append("Paged: " + ", ".join(f"{p['handle']} ({p['team']})" for p in paged))
    if at_risk:
        lines.append("Also at risk: " + ", ".join(_short(s) for s in at_risk))
    experts = [x for x in facts.get("experts", []) if x.get("id")]
    if experts:
        x = experts[0]
        lines.append(f"Ask: {x['name']} ({x['handle']}, {x['team']}) knows {_short(x['service'])} best")
    rbs = [r for r in facts["runbooks"] if r.get("id")]
    if rbs:
        r = rbs[0]
        lines.append(f"Next action: {r['steps'][0]} (runbook '{r['title']}', worked {r['successes']} of "
                     f"{r['uses']} times)")
    srcs = [s for s in facts["sources"] if s]
    if srcs:
        lines.append("Sources: " + ", ".join(srcs))
    return "\n".join(lines)


def learned_runbook(service_name: str, kind: str, summary: str, alert_service: str) -> tuple[str, str, list[str]]:
    """(id, title, steps) of the runbook remembered from a confirmed fix."""
    verb = "Revert the config change" if kind == "config" else "Roll back the deploy"
    return (f"rb:{service_name}:{kind}", f"{verb} on {service_name}",
            [f"{verb} on {service_name} (last time: {summary})",
             f"Watch {_short(alert_service)} p99 recover within 10 minutes",
             f"Add a guard: alert on {service_name} saturation before callers time out"])


def _short(service_id: str | None) -> str:
    return (service_id or "?").removeprefix("svc:")
