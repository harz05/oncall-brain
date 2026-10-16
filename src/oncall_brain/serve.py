"""One ASGI app for a deployment: the web UI and HTTP API at /, the MCP server over Streamable HTTP at /mcp, and
/health. The Dockerfile runs it (`make serve` locally): uvicorn oncall_brain.serve:app --host 0.0.0.0 --port $PORT.

/mcp answers only with a bearer token (MCP_TOKEN, else API_TOKEN): a public MCP endpoint can write to every tenant.
/api/* keeps its own rule (open unless API_TOKEN is set, which the bundled UI cannot send), so a demo deployment sets
MCP_TOKEN alone and serves the UI, the API and a guarded MCP endpoint from one URL. Host and Origin are checked
against ALLOWED_HOSTS plus the hostname Render or Railway set, on both halves."""

from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from oncall_brain.api.app import app as api
from oncall_brain.api.app import health as api_health
from oncall_brain.config import get_settings
from oncall_brain.mcp_server.__main__ import http_app


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
    body: dict[str, Any] = {**api_health(), "mcp": mcp_state}
    return JSONResponse(body)


@asynccontextmanager
async def lifespan(_: Starlette):
    # Starlette runs only the outer app's startup, so the two inner ones (FastAPI's, the MCP session manager) run here.
    mcp.app = http_app("0.0.0.0", require_token=True)
    async with api.router.lifespan_context(api), mcp.app.router.lifespan_context(mcp.app):
        yield


# Route("/mcp", <ASGI app>) keeps the exact path; a Mount would answer POST /mcp with a redirect to /mcp/, which MCP
# clients do not follow. The API is mounted last and takes everything else (the UI at /web/, / redirects there).
app = Starlette(routes=[Route("/health", health), Route("/mcp", mcp), Mount("/", app=api)], lifespan=lifespan)
