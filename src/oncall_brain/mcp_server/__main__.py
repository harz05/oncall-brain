"""python -m oncall_brain.mcp_server            serve MCP over stdio (Claude Desktop / Claude Code / Inspector)
python -m oncall_brain.mcp_server --http     serve Streamable HTTP at http://127.0.0.1:8001/mcp"""

import argparse
import secrets
from functools import lru_cache

import anyio
from mcp.server.stdio import stdio_server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from oncall_brain import wiring
from oncall_brain.api.guards import BodyLimit, Throttle
from oncall_brain.config import get_settings
from oncall_brain.mcp_server import build_server


async def _stdio() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


class BearerToken(BaseHTTPMiddleware):
    """When a token is set (MCP_TOKEN, else API_TOKEN, so one token can guard the HTTP API and MCP), every request
    to the remote MCP endpoint needs "Authorization: Bearer <token>": a server exposed for Claude Code, Claude
    Desktop or claude.ai is not open to the world. With required=True (a deployment, oncall_brain.serve) the
    endpoint answers 401 until a token is configured, so a public /mcp is never open by mistake."""

    def __init__(self, app, required: bool = False):
        super().__init__(app)
        self.required = required

    async def dispatch(self, request, call_next):
        token = get_settings().mcp_bearer()
        if self.required and not token:
            return JSONResponse({"error": "MCP_TOKEN is not set; a deployment serves /mcp only with a bearer token"},
                                status_code=401, headers={"WWW-Authenticate": "Bearer"})
        if token:
            sent = request.headers.get("authorization", "").encode("latin-1")
            if sent.strip() in (b"", b"Bearer"):  # the plugin sends "Bearer " when ONCALL_BRAIN_TOKEN is unset
                return JSONResponse({"error": "no bearer token sent: set ONCALL_BRAIN_TOKEN (the plugin) or the "
                                     "Authorization header to this server's MCP_TOKEN"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            scheme, _, cred = sent.partition(b" ")
            if scheme.lower() != b"bearer" or not secrets.compare_digest(cred.strip(), token.encode()):
                return JSONResponse({"error": "wrong API token (it must equal this server's MCP_TOKEN)"},
                                    status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return await call_next(request)


class AcceptTrailingSlash:
    """`/mcp/` is `/mcp`: some MCP clients normalise the endpoint to a trailing slash, and the SDK app's answer to
    that (a redirect) is not followed on a POST. Rewrites the path before routing."""

    def __init__(self, app, path: str = "/mcp"):
        self.app, self.path = app, path

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == self.path + "/":
            scope = {**scope, "path": self.path, "raw_path": self.path.encode()}
        await self.app(scope, receive, send)


def http_app(host: str, require_token: bool = False) -> Starlette:
    """DNS-rebinding protection on any bind address: the SDK only turns it on for a localhost bind, but the docker
    service binds 0.0.0.0. Host and Origin must name ALLOWED_HOSTS (plus the local defaults and the hostname Render
    or Railway set); "*" turns it off. MCP_TOKEN (else API_TOKEN), when set, is required as a bearer token; with
    require_token the endpoint is not served at all without one (BearerToken). Every request counts against
    RATE_LIMIT_PER_MIN for its client and its body against MAX_BODY_BYTES (api/guards.py), checked before the token,
    so guessing tokens is throttled too; write tools also count against WRITES_PER_MIN, and respond_to_alert and
    reset_tenant against RUNS_PER_HOUR."""
    names = [p for h in get_settings().hosts() for p in (h, f"{h}:*")]
    security = TransportSecuritySettings(enable_dns_rebinding_protection="*" not in names, allowed_hosts=names,
                                         allowed_origins=[f"{s}://{n}" for s in ("http", "https") for n in names])
    app = build_server().streamable_http_app(host=host, transport_security=security)
    app.add_middleware(BearerToken, required=require_token)
    app.add_middleware(BodyLimit)
    app.add_middleware(Throttle, store=lru_cache(wiring.make_store), buckets=lambda method, path, query: ["req"])
    app.add_middleware(AcceptTrailingSlash)
    return app


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m oncall_brain.mcp_server", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8001)
    a = p.parse_args()
    if not a.http:
        anyio.run(_stdio)
        return
    import uvicorn

    uvicorn.run(http_app(a.host), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
