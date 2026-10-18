"""Two-way Slack (api/slack_app.py) end to end on a seeded tenant and the rule planner: Slack's request signing, the
/oncall command (help, ask with a follow-up, incident in a thread) and the Confirm / Wrong cause buttons. Nothing
reaches Slack: httpx.post (what the app uses to answer a response_url and the webhook) is replaced by a recorder."""

import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from oncall_brain.api import app as app_module
from oncall_brain.api import slack_app
from oncall_brain.config import get_settings
from oncall_brain.mcp_server import _registry_handler
from oncall_brain.services.seeding import reset

pytestmark = pytest.mark.integration
SECRET = "test-signing-secret"
URL = "https://hooks.slack.com/commands/T1/1/test"
WEBHOOK = "https://hooks.slack.com/services/T1/B1/webhook"
INC = "inc:checkout-latency"


def signed(fields: dict, secret: str = SECRET, ts: int | None = None) -> tuple[str, dict]:
    body = urlencode(fields)
    ts = str(int(time.time()) if ts is None else ts)
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return body, {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig,
                  "Content-Type": "application/x-www-form-urlencoded"}


def settings(monkeypatch, **kv: str) -> None:
    for k, v in kv.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


@pytest.fixture
def slack(store, monkeypatch):
    """(client, command, click, posted, threads, tenant): a seeded tenant Slack is pointed at, and every message the
    app sends to Slack (response_url or webhook) recorded instead of sent. click() waits for the click's thread."""
    t = f"slack_test_{os.getpid()}"
    reset(store, t)
    settings(monkeypatch, SLACK_SIGNING_SECRET=SECRET, SLACK_TENANT=t, SLACK_WEBHOOK_URL=WEBHOOK, API_TOKEN="")
    posted: list[tuple[str, dict]] = []

    def record(url, json=None, timeout=None):
        posted.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(slack_app.httpx, "post", record)
    threads: list[threading.Thread] = []

    class Recorded(threading.Thread):
        def start(self) -> None:
            threads.append(self)
            super().start()

    monkeypatch.setattr(slack_app, "Thread", Recorded)
    c = TestClient(app_module.app)

    def command(text: str, user: str = "U1", channel: str = "C1") -> httpx.Response:
        body, headers = signed({"command": "/oncall", "text": text, "user_id": user, "channel_id": channel,
                                "response_url": URL, "trigger_id": uuid.uuid4().hex})  # Slack's is unique too
        return c.post("/slack/commands", content=body, headers=headers)

    def click(button: dict, user: str = "U2", url: str = URL + "/action") -> httpx.Response:
        payload = {"type": "block_actions", "user": {"id": user}, "response_url": url, "trigger_id": uuid.uuid4().hex,
                   "actions": [{"action_id": button["action_id"], "value": button["value"], "type": "button"}]}
        body, headers = signed({"payload": json.dumps(payload)})
        r = c.post("/slack/actions", content=body, headers=headers)
        for th in threads:  # the click is acked at once; its work runs in a thread
            th.join(60)
        return r

    yield c, command, click, posted, threads, t
    monkeypatch.undo()
    get_settings.cache_clear()
    store.drop(t)


def buttons(msg: dict) -> dict[str, dict]:
    return {e["action_id"]: e for blk in msg["blocks"] if blk["type"] == "actions" for e in blk["elements"]}


def everything(msg: dict) -> str:
    return json.dumps(msg["blocks"])


def status(store, t: str) -> str:
    return store.tenant(t).read("incident_head", incident_id=INC).rows[0]["status"]


def test_every_request_must_carry_slacks_signature_once(slack, monkeypatch):
    c, command, *_ = slack
    assert command("help").status_code == 200
    fields = {"command": "/oncall", "text": "help", "user_id": "U1", "channel_id": "C1", "response_url": URL}
    body, good = signed(fields)
    for headers in ({**good, "X-Slack-Signature": signed(fields, secret="wrong")[1]["X-Slack-Signature"]},
                    signed(fields, ts=int(time.time()) - 6 * 60)[1],  # a replayed request: signed, but stale
                    {"Content-Type": good["Content-Type"]},  # no signature headers at all
                    {**good, "X-Slack-Request-Timestamp": "１２３".encode()}):  # not ASCII digits
        for path in ("/slack/commands", "/slack/actions"):
            r = c.post(path, content=body, headers=headers)
            assert r.status_code == 401 and r.json() == {"detail": "invalid Slack signature"}
    assert c.post("/slack/commands", content=body + "&x=1", headers=good).status_code == 401  # body tampered
    assert c.post("/slack/commands", content=body, headers=good).status_code == 200
    replay = c.post("/slack/commands", content=body, headers=good)  # the same signed request again, still fresh
    assert replay.status_code == 401 and replay.json() == {"detail": "invalid Slack signature"}

    settings(monkeypatch, SLACK_SIGNING_SECRET="")  # Slack not configured: the endpoints are not there
    assert c.post("/slack/commands", content=body, headers=good).status_code == 404
    assert c.post("/slack/actions", content=body, headers=good).status_code == 404


