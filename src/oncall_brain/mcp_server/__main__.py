"""python -m oncall_brain.mcp_server            serve MCP over stdio (Claude Desktop / Claude Code / Inspector)
python -m oncall_brain.mcp_server --http     serve Streamable HTTP at http://127.0.0.1:8001/mcp"""

import argparse

import anyio
from mcp.server.stdio import stdio_server

from oncall_brain.mcp_server import build_server


async def _stdio() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


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

    # host is passed to the app too: on localhost the SDK turns on DNS-rebinding protection.
    uvicorn.run(build_server().streamable_http_app(host=a.host), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
