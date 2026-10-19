"""Abuse limits for a public deployment: per-client throttles, a cap on concurrent agent runs, and a daily LLM budget
every process shares (with an optional hourly slice). The surfaces (api/guards.py, mcp_server) read the settings and
pass the numbers in; 0 = off."""

import ipaddress
import math
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from oncall_brain.ports import GraphStore

# bucket -> (window in seconds, what the refusal calls the requests, the window's name)
WINDOWS = {"req": (60, "requests", "minute"), "write": (60, "writes", "minute"), "run": (3600, "agent runs", "hour")}
RL_PREFIX = "oncall_brain:rl:"
DAILY_PREFIX = "oncall_brain:llm_tokens:"


class Throttled(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class RunsBusy(Exception):
    pass


def _wait(seconds: int) -> str:
    return f"{seconds} second{'s' * (seconds != 1)}" if seconds < 90 else f"{math.ceil(seconds / 60)} minutes"


def client_key(host: str) -> str:
    """Whose bucket an address counts in: an IPv6 client by its /64 (one subscriber usually holds a whole /64, so per
    address it would have endless fresh buckets), an IPv4-mapped IPv6 address as its IPv4 one, anything else as is."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:  # "unknown", a test client's name
        return host
    if ip.version == 6 and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ipaddress.ip_network(f"{host}/64", strict=False)) if ip.version == 6 else host


def throttle(counters: GraphStore, bucket: str, client: str, limit: int, now: float | None = None) -> None:
    """Count one hit for `client` in `bucket` and raise Throttled past `limit` per window. Fixed windows
    (`oncall_brain:rl:<bucket>:<client>:<window number>`): a client can burst up to 2x the limit across a window
    edge, which is fine for keeping a demo affordable."""
    if not limit:
        return
    period, what, unit = WINDOWS[bucket]
    now = time.time() if now is None else now
    window = int(now // period)
    if counters.incr(f"{RL_PREFIX}{bucket}:{client}:{window}", ttl=period) > limit:
        retry = max(1, math.ceil((window + 1) * period - now))
        raise Throttled(f"Too many {what} from your address: {limit} per {unit}. Try again in {_wait(retry)}.", retry)


_running = 0
_running_lock = threading.Lock()


@contextmanager
def run_slot(limit: int) -> Iterator[None]:
    """At most `limit` agent runs at once (0 = no limit). A run past it is refused at once, not queued: a queued run
    would hold an HTTP request open for minutes."""
    # limit: per process. Several app replicas each allow `limit`; a Redis counter would make it global.
    global _running
    with _running_lock:
        if limit and _running >= limit:
            raise RunsBusy(f"{_running} agent run{'s are' if _running != 1 else ' is'} already in progress; "
                           "try again in a minute")
        _running += 1
    try:
        yield
    finally:
        with _running_lock:
            _running -= 1


class DailyBudget:
    """LLM tokens spent today (UTC) by every process on this FalkorDB, in one counter (`oncall_brain:llm_tokens:
    <yyyy-mm-dd>`, kept 2 days), and with `hourly` set also this hour's (`...:<yyyy-mm-ddThh>`, kept 2 hours), so a
    few clients cannot spend the whole day in one hour. RunBudget adds each decision's usage and asks `spent()`
    before the next one. cap 0 counts without limiting (so /api/health still shows the spend)."""

    def __init__(self, counters: GraphStore, cap: int, hourly: int = 0):
        self.counters, self.cap, self.hourly = counters, cap, hourly

    @staticmethod
    def key() -> str:
        return f"{DAILY_PREFIX}{datetime.now(UTC):%Y-%m-%d}"

    @staticmethod
    def hour_key() -> str:
        return f"{DAILY_PREFIX}{datetime.now(UTC):%Y-%m-%dT%H}"

    def used_today(self) -> int:
        return self.counters.counter(self.key())

    def used_this_hour(self) -> int:
        return self.counters.counter(self.hour_key())

    def spent(self) -> str | None:
        """Why the model may not decide now (the trace's words), or None."""
        # limit: checked before each decision, so runs in flight at a cap overshoot by one decision each.
        if self.cap and self.used_today() >= self.cap:
            return f"today's LLM budget ({self.cap:,} tokens) is spent; the rules planner decides until 00:00 UTC."
        if self.hourly and self.used_this_hour() >= self.hourly:
            nxt = (datetime.now(UTC).hour + 1) % 24
            return (f"this hour's share of the LLM budget ({self.hourly:,} tokens) is spent; the rules planner decides "
                    f"until {nxt:02d}:00 UTC.")
        return None

    def spend(self, tokens: int) -> None:
        if tokens:
            self.counters.incr(self.key(), ttl=2 * 86_400, by=tokens)
            if self.hourly:
                self.counters.incr(self.hour_key(), ttl=2 * 3600, by=tokens)