def test_api_token_does_not_block_slack_and_help_lists_the_commands(slack, monkeypatch):
    c, command, *_ = slack
    settings(monkeypatch, API_TOKEN="s3cret")
    assert c.get("/api/tools").status_code == 401  # /api/* still needs the token
    r = command("help")
    assert r.status_code == 200 and r.json()["response_type"] == "ephemeral"
    assert "/oncall incident" in everything(r.json())
    assert command("").json() == r.json()


def test_the_api_and_mcp_refuse_to_act_as_a_slack_user(slack, store):
    c, command, _, _, _, t = slack
    command("who owns payments-gw?", user="U7", channel="C9")
    for tool, args in (("my_questions", {"user": "slack:U7"}), ("ask", {"question": "why was legacy-billing retired?",
                                                                        "user": "@Slack:u7", "session": "c9"}),
                       ("ask", {"question": "who owns kafka?", "user": "person:slack:u7"})):
        r = c.post(f"/api/tenants/{t}/tools/{tool}", json=args)
        assert r.status_code == 403 and "belong to /oncall" in r.json()["detail"]
        with pytest.raises(ValueError, match="belong to /oncall"):
            _registry_handler(tool)(store, t, args)
    assert c.post(f"/api/tenants/{t}/tools/my_questions", json={"user": "person:hana-costa"}).status_code == 200
    follow = command("and who is on call for it?", user="U7", channel="C9").json()
    assert 'Taking \\"it\\" as payments-gw' in everything(follow)  # nothing was planted in U7's session


def test_ask_and_a_follow_up_with_it_in_the_same_channel(slack, store):
    c, command, _, posted, _, t = slack
    first = command("who owns kafka?").json()
    assert first["response_type"] == "ephemeral" and "*kafka is owned by Platform" in everything(first)
    assert "Sources: " in everything(first) and "doc:adr-011" in everything(first)
    answer = first["blocks"][0]["text"]["text"]
    assert answer.startswith("*kafka is owned by Platform") and "*\nPeople who know kafka" in answer  # one part a line

    follow = command("and who is on call for it?").json()
    assert 'Taking \\"it\\" as kafka' in everything(follow) and "Hana Costa" in everything(follow)
    other = command("and who is on call for it?", channel="C2").json()  # another channel: nothing to refer back to
    assert "Taking" not in everything(other)

    shared = command("share why was legacy-billing retired?").json()
    assert shared["response_type"] == "in_channel" and "ADR-012" in everything(shared)
    # The conversation is in the graph, per Slack user and channel.
    rows = store.tenant(t).read("user_questions", user="slack:u1", session="c1", ids=[], text=None, limit=10).rows
    assert [r["text"] for r in rows][:2] == ["why was legacy-billing retired?", "and who is on call for it?"]
    assert not posted  # ask answers inline


def test_incident_acks_at_once_then_posts_the_answer_and_confirm_resolves_it(slack, store, monkeypatch):
    c, command, click, posted, threads, t = slack
    gate, real = threading.Event(), app_module.run_agents

    def held(repo, alert_id, on_step=None, post=True):  # the run waits until the ack is back: the ack cannot wait
        assert gate.wait(30)
        return real(repo, alert_id, on_step, post)

    monkeypatch.setattr(app_module, "run_agents", held)
    t0 = time.perf_counter()
    ack = command("incident checkout is slow, latency spike").json()
    assert time.perf_counter() - t0 < 3 and not posted
    assert ack == {"response_type": "in_channel", "text": "Three agents are on it: checkout latency. The answer "
                                                          "lands here in about a minute."}
    assert "Another agent run" in command("incident checkout latency", user="U5").json()["text"]  # one run, not two
    gate.set()
    threads[0].join(60)
    assert len(threads) == 1
    (url, msg), = posted  # the card only: what Slack started is not also posted through the webhook
    assert url == URL and msg["response_type"] == "in_channel" and msg["replace_original"] is False
    text = everything(msg)
    assert "checkout p99 latency above 2s" in text and "*payments-gw*" in text and "Sana Brandt" in text
    assert "Very likely" in text and "Asha Nakamura" in text and "chg:pgw-pool-1" in text
    assert "Suggested: *Revert the config change on payments-gw*" in text
    b = buttons(msg)
    assert set(b) == {"confirm", "wrong"}

    again = command("incident checkout latency", user="U9").json()  # the agents already worked it: the card, inline
    assert again["response_type"] == "in_channel" and set(buttons(again)) == {"confirm", "wrong"}
    assert len(threads) == 1 and len(posted) == 1

    assert click(b["confirm"]).status_code == 200
    url, upd = posted[-1]
    assert url == URL + "/action" and upd["replace_original"] is True
    assert "Confirmed by <@U2>: the fix is saved to memory" in everything(upd) and not buttons(upd)
    assert "Cause confirmed" in everything(upd) and "Revert the config change on payments-gw" in everything(upd)
    assert status(store, t) == "resolved"
    assert store.tenant(t).read("cause_facts", incident_id=INC).rows[0]["change"] == "chg:pgw-pool-1"

    assert click(b["confirm"], user="U3").status_code == 200  # a stale copy of the buttons, clicked again
    assert posted[-1][1] == {"response_type": "ephemeral", "text": "Already resolved, so nothing changed.",
                             "replace_original": False}  # only the clicker sees it; "Confirmed by" stays
    runbook = store.tenant(t).read("update_facts", incident_id=INC).rows[0]["runbooks"][0]
    assert runbook["successes"] == 1  # resolved once, not twice
    assert all(u != WEBHOOK for u, _ in posted)


