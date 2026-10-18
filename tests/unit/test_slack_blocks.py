"""Slack Block Kit formatting (adapters/slack_blocks.py): content, escaping of graph strings, Slack's limits."""

import json

from oncall_brain.adapters import slack_blocks as b

HEAD = {"incident": "inc:checkout-latency", "status": "open", "service": "svc:checkout",
        "alert": "alert:checkout-latency", "at": 1792036800, "alert_name": "checkout p99 latency above 2s"}
CAUSE = {"change": "chg:pgw-pool-1", "service": "svc:payments-gw", "kind": "config", "at": 1792036800 - 40 * 60,
         "author": "Sana Brandt", "summary": "Lower payments-gw HTTP pool max_connections 200 -> 20"}


def outcome(**kw):
    o = {"root_cause": CAUSE, "confidence": {"level": "high", "label": "Very likely", "why": "anomalies follow it"},
         "paged": [{"name": "Asha Nakamura", "handle": "@asha.nakamura", "team_name": "Payments",
                    "service": "svc:payments-gw"}],
         "warned": [{"name": "Hana Costa", "service": "svc:api-gateway"}],
         "sources": [{"id": f"doc:d{i}", "title": f"Doc {i}"} for i in range(7)],
         "refuted": [{"change": "chg:search-420", "service": "svc:search", "summary": "Deploy search",
                      "tag": "no dependency path"}],
         "co_causes": [], "baseline_pick": {"change": "chg:search-420", "service": "svc:search"},
         "anomaly_baseline_pick": {"change": "chg:legacy-193", "service": "svc:legacy-billing"},
         "memory": {"solved_by_memory": False, "recalled": []}}
    return {**o, **kw}


def texts(msg):
    """Every text in a message, with the limit Slack puts on it."""
    for blk in msg["blocks"]:
        if blk["type"] == "header":
            yield blk["text"]["text"], b.HEADER
        for t in [blk.get("text")] + blk.get("elements", []) + blk.get("fields", []):
            if t and t.get("type") == "mrkdwn":
                yield t["text"], b.FIELD if t in blk.get("fields", []) else b.TEXT
            if t and t.get("type") == "button":
                yield t["text"]["text"], b.LABEL


def actions(msg):
    return [e for blk in msg["blocks"] if blk["type"] == "actions" for e in blk["elements"]]


def test_escape_only_what_slack_needs():
    assert b.esc("<@U1> & <!here> *bold*") == "&lt;@U1&gt; &amp; &lt;!here&gt; *bold*"
    assert b.esc(None) == ""


def test_incident_message_has_cause_people_fix_sources_and_buttons():
    msg = b.incident_message("acme", HEAD, outcome())
    assert msg["blocks"][0] == {"type": "header", "text": {"type": "plain_text", "text": HEAD["alert_name"]}}
    cause = msg["blocks"][1]["text"]["text"]
    assert "*Likely cause:* Config change on *payments-gw* by Sana Brandt, 40 min before the alert" in cause
    assert "200 -&gt; 20" in cause and "*Very likely*: anomalies follow it" in cause
    paged, fix = (f["text"] for f in msg["blocks"][2]["fields"])
    assert "Asha Nakamura (@asha.nakamura, Payments) for payments-gw" in paged and "Heads-up: Hana Costa" in paged
    assert fix == ("*Fix*\nSuggested: *Revert the config change on payments-gw*. Confirm the cause and it is saved "
                   "for next time.")
    src = msg["blocks"][3]["elements"][0]["text"]
    assert src.count("(`doc:") == 5 and src.endswith("and 2 more")
    confirm, wrong = actions(msg)
    assert (confirm["action_id"], confirm["style"], wrong["action_id"]) == ("confirm", "primary", "wrong")
    assert json.loads(confirm["value"]) == {"t": "acme", "i": "inc:checkout-latency", "c": "chg:pgw-pool-1"}


def test_graph_strings_are_escaped_and_everything_fits_slacks_limits():
    evil = "<!channel> & <@U1> " + "x" * 5000
    o = outcome(root_cause={**CAUSE, "summary": evil, "author": evil},
                paged=[{"name": evil, "handle": evil, "team_name": evil, "service": "svc:a"}] * 30,
                sources=[{"id": "doc:x", "title": evil}] * 30,
                refuted=[{"change": f"chg:{'y' * 90}{i}", "service": "svc:s", "summary": evil, "tag": evil}
                         for i in range(10)])
    for msg in (b.incident_message("acme", {**HEAD, "alert_name": evil}, o, note="Marked wrong by <@U1>.",
                                   choices=b.alternatives(o), runbook={"title": evil, "steps": [evil] * 9, "uses": 3}),
                b.ask_message({"answer": evil + ". " + evil, "sources": ["doc:x"] * 9,
                               "hits": [{"id": "doc:x", "kind": "chat", "title": evil}]}, shared=True)):
        assert len(msg["blocks"]) <= 50 and len(msg["text"]) <= b.TEXT
        for text, limit in texts(msg):
            assert 0 < len(text) <= limit
            assert "<!channel>" not in text or text.startswith("<!channel>") and limit == b.HEADER  # plain_text
        assert len({e["action_id"] for e in actions(msg)}) == len(actions(msg))  # Slack wants them unique


