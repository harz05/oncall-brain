"""One ASGI app for a deployment: the web UI and HTTP API at /, the MCP server over Streamable HTTP at /mcp, and
/health. The Dockerfile runs it (`make serve` locally): uvicorn oncall_brain.serve:app --host 0.0.0.0 --port $PORT.

/mcp answers only with a bearer token (MCP_TOKEN, else API_TOKEN): a public MCP endpoint can write to every tenant.
/api/* keeps its own rule (open unless API_TOKEN is set, which the bundled UI cannot send), so a demo deployment sets
MCP_TOKEN alone and serves the UI, the API and a guarded MCP endpoint from one URL. Plainly: with MCP_TOKEN alone,
anyone who can reach the URL can drive the demo (simulate, confirm, reset, every write tool) through the UI's API;
set API_TOKEN too for a deployment that is MCP-only. Host and Origin are checked
against ALLOWED_HOSTS plus the hostname Render or Railway set, on both halves. What anyone can spend is capped by the
limits in services/limits.py (per-client throttles, concurrent runs, the daily LLM budget; the public preset in
.env.example), and every response carries the security headers (api/guards.py)."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from oncall_brain.adapters.falkordb.repository import FalkorGraphStore
from oncall_brain.api.app import app as api
from oncall_brain.api.app import health_body, store
from oncall_brain.api.guards import SecurityHeaders
from oncall_brain.config import get_settings
from oncall_brain.mcp_server.__main__ import http_app
from oncall_brain.services.seeding import reset

log = logging.getLogger(__name__)
TEND_EVERY = 60  # seconds


class _McpHalf:
    """The MCP server app, built at every startup: the SDK's session manager runs once per instance, and a process
    that restarts its app (tests, a reload) needs a fresh one."""

    def __init__(self) -> None:
        self.app: Starlette | None = None

    async def __call__(self, scope, receive, send) -> None:
        assert self.app is not None, "startup has not run"
        await self.app(scope, receive, send)


mcp = _McpHalf()


def health(_: Request) -> JSONResponse:
    """/api/health plus the MCP endpoint's state: what the platform's health check (render.yaml) and a human read.
    Answers on any Host (a platform's checker may not send the public name); it reveals no data and changes nothing.
    The API and MCP halves keep their Host and Origin checks."""
    mcp_state = "/mcp" if get_settings().mcp_bearer() else "off: MCP_TOKEN is not set"
    body: dict[str, Any] = {**health_body(), "mcp": mcp_state}
    return JSONResponse(body, status_code=200 if body["ok"] else 503)


def tend(s: FalkorGraphStore, tenant: str) -> None:
    """FalkorDB Cloud Free stops an instance nobody used for a day and keeps nothing across a restart (no
    persistence). So once a minute: real graph queries keep it in use, and what a restart lost comes back: the
    coordination graph's constraints (Coordination.recheck), then the demo company (reset seeds it when no pristine
    copy survived). The UDF library reloads by itself on the first query that misses it (FalkorRepository._run)."""
    s.coord.recheck()
    if not s.exists(tenant):
        log.warning("tend: tenant %s is missing (a database restart?): %s", tenant, reset(s, tenant))


async def _tend_forever() -> None:
    while True:
        await asyncio.sleep(TEND_EVERY)
        try:
            await run_in_threadpool(tend, store(), get_settings().default_tenant)
        except Exception:  # the database may be down right now: say so, try again in a minute
            log.exception("tend failed")


@asynccontextmanager
async def lifespan(_: Starlette):
    # Starlette runs only the outer app's startup, so the two inner ones (FastAPI's, the MCP session manager) run here.
    mcp.app = http_app("0.0.0.0", require_token=True)
    async with api.router.lifespan_context(api), mcp.app.router.lifespan_context(mcp.app):
        task = asyncio.create_task(_tend_forever())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


# Route("/mcp", <ASGI app>) keeps the exact path; a Mount would answer POST /mcp with a redirect to /mcp/, which MCP
# clients do not follow. /mcp/ reaches the same half (it rewrites the path). The API is mounted last and takes
# everything else (the UI at /web/, / redirects there).
app = Starlette(routes=[Route("/health", health), Route("/mcp", mcp), Route("/mcp/", mcp), Mount("/", app=api)],
                middleware=[Middleware(SecurityHeaders)], lifespan=lifespan)