def test_wrong_cause_lists_the_other_suspects_and_a_pick_resolves_with_it(slack, store):
    c, command, click, posted, threads, t = slack
    command("incident checkout latency")
    threads[0].join(60)
    wrong = buttons(posted[-1][1])["wrong"]
    click(wrong)
    msg = posted[-1][1]
    assert "Marked wrong by <@U2>" in everything(msg) and "legacy-193" in everything(msg)
    picks = buttons(msg)
    assert "confirm" in picks and "pick_0" in picks
    choice = json.loads(picks["pick_0"]["value"])["c"]
    assert choice != "chg:pgw-pool-1"
    click(picks["pick_0"])
    assert f"<@U2> picked `{choice}` as the cause" in everything(posted[-1][1])
    assert store.tenant(t).read("cause_facts", incident_id=INC).rows[0]["change"] == choice


def test_crafted_and_malformed_clicks_change_nothing(slack, store):
    c, command, click, posted, threads, t = slack
    command("incident checkout latency")
    threads[0].join(60)
    confirm = buttons(posted[-1][1])["confirm"]
    other = f"{t}_other"  # another company on the same FalkorDB, with the same incident open
    reset(store, other)
    try:
        app_module.run_agents(store.tenant(other), "alert:checkout-latency", post=False)
        click({**confirm, "value": json.dumps({"t": other, "i": INC, "c": "chg:pgw-pool-1"})})
        assert posted[-1][1]["text"] == "That did not work: that button is for another company graph"
        assert status(store, other) == "open"
    finally:
        store.drop(other)
    for bad in ({**confirm, "action_id": "foo"}, {**confirm, "value": "not json"},
                {**confirm, "value": json.dumps({"t": t, "i": INC, "c": None})}):
        click(bad)
        assert posted[-1][1]["text"] == "That did not work: that button is not one of ours"
    n = len(posted)
    click({**confirm, "action_id": "foo"}, url="http://127.0.0.1:9/")  # not Slack's host: nothing is sent there
    assert len(posted) == n
    for payload in ([], {"type": "block_actions", "actions": [], "user": {"id": "U1"}, "response_url": URL},
                    {"type": "block_actions", "actions": [confirm], "user": {"id": "U1"}}, {"type": "view_submission"}):
        body, headers = signed({"payload": json.dumps(payload)})
        assert c.post("/slack/actions", content=body, headers=headers).status_code == 400
    assert status(store, t) != "resolved"


def test_busy_tenant_bad_input_and_a_failed_run_are_said_plainly(slack, store, monkeypatch):
    c, command, click, posted, threads, t = slack
    with store.tenant(t).lock():
        assert "Another agent run is working" in command("incident checkout latency").json()["text"]
    assert not threads
    assert command("incident nothing here").json()["text"].startswith('Which service? None I know is in "nothing')
    assert command("incident checkout").json()["text"].startswith("What is checkout showing: latency, errors")

    for error, said in ((RuntimeError("planner exploded"), "RuntimeError (see the server log)"),
                        (ValueError("<!channel> no such alert"), "&lt;!channel&gt; no such alert"),
                        (RedisConnectionError("Error 111 connecting to falkordb:6379."),
                         "the graph database is unreachable or failed (see the server log)")):
        def boom(repo, alert_id, on_step=None, post=True, error=error):
            raise error

        monkeypatch.setattr(app_module, "run_agents", boom)
        assert "checkout latency" in command("incident checkout is slow").json()["text"]  # slow: latency
        threads[-1].join(60)
        assert posted[-1][1]["text"] == f"The agents could not finish: {said}"


def test_a_card_slack_refuses_is_sent_again_as_plain_text(slack, monkeypatch):
    c, command, click, posted, threads, t = slack

    def picky(url, json=None, timeout=None):  # Slack answers 400 invalid_blocks to a card it cannot render
        posted.append((url, json))
        return httpx.Response(400 if "blocks" in json else 200, text="invalid_blocks",
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(slack_app.httpx, "post", picky)
    command("incident checkout latency")
    threads[0].join(60)
    (_, card), (_, plain) = posted
    assert "blocks" in card and "blocks" not in plain
    assert plain["text"] == card["text"] and plain["response_type"] == "in_channel"
