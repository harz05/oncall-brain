"""Slack Block Kit messages for /oncall (api/slack_app.py): pure functions of what the services return, no I/O.

Every graph string goes through esc() (Slack's mrkdwn needs &, < and > escaped, or "<@U1>" and "<!here>" in a doc
would ping people), and every text is capped under Slack's limits (3000 characters per text, 2000 per field, 150
per header, 75 per button label, 50 blocks per message)."""

import json
import re
from typing import Any

from oncall_brain.domain import update

HELP = (
    ("/oncall <question>", "ask the company brain, e.g. `/oncall who owns kafka?` Only you see the answer."),
    ("/oncall share <question>", "the same, posted to the channel."),
    ("/oncall incident <service> <latency|errors|saturation>", "three agents work the incident and post the cause, "
     "who is paged and the fix here, with Confirm cause / Wrong cause buttons. Slow, p99 or timeouts mean latency; "
     "5xx, failing or down mean errors; cpu or memory mean saturation."),
    ("/oncall help", "this list."),
)
TEXT, FIELD, HEADER, LABEL, SOURCES = 3000, 2000, 150, 75, 5


def esc(s: Any) -> str:
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cap(s: str, n: int = TEXT) -> str:
    return s if len(s) <= n else s[:n - 3].rstrip() + "..."


def short(node_id: str | None) -> str:
    """svc:payments-gw -> payments-gw (what an engineer calls it)."""
    return (node_id or "").split(":", 1)[-1]


def mrkdwn(text: str, n: int = TEXT) -> dict[str, str]:
    return {"type": "mrkdwn", "text": cap(text, n)}


def section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": mrkdwn(text)}


def context(*texts: str) -> dict[str, Any]:
    return {"type": "context", "elements": [mrkdwn(t) for t in texts if t][:10]}


def say(text: str, response_type: str = "ephemeral") -> dict[str, Any]:
    """A plain message (help, errors, acks); `text` is ours, not the graph's, so it is not escaped."""
    return {"response_type": response_type, "text": cap(text)}


def help_message() -> dict[str, Any]:
    lines = "\n".join(f"`{cmd}`: {what}" for cmd, what in HELP)
    return {"response_type": "ephemeral", "text": "On-call Brain: /oncall help",
            "blocks": [section("*On-call Brain* answers from your company graph: services and who owns them, "
                               "on-call, changes, incidents, docs, tickets and chat.\n" + lines),
                       context("Follow-ups remember this channel's conversation: "
                               "`/oncall and who is on call for it?`")]}


def _sources(items: list[tuple[str, str | None]]) -> str:
    """'title (`id`)' for up to five sources, in the order the answer cites them."""
    shown = [f"{esc(title)} (`{esc(i)}`)" if title else f"`{esc(i)}`" for i, title in items[:SOURCES]]
    more = len(items) - SOURCES
    return ("Sources: " + " · ".join(shown) + (f" · and {more} more" if more > 0 else "")) if shown else ""


def _split(text: str) -> tuple[str, str]:
    """First sentence, rest (a sentence ends at . ! or ? before a space: 'v1.9.3' and 'inc:0911' stay whole, and so
    does a quoted excerpt: the end, after the excerpt's closing quote if any, must sit where the double quotes so far
    are balanced)."""
    text = text.strip()
    for m in re.finditer(r'(?:(?<=[.!?])|(?<=[.!?]"))\s+', text):
        if text[:m.start()].count('"') % 2 == 0:
            return text[:m.start()], text[m.end():]
    return text, ""


def ask_message(data: dict[str, Any], *, shared: bool) -> dict[str, Any]:
    """The ask tool's answer: the lead bold, the rest, then its sources. With the answer's parts (brain.ask), the
    first part is the lead and each further part gets its own line; else the lead is the first sentence. A follow-up's
    "Taking 'it' as kafka" sentence goes on its own line above, so the bold line is the answer."""
    if parts := data.get("parts"):
        note, lead, rest = data["answer"].removesuffix(" ".join(parts)).strip(), parts[0], "\n".join(parts[1:])
    else:
        note, (lead, rest) = "", _split(data["answer"])
        if data.get("resolved") and rest:
            note, (lead, rest) = lead, _split(rest)
    titles = {h["id"]: (f"chat in {h['title']}" if h["kind"] == "chat" else h["title"]) for h in data.get("hits", [])}
    blocks = ([context(f"_{esc(note)}_")] if note else []) + [section(f"*{esc(lead)}*" + (f"\n{esc(rest)}" if rest
                                                                                        else ""))]
    src = _sources([(s, titles.get(s)) for s in data.get("sources", [])])
    if src:
        blocks.append(context(src))
    return {"response_type": "in_channel" if shared else "ephemeral", "text": cap(esc(lead)), "blocks": blocks}


def value(tenant: str, incident: str, change: str | None = None) -> str:
    """A button's value: which tenant, incident and change the click is about (Slack echoes it back, signed)."""
    return json.dumps({"t": tenant, "i": incident, "c": change}, separators=(",", ":"))


def button(text: str, action_id: str, val: str, style: str | None = None) -> dict[str, Any]:
    b = {"type": "button", "text": {"type": "plain_text", "text": cap(text, LABEL)}, "action_id": action_id,
         "value": val}
    return b | ({"style": style} if style else {})


def alternatives(o: dict[str, Any]) -> list[dict[str, Any]]:
    """The other changes a human might name instead (what the web UI's Wrong cause lists): the suspects the agents
    ruled out or outranked, co-causes, and what the change log alone would blame. Distinct, without the leading
    cause."""
    seen = {(o.get("root_cause") or {}).get("change")}
    out = []
    for r in [*o.get("refuted", []), *o.get("co_causes", []), o.get("baseline_pick"), o.get("anomaly_baseline_pick")]:
        if r and r.get("change") and r["change"] not in seen:
            seen.add(r["change"])
            out.append({**r, "tag": r.get("tag") or "not on a dependency path the agents tested"})
    return out


