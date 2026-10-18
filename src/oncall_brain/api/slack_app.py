"""Two-way Slack (docs/SLACK.md): the /oncall slash command and its Confirm cause / Wrong cause buttons.

POST /slack/commands  /oncall <question> | share <question> | incident <service> <symptom> | help
POST /slack/actions   block_actions from the buttons on an incident message

Both answer 404 until SLACK_SIGNING_SECRET is set, and 401 unless the request carries Slack's signature over the raw
body with a timestamp under 5 minutes old, seen for the first time. They sit outside /api/, so API_TOKEN does not
apply: the signature is their credential. They work on one company graph, SLACK_TENANT, whatever a payload names.
The work goes through the same services as the HTTP API: ask (run_tool), the alert webhook path (raise_alert,
run_agents, so the tenant lock and the token budget apply) and resolve. What Slack started is answered in Slack only
(through the response_url, never also through SLACK_WEBHOOK_URL), and only to Slack's own hosts.
Formatting is in adapters/slack_blocks.py."""

import hashlib
import hmac
import json
import logging
import re
import time
from contextlib import suppress
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import ValidationError
from redis.exceptions import LockError, RedisError
from starlette.concurrency import run_in_threadpool

from oncall_brain.adapters import slack_blocks as blocks
from oncall_brain.config import get_settings
from oncall_brain.ports import GraphRepository
from oncall_brain.services import brain
from oncall_brain.services import respond as respond_svc
from oncall_brain.services.limits import RunsBusy, Throttled, throttle

router = APIRouter(prefix="/slack", include_in_schema=False)
log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO line prints response_url and webhook URLs (secrets)
MAX_AGE = 5 * 60  # Slack's replay window
SLACK_HOOKS = {"hooks.slack.com", "hooks.slack-gov.com"}  # where Slack's response_urls point
# What an engineer types after the service, mapped to the alert symptoms the graph knows.
SYMPTOMS = {"latency": "latency", "slow": "latency", "p99": "latency", "timeout": "latency", "timeouts": "latency",
            "error": "errors", "errors": "errors", "5xx": "errors", "500s": "errors", "failing": "errors",
            "down": "errors", "saturation": "saturation", "saturated": "saturation", "cpu": "saturation",
            "memory": "saturation"}
BUSY = "Another agent run is working on this company's graph right now (one at a time). Try again in a minute."
ALREADY = {**blocks.say("Already resolved, so nothing changed."), "replace_original": False}  # only the clicker


def _api():
    # ponytail: imported on use, since api/app.py includes this router at its end (a top-level import would be circular)
    from oncall_brain.api import app

    return app


def _redis():
    return _api().store().db.connection


async def _verified(request: Request) -> dict[str, str]:
    """The form fields of a request Slack signed, else 404 (Slack is off) or 401. The raw body is read once and the
    signature is checked over those exact bytes before anything is parsed. A signature is accepted once: Slack never
    sends a command or a click twice, so a repeat is a replay."""
    secret = get_settings().slack_signing_secret
    if not secret:
        raise HTTPException(404, "Not Found")
    body = await request.body()
    ts = request.headers.get("x-slack-request-timestamp", "")
    sent = request.headers.get("x-slack-signature", "").encode("latin-1")  # Starlette decodes headers as latin-1
    fresh = re.fullmatch(r"\d{1,12}", ts) is not None and abs(time.time() - int(ts)) <= MAX_AGE
    good = b"v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest().encode()
    if not (fresh and hmac.compare_digest(sent, good)):
        raise HTTPException(401, "invalid Slack signature")
    # A timestamp may be up to MAX_AGE ahead of us, so its signature stays acceptable for up to 2 * MAX_AGE.
    if not await run_in_threadpool(_redis().set, f"oncall_brain:slack:seen:{good[3:].decode()}", 1, nx=True,
                                   ex=2 * MAX_AGE):
        raise HTTPException(401, "invalid Slack signature")
    return {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}


def _why(e: Exception) -> str:
    """What went wrong, in words fit for the channel and escaped (the traceback goes to the server log; FalkorDB's
    host and port never reach the channel)."""
    if isinstance(e, HTTPException):
        text = str(e.detail)
    elif isinstance(e, LockError):
        text = BUSY
    elif isinstance(e, RunsBusy | Throttled):  # MAX_CONCURRENT_RUNS, RUNS_PER_HOUR: their words are for people
        text = str(e)
    elif isinstance(e, RedisError):
        text = "the graph database is unreachable or failed (see the server log)"
    elif isinstance(e, ValueError) and not isinstance(e, ValidationError):  # ours: an unknown id, a foreign button
        text = str(e)
    else:
        text = f"{type(e).__name__} (see the server log)"
    return blocks.esc(text)


