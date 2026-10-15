"""python -m oncall_brain.mcp_server            serve MCP over stdio (Claude Desktop / Claude Code / Inspector)
python -m oncall_brain.mcp_server --http     serve Streamable HTTP at http://127.0.0.1:8001/mcp"""

import argparse
import secrets

import anyio
from mcp.server.stdio import stdio_server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from oncall_brain.config import get_settings
from oncall_brain.mcp_server import build_server


async def _stdio() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


class BearerToken(BaseHTTPMiddleware):
    """When API_TOKEN is set, every request to the remote MCP endpoint needs "Authorization: Bearer <token>"
    (the same token the HTTP API uses), so a server exposed for Claude Desktop / claude.ai is not open to the world."""

    async def dispatch(self, request, call_next):
        token = get_settings().api_token
        if token:
            sent = request.headers.get("authorization", "").encode("latin-1")
            if not secrets.compare_digest(sent, f"Bearer {token}".encode()):
                return JSONResponse({"error": "missing or wrong API token"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
        return await call_next(request)


def http_app(host: str) -> Starlette:
    """DNS-rebinding protection on any bind address: the SDK only turns it on for a localhost bind, but the docker
    service binds 0.0.0.0. Host and Origin must name ALLOWED_HOSTS (plus the local defaults); "*" turns it off.
    API_TOKEN, when set, is required as a bearer token (BearerToken)."""
    names = [p for h in get_settings().hosts() for p in (h, f"{h}:*")]
    security = TransportSecuritySettings(enable_dns_rebinding_protection="*" not in names, allowed_hosts=names,
                                         allowed_origins=[f"{s}://{n}" for s in ("http", "https") for n in names])
    app = build_server().streamable_http_app(host=host, transport_security=security)
    app.add_middleware(BearerToken)
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
