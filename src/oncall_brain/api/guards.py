"""HTTP guards shared by the API (api/app.py), MCP over HTTP (mcp_server/__main__.py) and the deployment app
(serve.py): a request body cap, per-client throttles (services/limits.py), same-origin writes and security headers.
Plain ASGI middleware, so streamed responses (the NDJSON run stream, MCP's event stream) pass through untouched."""

import logging
from collections.abc import Callable
from urllib.parse import urlsplit

from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders, QueryParams
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from oncall_brain.config import get_settings
from oncall_brain.ports import GraphStore
from oncall_brain.services.limits import Throttled, client_key, throttle

log = logging.getLogger(__name__)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
HEADERS = {"content-security-policy": CSP, "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
           "permissions-policy": "camera=(), microphone=(), geolocation=()"}
NO_CSP = ("/docs", "/redoc")  # FastAPI's API explorer pages load Swagger UI from a CDN with an inline script


class SecurityHeaders:
    """The headers above on every response (kept if the app set its own), plus HSTS when the request came over https:
    uvicorn sets the scheme from X-Forwarded-Proto for a proxy in FORWARDED_ALLOW_IPS."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        extra = {k: v for k, v in HEADERS.items() if not (k == "content-security-policy" and scope["path"] in NO_CSP)}
        if scope.get("scheme") == "https":
            extra["strict-transport-security"] = "max-age=31536000"
        if scope["path"].startswith("/web/"):  # the UI has no build step or hashed names: revalidate on every load
            extra["cache-control"] = "no-cache"  # (a 304 when unchanged), so a redeploy never mixes old JS with new

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in extra.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class SameOrigin:
    """403 for a write whose Origin names another site (CSRF): any web page can make a visitor's browser fire a
    body-less POST at us, and the browser then sends its own Origin. host:port only (no scheme), so a TLS-terminating
    proxy in front still matches. It sits in front of the throttles, so such a page cannot spend the visitor's quotas
    either."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if origin is not None and urlsplit(origin).netloc.lower() != headers.get("host", "").lower():
                return await JSONResponse({"detail": "cross-origin request refused"}, status_code=403)(
                    scope, receive, send)
        await self.app(scope, receive, send)


class _TooLarge(Exception):
    pass


class BodyLimit:
    """413 for a body over MAX_BODY_BYTES on every path of the app it wraps, before the app reads it: by Content-Length
    up front, and for a chunked body by counting it as it arrives (the app's read fails at the first chunk past the
    cap, and whatever it would answer is replaced by the 413)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        cap = get_settings().max_body_bytes
        if scope["type"] != "http" or not cap:
            return await self.app(scope, receive, send)
        refuse = JSONResponse({"detail": f"request body too large: the limit is {cap:,} bytes"}, status_code=413)
        length = Headers(scope=scope).get("content-length", "")
        if length.isdigit() and int(length) > cap:
            return await refuse(scope, receive, send)
        seen, over, started = 0, False, False

        async def counted() -> Message:
            nonlocal seen, over
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > cap:
                    over = True
                    raise _TooLarge
            return message

        async def send_unless_over(message: Message) -> None:
            nonlocal started
            if over:
                return
            started = True
            await send(message)

        try:
            await self.app(scope, counted, send_unless_over)
        except Exception:  # the app may re-raise our _TooLarge or wrap it (FastAPI turns it into a 400)
            if not over:
                raise
        if over and not started:
            await refuse(scope, receive, send)


# Bucket -> the setting that limits it (services/limits.py WINDOWS has the window for each).
LIMITS = {"req": "rate_limit_per_min", "write": "writes_per_min", "run": "runs_per_hour"}
Buckets = Callable[[str, str, QueryParams], list[str]]  # (method, path, query) -> the buckets a request counts in


class Throttle:
    """429 with Retry-After once a client is past a limit (services/limits.throttle). The client is the ASGI client
    address (an IPv6 one by its /64, limits.client_key): uvicorn replaces it with an X-Forwarded-For address only when
    the connection comes from a proxy in FORWARDED_ALLOW_IPS, so a header a client sends itself changes nothing.
    Nothing is counted (FalkorDB is not touched) while every limit is 0."""

    def __init__(self, app: ASGIApp, store: Callable[[], GraphStore], buckets: Buckets):
        self.app, self.store, self.buckets = app, store, buckets

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            s = get_settings()
            hits = [(b, getattr(s, LIMITS[b])) for b in
                    self.buckets(scope["method"], scope["path"], QueryParams(scope["query_string"]))]
            hits = [(bucket, limit) for bucket, limit in hits if limit]
            if hits:
                client = client_key((scope.get("client") or ("unknown",))[0])
                try:
                    await run_in_threadpool(self._count, client, hits)  # a Redis round trip; keep it off the loop
                except Throttled as e:
                    return await JSONResponse({"detail": str(e)}, status_code=429,
                                              headers={"Retry-After": str(e.retry_after)})(scope, receive, send)
        await self.app(scope, receive, send)

    def _count(self, client: str, hits: list[tuple[str, int]]) -> None:
        try:
            store = self.store()
            for bucket, limit in hits:
                throttle(store, bucket, client, limit)
        except RedisError as e:  # fail open: with FalkorDB down every throttled route answers 503 by itself
            log.warning("throttles skipped, FalkorDB unavailable: %s", e)