def _post(url: str, msg: dict[str, Any]) -> None:
    """Send a message to a response_url, only on Slack's hosts (a forged one must not make us POST inside our
    network). A refusal is logged with Slack's reason (never the URL: it is a credential), and a card Slack refuses is
    sent once more as plain text, so the channel still gets the answer."""
    u = urlsplit(url)
    if u.scheme != "https" or u.hostname not in SLACK_HOOKS:
        log.warning("refused a response_url outside Slack (host %r)", u.hostname)
        return
    try:
        httpx.post(url, json=msg, timeout=10).raise_for_status()
    except httpx.HTTPStatusError as e:
        log.warning("Slack refused a response_url post: %s %r", e.response.status_code, e.response.text[:80])
        if "blocks" in msg:
            _post(url, {k: v for k, v in msg.items() if k != "blocks"})
    except httpx.HTTPError as e:
        log.warning("Slack response_url post failed: %s", type(e).__name__)


def _tenant() -> str:
    s = get_settings()
    return s.slack_tenant or s.default_tenant


def _repo(tenant: str) -> GraphRepository:
    if not _api().store().exists(tenant):
        raise ValueError(f"the company graph {tenant!r} is not seeded yet (POST /api/tenants/{tenant}/reset seeds it)")
    return _api().store().tenant(tenant)


def _busy(repo: GraphRepository) -> bool:
    return repo.lock().locked()  # one agent run per tenant at a time (FalkorRepository.lock)


def _pending(repo: GraphRepository) -> str:
    """Set while a Slack-started run is queued or running: the tenant lock is taken only once the thread starts."""
    return f"oncall_brain:slack:pending:{repo.tenant}"


@router.post("/commands")
async def commands(request: Request) -> dict[str, Any]:
    form = await _verified(request)
    return await run_in_threadpool(_command, form)


def _command(f: dict[str, str]) -> dict[str, Any]:
    text = " ".join(f.get("text", "").split())
    word, _, rest = text.partition(" ")
    word = word.lower()
    if word in ("", "help"):
        return blocks.help_message()
    try:
        repo = _repo(_tenant())
        if word == "incident":
            return _incident(repo, rest, f)
        shared = word == "share"
        question = rest if shared else text
        if not question:
            return blocks.say("Ask a question after `share`, e.g. `/oncall share who owns kafka?`")
        if len(question) > 300:
            return blocks.say("Keep the question under 300 characters.")
        out = respond_svc.run_tool(repo, "ask", {"question": question, "user": f"slack:{f['user_id']}",
                                                 "session": f["channel_id"]})
        return blocks.ask_message(out.data, shared=shared)
    except Exception as e:
        log.exception("/oncall %s failed", word)
        return blocks.say(f"The brain could not answer: {_why(e)}")


def _incident(repo: GraphRepository, rest: str, f: dict[str, str]) -> dict[str, Any]:
    """The card of the incident already working that alert, else: ack now (Slack waits 3 s), run the agents in a
    thread, post the answer to the command's response_url."""
    q = brain.padded(rest)
    svc = next((e for e in brain.link(repo.read("link_entities", q=q).rows, q) if e["kind"] == "service"), None)
    symptom = next((SYMPTOMS[w] for w in re.findall(r"[a-z0-9]+", rest.lower()) if w in SYMPTOMS), None)
    if not svc:
        return blocks.say(f'Which service? None I know is in "{blocks.esc(rest)}". '
                          "E.g. `/oncall incident checkout latency`.")
    if not symptom:
        name = blocks.esc(svc["name"])
        return blocks.say(f"What is {name} showing: latency, errors or saturation? "
                          f"E.g. `/oncall incident {name} latency`.")
    if _busy(repo):
        return blocks.say(BUSY)
    try:  # RUNS_PER_HOUR per Slack user: every request comes from Slack's addresses, so the per-IP bucket is shared
        throttle(_api().store(), "run", f"slack:{f.get('user_id', '')}", get_settings().runs_per_hour)
    except Throttled as e:
        return blocks.say(blocks.esc(str(e)))
    alert = _open_alert(repo, svc, symptom)
    if alert and alert["incident"]:  # a run (here, the UI, the alert webhook) already worked it: show it, ~30 ms
        return {**_render(repo, alert["incident"]), "response_type": "in_channel"}
    if not _redis().set(_pending(repo), 1, nx=True, ex=900):  # two commands at once: one run
        return blocks.say(BUSY)
    Thread(target=_work, args=(repo, svc, symptom, alert and alert["id"], f.get("response_url", "")),
           daemon=True).start()
    return blocks.say(f"Three agents are on it: {blocks.esc(svc['name'])} {symptom}. The answer lands here in about "
                      "a minute.", "in_channel")


def _open_alert(repo: GraphRepository, svc: dict[str, Any], symptom: str) -> dict[str, Any] | None:
    """The first alert on that service and symptom still open in the inbox, with the incident working it if any
    (list_alerts order: the demo's acts in story order, then by time; not yet resolved)."""
    # ponytail: oldest open alert first; add "newest" or an alert id argument if a real inbox piles up stale ones.
    return next((a for a in repo.read("list_alerts").rows
                 if a["service"] == svc["id"] and a["symptom"] == symptom and a["status"] != "resolved"), None)