def test_wrong_cause_lists_the_other_suspects_with_unique_pick_buttons():
    o = outcome()
    alts = b.alternatives(o)
    assert [a["change"] for a in alts] == ["chg:search-420", "chg:legacy-193"]  # distinct, the cause left out
    msg = b.incident_message("acme", HEAD, o, note="Marked wrong by <@U1>.", choices=alts)
    assert msg["blocks"][1]["text"]["text"] == "Marked wrong by <@U1>."  # our note keeps its mention
    picks = actions(msg)
    assert [p["action_id"] for p in picks] == ["pick_0", "pick_1", "confirm"]
    assert json.loads(picks[1]["value"])["c"] == "chg:legacy-193"


def test_resolved_incident_has_no_buttons_and_says_confirmed():
    rb = {"title": "Revert the config change on payments-gw", "steps": ["Revert the config change on payments-gw",
          "Watch checkout p99 recover"], "successes": 1, "uses": 1}
    msg = b.incident_message("acme", {**HEAD, "status": "resolved"}, outcome(), runbook=rb)
    assert not actions(msg) and "*Cause confirmed:*" in msg["blocks"][1]["text"]["text"]
    fix = msg["blocks"][2]["fields"][1]["text"]
    assert "Saved to memory: *Revert the config change on payments-gw* (confirmed once)" in fix
    assert fix.endswith("• Watch checkout p99 recover")


def test_no_cause_and_no_alternatives_means_no_buttons():
    o = outcome(root_cause=None, confidence={"level": "none", "label": "No cause found", "why": "a human should look"},
                refuted=[], baseline_pick=None, anomaly_baseline_pick=None)
    msg = b.incident_message("acme", HEAD, o)
    assert msg["blocks"][1]["text"]["text"] == "*No cause found:* a human should look."
    assert msg["blocks"][2]["fields"][1]["text"] == "*Fix*\nNone yet: no cause found, so a human should look first."
    assert not actions(msg) and "no single cause yet" in msg["text"]
    assert [a["text"]["text"] for a in actions(b.incident_message("acme", HEAD, outcome(root_cause=None)))] == [
        "Pick the cause"]


def test_ask_lead_is_bold_and_a_follow_up_note_sits_above_it():
    data = {"answer": 'Taking "it" as kafka, from your earlier question "who owns kafka?". kafka is owned by '
                      "Platform; members: Hana Costa. People who know kafka: Jae Haddad.",
            "resolved": {"pronoun": "it"}, "sources": ["doc:adr-011", "msg:chat-024", "ticket:X"],
            "hits": [{"id": "doc:adr-011", "kind": "decision", "title": "ADR-011: Kafka <retention>"},
                     {"id": "msg:chat-024", "kind": "chat", "title": "#platform"}]}
    msg = b.ask_message(data, shared=False)
    note, answer, src = msg["blocks"]
    assert msg["response_type"] == "ephemeral"
    assert note["elements"][0]["text"] == '_Taking "it" as kafka, from your earlier question "who owns kafka?"._'
    assert answer["text"]["text"] == ("*kafka is owned by Platform; members: Hana Costa.*\n"
                                      "People who know kafka: Jae Haddad.")
    assert src["elements"][0]["text"] == ("Sources: ADR-011: Kafka &lt;retention&gt; (`doc:adr-011`) · "
                                          "chat in #platform (`msg:chat-024`) · `ticket:X`")
    assert b.ask_message({"answer": "Nothing in docs mentions zzz.", "sources": []}, shared=True) == {
        "response_type": "in_channel", "text": "Nothing in docs mentions zzz.",
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "*Nothing in docs mentions zzz.*"}}]}


def test_help_lists_every_command():
    text = b.help_message()["blocks"][0]["text"]["text"]
    assert all(f"`{cmd}`" in text for cmd, _ in b.HELP) and "incident" in text


def test_ask_parts_each_get_a_line_and_a_quoted_excerpt_stays_whole():
    parts = ["kafka is owned by Platform; members: Hana Costa.", "People who know kafka: Jae Haddad.",
             "Most relevant: ADR-011 <retention>."]
    msg = b.ask_message({"answer": 'Taking "it" as kafka, from your earlier question "who?". ' + " ".join(parts),
                         "parts": parts, "resolved": {"pronoun": "it"}, "sources": []}, shared=False)
    note, answer = msg["blocks"]
    assert note["elements"][0]["text"] == '_Taking "it" as kafka, from your earlier question "who?"._'
    assert answer["text"]["text"] == ("*kafka is owned by Platform; members: Hana Costa.*\n"
                                      "People who know kafka: Jae Haddad.\nMost relevant: ADR-011 &lt;retention&gt;.")
    quoted = 'Most relevant: Postmortem: "checkout latency for two hours. Root cause: inv-880." Also: a ticket.'
    assert b.ask_message({"answer": quoted, "sources": []}, shared=False)["text"] == (
        'Most relevant: Postmortem: "checkout latency for two hours. Root cause: inv-880."')
