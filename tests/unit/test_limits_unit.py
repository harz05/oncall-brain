"""The abuse limits without FalkorDB: throttle windows and words, the run slot, the daily LLM budget inside RunBudget,
the body cap (Content-Length and a chunked body), the security headers and the startup warning."""

import logging
import re

import anyio
import pytest
from starlette.applications import Starlette
from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from oncall_brain.api.app import throttle_buckets
from oncall_brain.api.guards import CSP, BodyLimit, SecurityHeaders
from oncall_brain.config import Settings
from oncall_brain.domain.models import Decision
from oncall_brain.services import limits
from oncall_brain.services.limits import DailyBudget, RunsBusy, Throttled, client_key, run_slot, throttle
from oncall_brain.services.respond import RunBudget
from oncall_brain.wiring import exposure_warning

BOARD = {"incident": {"id": "inc:x", "service": "svc:checkout", "status": "open"}, "steps": [], "hypotheses": [],
         "recalls": []}
HOUR = 1_800_000_000  # a whole hour (and minute) in epoch seconds


class Counters:
    """The GraphStore counter half, in memory (expiry is the window number in the key; ttl is not needed here)."""

    def __init__(self):
        self.values: dict[str, int] = {}

    def incr(self, key, ttl, by=1):
        self.values[key] = self.values.get(key, 0) + by
        return self.values[key]

    def counter(self, key):
        return self.values.get(key, 0)


def test_a_throttle_trips_at_n_plus_1_per_client_and_window_with_retry_after_and_plain_words():
    c = Counters()
    for _ in range(3):
        throttle(c, "req", "a", 3, now=HOUR + 23)
    with pytest.raises(Throttled) as e:
        throttle(c, "req", "a", 3, now=HOUR + 23)
    assert str(e.value) == "Too many requests from your address: 3 per minute. Try again in 37 seconds."
    assert e.value.retry_after == 37
    throttle(c, "req", "b", 3, now=HOUR + 23)  # another client has its own bucket
    throttle(c, "req", "a", 3, now=HOUR + 60)  # the next window starts from zero
    throttle(c, "req", "a", 0, now=HOUR + 61)  # 0 = off: nothing counted
    assert c.values[f"oncall_brain:rl:req:a:{(HOUR + 60) // 60}"] == 1

    throttle(c, "run", "a", 1, now=HOUR + 48 * 60)
    with pytest.raises(Throttled) as e:
        throttle(c, "run", "a", 1, now=HOUR + 48 * 60)
    assert str(e.value) == "Too many agent runs from your address: 1 per hour. Try again in 12 minutes."
    assert e.value.retry_after == 720
    throttle(c, "write", "a", 1, now=HOUR + 59)
    with pytest.raises(Throttled, match=r"^Too many writes from your address: 1 per minute. Try again in 1 second.$"):
        throttle(c, "write", "a", 1, now=HOUR + 59)