def _work(repo: GraphRepository, svc: dict[str, Any], symptom: str, alert: str | None, url: str) -> None:
    """Work the alert (or raise one now, through the same tool as the alert webhook, POST .../alerts) and post the
    card; a failure is posted in words and logged with its traceback."""
    try:
        if not alert:
            alert = respond_svc.run_tool(repo, "raise_alert", {
                "service": svc["id"], "symptom": symptom, "name": f"{svc['name']} {symptom}, raised in Slack"}
            ).data["alert"]
        run = _api().run_agents(repo, alert, post=False)  # the card below is the post
        msg = _render(repo, run["incident_id"])
    except RunsBusy as e:  # the run cap: say so, no traceback
        msg = blocks.say(f"Not started: {blocks.esc(str(e))}.")
    except Exception as e:
        log.exception("Slack incident run for %s %s on tenant %s failed", svc["id"], symptom, repo.tenant)
        msg = blocks.say(f"The agents could not finish: {_why(e)}")
    finally:
        with suppress(RedisError):  # else it expires with its 15-minute lease
            _redis().delete(_pending(repo))
    _post(url, {**msg, "response_type": "in_channel", "replace_original": False})


def _render(repo: GraphRepository, incident_id: str, **kw: Any) -> dict[str, Any]:
    """The incident message, all from the graph: head, outcome (as GET .../incidents/{id} has it) and the runbook the
    update suggests (memory's, or the one a human confirmed)."""
    head = repo.read("incident_head", incident_id=incident_id).rows
    if not head:
        raise ValueError(f"unknown incident {incident_id!r}")
    runbooks = repo.read("update_facts", incident_id=incident_id).rows[0]["runbooks"]
    return blocks.incident_message(repo.tenant, head[0], respond_svc.outcome(repo, incident_id, []),
                                   runbook=next((r for r in runbooks if r["id"]), None), **kw)


@router.post("/actions")
async def actions(request: Request) -> Response:
    """Ack at once (Slack waits 3 s; a resolve can wait on the tenant lock) and update the message from a thread."""
    form = await _verified(request)
    try:
        p = json.loads(form["payload"])
    except (KeyError, ValueError):
        raise HTTPException(400, "no interaction payload") from None
    if not (isinstance(p, dict) and p.get("type") == "block_actions" and isinstance(p.get("response_url"), str)
            and isinstance(p.get("user"), dict) and isinstance(p["user"].get("id"), str)
            and isinstance(p.get("actions"), list) and p["actions"] and isinstance(p["actions"][0], dict)):
        raise HTTPException(400, "unsupported interaction")
    Thread(target=_action, args=(p,), daemon=True).start()
    return Response(status_code=200)


def _button(act: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The action_id and value of one of our buttons (blocks.value), else ValueError."""
    aid = str(act.get("action_id", ""))
    try:
        v = json.loads(str(act.get("value", "")))
    except ValueError:
        v = None
    ours = aid in ("confirm", "wrong") or re.fullmatch(r"pick_\d", aid)
    if not (ours and isinstance(v, dict) and isinstance(v.get("i"), str)
            and (aid == "wrong" or isinstance(v.get("c"), str))):
        raise ValueError("that button is not one of ours")
    return aid, v


def _action(p: dict[str, Any]) -> None:
    """A button on an incident message: confirm (or pick) a cause through the resolve service, or list the other
    suspects (Wrong cause). The message is updated in place through the payload's response_url; a click on an incident
    already resolved is told so privately and leaves the message (and who confirmed it) as it is."""
    url, user = p["response_url"], blocks.esc(p["user"]["id"])
    try:
        aid, v = _button(p["actions"][0])
        repo, inc, change = _repo(_tenant()), v["i"], v.get("c")
        if v.get("t") != repo.tenant:  # SLACK_TENANT only: a crafted button must not reach another company's graph
            raise ValueError("that button is for another company graph")
        head = repo.read("incident_head", incident_id=inc).rows
        if head and head[0]["status"] == "resolved":
            return _post(url, ALREADY)
        if aid == "wrong":
            alts = blocks.alternatives(respond_svc.outcome(repo, inc, []))
            lead = f"Marked wrong by <@{user}>." if change else f"<@{user}> is picking the cause."
            note = (f"{lead} Which change caused it? Your pick is written to the graph and becomes memory." if alts
                    else f"{lead} No other suspect is on record: a human should look. The incident stays open.")
            msg = _render(repo, inc, note=note, choices=alts)
        else:
            if respond_svc.resolve(repo, inc, change)["data"] is None:  # resolved by someone else meanwhile
                return _post(url, ALREADY)
            who = (f"Confirmed by <@{user}>" if aid == "confirm"
                   else f"<@{user}> picked `{blocks.esc(change)}` as the cause")
            msg = _render(repo, inc, note=f"{who}: the fix is saved to memory, so the next incident like this "
                                          "tries it first.")
    except Exception as e:
        log.exception("Slack action failed")
        return _post(url, {**blocks.say(f"That did not work: {_why(e)}"), "replace_original": False})
    _post(url, {**msg, "replace_original": True})
