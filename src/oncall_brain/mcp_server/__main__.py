"""python -m oncall_brain.mcp_server            serve MCP over stdio (Claude Desktop / Claude Code / Inspector)
python -m oncall_brain.mcp_server --http     serve Streamable HTTP at http://127.0.0.1:8001/mcp"""

import argparse

import anyio
from mcp.server.stdio import stdio_server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from oncall_brain.config import get_settings
from oncall_brain.mcp_server import build_server


async def _stdio() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def http_app(host: str) -> Starlette:
    """DNS-rebinding protection on any bind address: the SDK only turns it on for a localhost bind, but the docker
    service binds 0.0.0.0. Host and Origin must name ALLOWED_HOSTS (plus the local defaults); "*" turns it off."""
    names = [p for h in get_settings().hosts() for p in (h, f"{h}:*")]
    security = TransportSecuritySettings(enable_dns_rebinding_protection="*" not in names, allowed_hosts=names,
                                         allowed_origins=[f"{s}://{n}" for s in ("http", "https") for n in names])
    return build_server().streamable_http_app(host=host, transport_security=security)


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