def test_an_ipv6_client_counts_by_its_64_and_an_ipv4_mapped_one_as_its_ipv4_address():
    assert client_key("2001:db8:1:2:aaaa::1") == client_key("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert client_key("2001:db8:1:3::1") == "2001:db8:1:3::/64"
    assert client_key("::ffff:203.0.113.7") == client_key("203.0.113.7") == "203.0.113.7"  # a dual-stack bind
    assert client_key("unknown") == "unknown"


def test_the_buckets_of_a_request():
    def buckets(method, path, query=""):
        return throttle_buckets(method, path, QueryParams(query))

    base = "/api/tenants/acme"
    assert buckets("GET", "/api/health") == [] and buckets("POST", "/web/") == []
    assert buckets("GET", f"{base}/alerts") == ["req"]
    assert buckets("POST", f"{base}/tools/ask") == ["req", "write"]  # Ask records the question
    assert buckets("POST", f"{base}/alerts", "respond=true") == ["req", "write", "run"]
    assert buckets("POST", f"{base}/reset") == ["req", "write", "run"]
    # ?compare=memory replays the incident without memory: two runs' worth of tokens, two runs
    assert buckets("POST", f"{base}/alerts/a/respond/stream", "compare=memory") == ["req", "write", "run", "run"]


def test_the_run_slot_refuses_past_the_limit_and_frees_on_exit():
    with run_slot(2), run_slot(2):
        with pytest.raises(RunsBusy, match=r"^2 agent runs are already in progress; try again in a minute$"):
            with run_slot(2):
                pass
        with run_slot(0):  # 0 = no limit
            pass
    with pytest.raises(ValueError), run_slot(1):
        raise ValueError("a run that fails")
    with run_slot(1), pytest.raises(RunsBusy, match=r"^1 agent run is already in progress"), run_slot(1):
        pass
    assert limits._running == 0


class Spendy:
    name = "spendy via test"

    def __init__(self):
        self.calls = 0

    def decide(self, role, board, tools):
        self.calls += 1
        return Decision(action="call", tool="blast_radius", args={"service": "svc:checkout"}, reason="because",
                        by="spendy", usage=1000)


def test_the_daily_budget_is_shared_by_runs_and_hands_the_rest_of_the_day_to_the_rules():
    c, model = Counters(), Spendy()
    daily = DailyBudget(c, cap=2500)
    first = RunBudget(model, cap=0, daily=daily)  # cap 0: no per-run cap, only the daily one
    picks = [first.decide("triage", BOARD, []) for _ in range(4)]
    assert [d.by for d in picks] == ["spendy", "spendy", "spendy", "rules"] and model.calls == 3
    assert daily.used_today() == 3000 and first.used == 3000  # checked before each call: one call may overshoot
    assert picks[3].reason.startswith("LLM fallback: today's LLM budget (2,500 tokens) is spent; the rules planner "
                                      "decides until 00:00 UTC. ")
    second = RunBudget(model, cap=300_000, daily=daily)  # the next run, from any process: rules from the start
    assert second.decide("triage", BOARD, []).by == "rules" and model.calls == 3
    assert DailyBudget.key().startswith("oncall_brain:llm_tokens:20") and len(DailyBudget.key()) == 34

    free = DailyBudget(Counters(), cap=0)  # cap 0 counts (for /api/health) and never stops the model
    RunBudget(model, cap=0, daily=free).decide("triage", BOARD, [])
    assert free.used_today() == 1000 and not free.spent()


def test_the_hourly_slice_hands_the_rest_of_the_hour_to_the_rules_so_one_hour_cannot_spend_the_day():
    c, model = Counters(), Spendy()
    budget = RunBudget(model, cap=0, daily=DailyBudget(c, cap=1_000_000, hourly=1500))
    picks = [budget.decide("triage", BOARD, []) for _ in range(3)]
    assert [d.by for d in picks] == ["spendy", "spendy", "rules"] and model.calls == 2
    assert re.match(r"LLM fallback: this hour's share of the LLM budget \(1,500 tokens\) is spent; the rules planner "
                    r"decides until \d\d:00 UTC\. ", picks[2].reason)
    assert c.values[DailyBudget.key()] == c.values[DailyBudget.hour_key()] == 2000
    assert DailyBudget.hour_key() == DailyBudget.key() + DailyBudget.hour_key()[-3:]  # <day>T<hh>


async def _echo(request: Request) -> JSONResponse:
    return JSONResponse({"got": len(await request.body()), "https": request.url.scheme == "https"})


def _app(middleware) -> Starlette:
    app = Starlette(routes=[Route("/{p:path}", _echo, methods=["GET", "POST"])])
    app.add_middleware(middleware)
    return app


def test_the_body_cap_refuses_by_content_length_and_while_a_chunked_body_arrives(monkeypatch):
    monkeypatch.setenv("MAX_BODY_BYTES", "1000")
    from oncall_brain.config import get_settings

    get_settings.cache_clear()
    try:
        c = TestClient(_app(BodyLimit))
        assert c.post("/x", content=b"a" * 1000).json()["got"] == 1000
        big = c.post("/x", content=b"a" * 1001)
        assert big.status_code == 413 and big.json() == {"detail": "request body too large: the limit is 1,000 bytes"}

        sent: list[dict] = []  # a chunked body: no Content-Length, three 400-byte chunks

        async def chunked():
            chunks = [{"type": "http.request", "body": b"a" * 400, "more_body": True}] * 2
            chunks.append({"type": "http.request", "body": b"a" * 400})
            scope = {"type": "http", "method": "POST", "path": "/x", "headers": [], "query_string": b"",
                     "root_path": "", "scheme": "http", "server": ("t", 80), "client": ("c", 1)}

            async def receive():
                return chunks.pop(0)

            async def send(message):
                sent.append(message)

            await _app(BodyLimit)(scope, receive, send)

        anyio.run(chunked)
        assert sent[0]["status"] == 413 and b"1,000 bytes" in sent[1]["body"] and len(sent) == 2
    finally:
        get_settings.cache_clear()


def test_security_headers_on_every_response_and_hsts_only_over_https():
    plain = TestClient(_app(SecurityHeaders)).get("/web/")
    assert plain.headers["content-security-policy"] == CSP and "frame-ancestors 'none'" in CSP
    assert plain.headers["x-content-type-options"] == "nosniff" and plain.headers["referrer-policy"] == "no-referrer"
    assert plain.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert "strict-transport-security" not in plain.headers
    tls = TestClient(_app(SecurityHeaders), base_url="https://testserver").get("/x")
    assert tls.json()["https"] and tls.headers["strict-transport-security"] == "max-age=31536000"
    assert "content-security-policy" not in TestClient(_app(SecurityHeaders)).get("/docs").headers


def test_a_public_paid_deployment_without_a_daily_cap_or_run_limit_warns_at_startup(monkeypatch, caplog):
    def settings(**kv):
        return Settings(_env_file=None, **kv)

    public = {"allowed_hosts": "brain.example.com", "llm_provider": "anthropic", "anthropic_api_key": "k"}
    text = exposure_warning(settings(**public))
    assert "brain.example.com" in text and "LLM_DAILY_TOKEN_CAP and RUNS_PER_HOUR = 0" in text
    assert "RUNS_PER_HOUR = 0" in exposure_warning(settings(**public, llm_daily_token_cap=2_000_000))
    assert exposure_warning(settings(**public, llm_daily_token_cap=2_000_000, runs_per_hour=6)) is None
    assert exposure_warning(settings(**{**public, "allowed_hosts": ""})) is None  # local only
    assert exposure_warning(settings(**{**public, "llm_provider": "mock"})) is None  # the rules planner costs nothing
    assert exposure_warning(settings(render_external_hostname="x.onrender.com", llm_provider="gemini",
                                     gemini_api_key="k")).startswith("public on x.onrender.com with the gemini")

    from oncall_brain.api import app as app_module

    monkeypatch.setattr(app_module, "exposure_warning", lambda: "public on brain.example.com ...")
    with caplog.at_level(logging.WARNING), TestClient(app_module.app):
        pass
    assert [r.getMessage() for r in caplog.records if r.name == app_module.log.name] == [
        "public on brain.example.com ..."]