def _ago(seconds: int) -> str:
    m = max(0, round(seconds / 60))
    return f"{m} min" if m < 120 else f"{m // 60} h {m % 60} min"


def _cause(head: dict[str, Any], o: dict[str, Any]) -> str:
    rc, conf = o.get("root_cause"), o["confidence"]
    if not rc:
        return f"*{esc(conf['label'])}:* {esc(conf['why'])}."
    label = "Cause confirmed" if head["status"] == "resolved" else "Likely cause"
    kind = {"deploy": "Deploy", None: "Change"}.get(rc.get("kind"), "Config change")
    by = f" by {esc(rc['author'])}" if rc.get("author") else ""
    when = f", {_ago(head['at'] - rc['at'])} before the alert" if rc.get("at") else ""
    return (f"*{label}:* {kind} on *{esc(short(rc['service']))}*{by}{when}\n>{esc(rc.get('summary'))}\n"
            f"`{esc(rc['change'])}` · *{esc(conf['label'])}*: {esc(conf['why'])}")


def _paged(o: dict[str, Any]) -> str:
    rows = [f"{esc(p['name'])} ({esc(p['handle'])}, {esc(p.get('team_name') or short(p.get('team')))})"
            + (f" for {esc(short(p['service']))}" if p.get("service") else "") for p in o.get("paged", [])]
    warned = [f"{esc(w['name'])} for {esc(short(w['service']))}" for w in o.get("warned", [])]
    return ("*Who is paged*\n" + ("\n".join(rows[:6]) if rows else "Nobody paged.")
            + (f"\nHeads-up: {', '.join(warned[:4])}" if warned else ""))


def _fix(head: dict[str, Any], runbook: dict[str, Any] | None, rc: dict[str, Any] | None = None) -> str:
    """Memory's runbook, else what the cause suggests (the runbook a confirmation would save), else nothing yet."""
    if not runbook:
        if not rc:
            return "*Fix*\nNone yet: no cause found, so a human should look first."
        title = update.learned_runbook(short(rc["service"]), rc.get("kind") or "deploy", "", head["service"])[1]
        return f"*Fix*\nSuggested: *{esc(title)}*. Confirm the cause and it is saved for next time."
    uses, ok = runbook.get("uses") or 0, runbook.get("successes") or 0
    record = f"worked {ok} of {uses} times" if uses > 1 else "confirmed once" if uses == 1 else "from memory"
    saved = "Saved to memory: " if head["status"] == "resolved" else ""
    steps = [esc(s) for s in runbook.get("steps") or [] if s != runbook["title"]][:2]
    return f"*Fix*\n{saved}*{esc(runbook['title'])}* ({record})" + "".join(f"\n• {s}" for s in steps)


def incident_message(tenant: str, head: dict[str, Any], o: dict[str, Any], *, runbook: dict[str, Any] | None = None,
                     note: str | None = None, choices: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An incident as the agents left it: the alert, the cause with its confidence, who is paged and the fix, up to
    five sources, then the buttons. `head` is the incident_head row, `o` the outcome (services/respond.py).
    `note` (ours, mrkdwn) says who did what. `choices` (after Wrong cause) lists the other suspects to pick from."""
    rc, open_, alert = o.get("root_cause"), head["status"] != "resolved", head.get("alert_name") or head["alert"]
    blocks: list[dict[str, Any]] = [{"type": "header", "text": {"type": "plain_text", "text": cap(alert, HEADER)}}]
    if note:
        blocks.append(section(note))
    blocks.append(section(_cause(head, o)))
    blocks.append({"type": "section", "fields": [mrkdwn(_paged(o), FIELD), mrkdwn(_fix(head, runbook, rc), FIELD)]})
    mem = o.get("memory") or {}
    if mem.get("solved_by_memory") and mem.get("recalled"):
        past = mem["recalled"][0]
        blocks.append(context(f"From memory: this looked like `{esc(past.get('incident'))}`, so its cause was "
                              "checked first."))
    blocks.append(context(_sources([(s["id"], f"chat in {s['title']}" if s.get("kind") == "Message" else s.get("title"))
                                    for s in o.get("sources", [])]),
                          f"`{esc(head['incident'])}` on {esc(tenant)}"))
    val = value(tenant, head["incident"], (rc or {}).get("change"))
    if open_ and choices is not None:
        if choices:
            blocks.append(section("\n".join(f"• `{esc(short(c['change']))}` on {esc(short(c['service']))}: "
                                            f"{esc(c.get('summary'))} _({esc(c['tag'])})_" for c in choices[:5])))
        picks = [button(f"This one: {short(c['change'])}", f"pick_{n}", value(tenant, head["incident"], c["change"]))
                 for n, c in enumerate(choices[:5])]
        keep = [button("Confirm the agents' cause", "confirm", val, "primary")] if rc else []
        if picks or keep:
            blocks.append({"type": "actions", "elements": picks + keep})  # Slack makes a fresh block_id each time
    elif open_ and (rc or alternatives(o)):
        elements = ([button("Confirm cause", "confirm", val, "primary"), button("Wrong cause", "wrong", val, "danger")]
                    if rc else [button("Pick the cause", "wrong", val)])
        blocks.append({"type": "actions", "elements": elements})
    fallback = f"{alert}: " + (
        f"{'confirmed' if not open_ else 'likely'} cause {short(rc['change'])} on {short(rc['service'])}" if rc
        else "no single cause yet")
    return {"text": cap(esc(fallback)), "blocks": blocks[:50]}
