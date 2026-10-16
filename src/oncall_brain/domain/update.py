"""Templates for what agents write back: the status update and a learned runbook. Pure functions."""

from datetime import UTC, datetime
from typing import Any


def status_update(facts: dict[str, Any], refuted: list[dict[str, Any]], origin: str,
                  co_causes: list[dict[str, Any]] = (), cause_path: list[str] = ()) -> str:
    """IMPACTS edges written by triage have via = the alerting service (or none); edges written by comms
    have via = the culprit service, so those are 'also at risk' (unless they sit on the failure path itself)."""
    impacts = [i for i in facts["impacts"] if i.get("service")]
    direct = sorted({i["service"] for i in impacts if i.get("via") in (None, origin)})
    at_risk = sorted({i["service"] for i in impacts} - set(direct) - set(cause_path))
    status = ("resolved, cause confirmed" if facts.get("cause_status") == "confirmed"
              else "cause identified, fix pending" if facts.get("change")
              else "investigating, no change-related cause found yet")
    lines = [f"[{facts['alert']}] status: {status}", "Impact: " + ", ".join(_short(s) for s in direct)]
    if facts.get("change"):
        label = "Cause (confirmed)" if facts.get("cause_status") == "confirmed" else "Likely cause"
        by = f" by {facts['author']}" if facts.get("author") else ""
        kind = {"config": "config change", "deploy": "deploy"}.get(facts.get("change_kind"), "change")
        lines.append(f"{label}: {kind} on {_short(facts['cause_service'])}{by}: "
                     f"\"{facts['change_summary']}\"")
        if facts.get("cause_gaps"):
            lines.append("Note: no anomaly was recorded on " + ", ".join(map(_short, facts["cause_gaps"]))
                         + " although the failure passed through it; check its monitoring")
        if facts.get("initiative"):  # the project the change was made for: whose goal the fix may cost
            w = facts["initiative"]
            about = [w.get("team"), f"led by {w['lead']}" if w.get("lead") else None,
                     f"due {_date(w['due'])}" if w.get("due") else None]
            lines.append(f"Behind it: {w['ticket'].removeprefix('ticket:')} is part of '{w['name']}'"
                         + (f" ({', '.join(x for x in about if x)})" if any(about) else ""))
    if facts.get("context"):
        lines.append("Context: " + "; ".join(f"{d['title']} ({d['kind']})" for d in facts["context"]))
    for c in co_causes:
        lines.append(f"Also contributing: {c['change'].removeprefix('chg:')} on {_short(c['service'])} "
                     f"({c['reason'].removeprefix('also needed: ')})")
    ruled = [r for r in refuted if r.get("verdict") != "outranked"]
    outranked = [r for r in refuted if r.get("verdict") == "outranked"]
    if ruled:
        lines.append("Ruled out: " + ", ".join(f"{r['change'].removeprefix('chg:')} ({r.get('tag') or 'ruled out'})"
                                               for r in ruled))
    if outranked:
        lines.append("Supported but outranked: " + ", ".join(
            f"{r['change'].removeprefix('chg:')} ({r['reason'].removeprefix('outranked: ')})" for r in outranked))
    paged = [p for p in facts["paged"] if p.get("handle")]
    if paged:
        lines.append("Paged: " + ", ".join(f"{p['handle']} ({p['team']})" for p in paged))
    warned = sorted((w for w in facts.get("warned", []) if w.get("handle")), key=lambda w: w.get("rank") or 0)
    if warned:
        lines.append("Heads-up (most relied-on first): " + ", ".join(
            f"{w['handle']} ({w['team']}) for {_short(w['service'])}" for w in warned))
    if at_risk:
        lines.append("Also at risk: " + ", ".join(_short(s) for s in at_risk))
    experts = [x for x in facts.get("experts", []) if x.get("id")]
    if experts:
        x = experts[0]
        lines.append(f"Ask: {x['name']} ({x['handle']}, {x['team']}) knows {_short(x['service'])} best")
    rbs = [r for r in facts["runbooks"] if r.get("id")]
    if rbs:
        r = rbs[0]
        lines.append(f"Next action: {r['steps'][0]} (this runbook worked {r['successes']} of {r['uses']} times)")
    srcs = [s for s in facts["sources"] if s]
    if srcs:
        lines.append("Sources: " + ", ".join(srcs))
    return "\n".join(lines)


def learned_runbook(service_name: str, kind: str, summary: str, alert_service: str) -> tuple[str, str, list[str]]:
    """(id, title, steps) of the runbook remembered from a confirmed fix."""
    verb = "Revert the config change" if kind == "config" else "Roll back the deploy"
    return (f"rb:{service_name}:{kind}", f"{verb} on {service_name}",
            [f"{verb} on {service_name}",
             f"Watch {_short(alert_service)} p99 recover within 10 minutes",
             f"Last time the culprit was: {summary}",
             f"Add a guard: alert on {service_name} saturation before callers time out"])


def _date(at: int) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d")


def _short(service_id: str | None) -> str:
    return (service_id or "?").removeprefix("svc:")
