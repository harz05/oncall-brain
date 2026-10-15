"""MCP surface of the tool registry. Every graph tool in agents.registry is exposed as-is (its docstring and
pydantic schema, plus a required `tenant`), next to two use cases: respond_to_alert and reset_tenant. Nothing
is defined twice: add a tool to the registry and it shows up here, in the agent loop and in the HTTP API."""

from collections.abc import Callable
from functools import lru_cache
from typing import Any

import anyio
from mcp import types
from mcp.server import Server
from pydantic import BaseModel
from pydantic_core import to_json

from oncall_brain import wiring
from oncall_brain.agents import registry
from oncall_brain.agents.registry import ToolContext
from oncall_brain.config import get_settings
from oncall_brain.ports import GraphRepository, GraphStore
from oncall_brain.services import respond, seeding
from oncall_brain.services.tools import AlertArgs

TENANT = {"type": "string", "pattern": "^[a-z0-9_]{1,40}$",
          "description": "Tenant graph to work in (one isolated FalkorDB graph per tenant), e.g. acme"}

# A handler gets (store, tenant, args) and returns something JSON-serialisable.
Handler = Callable[[GraphStore, str, dict[str, Any]], Any]


class _NoArgs(BaseModel):
    pass


def _repo(store: GraphStore, tenant: str) -> GraphRepository:
    if not store.exists(tenant):  # otherwise FalkorDB answers a cryptic "empty key" error
        raise ValueError(f"tenant {tenant!r} has no graph yet; call reset_tenant first")
    return store.tenant(tenant)


def _registry_handler(name: str) -> Handler:
    def run(store: GraphStore, tenant: str, args: dict[str, Any]) -> dict[str, Any]:
        out = registry.call(name, ToolContext(_repo(store, tenant)), args)
        return {"summary": out.summary, "data": out.data,
                "queries": [{"name": q.name, "readonly": q.readonly, "rows": q.row_count, "ms": q.ms,
                             "cypher": q.cypher} for q in out.queries]}

    return run


def _respond(store: GraphStore, tenant: str, args: dict[str, Any]) -> dict[str, Any]:
    run = respond.respond(_repo(store, tenant), AlertArgs.model_validate(args).alert_id, _llm())
    return {"incident_id": run["incident_id"], "planner": run["planner"],
            "outcome": run["outcome"],
            "steps": [{"seq": s.seq, "role": s.role, "tool": s.tool, "summary": s.summary, "reason": s.reason}
                      for s in run["steps"]]}


def _reset(store: GraphStore, tenant: str, args: dict[str, Any]) -> dict[str, Any]:
    known, cap = store.tenants(), get_settings().max_tenants  # same soft cap as the HTTP API
    if tenant not in known and len(known) >= cap:
        raise ValueError(f"tenant limit reached ({cap}); reset an existing tenant or raise MAX_TENANTS")
    return {"tenant": tenant, "graph": seeding.reset(store, tenant)}


@lru_cache
def _llm():
    return wiring.make_llm()


USE_CASES: dict[str, tuple[str, type[BaseModel], bool, Handler]] = {
    "respond_to_alert": ("Run the triage -> investigator -> comms agents on an alert (e.g. alert:checkout-latency). "
                         "They hand off through the graph; returns the incident id, the outcome (root cause, "
                         "refuted suspects, who was paged, status update) and every step.", AlertArgs, True, _respond),
    "reset_tenant": ("Restore the tenant's pristine seeded graph (GRAPH.COPY), seeding it first if it has none. "
                     "Wipes incidents, memory and runbooks learned since.", _NoArgs, True, _reset),
}


def catalogue() -> dict[str, tuple[types.Tool, Handler]]:
    """Every MCP tool with its handler: the registry's tools, then the use cases."""
    entries = [(t.name, t.description, t.args_model, t.writes, _registry_handler(t.name))
               for t in registry.REGISTRY.values()]
    entries += [(name, *spec) for name, spec in USE_CASES.items()]
    out = {}
    for name, description, model, writes, handler in entries:
        schema = model.model_json_schema()
        schema["properties"] = {"tenant": TENANT, **schema.get("properties", {})}
        schema["required"] = ["tenant", *schema.get("required", [])]
        tool = types.Tool(name=name, description=description, input_schema=schema,
                          annotations=types.ToolAnnotations(read_only_hint=not writes))
        out[name] = (tool, handler)
    return out


def _text(payload: Any, error: bool = False) -> types.CallToolResult:
    text = payload if isinstance(payload, str) else to_json(payload, fallback=str).decode()
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)


def build_server(store: GraphStore | None = None) -> Server:
    """The store is connected on first call, so the server starts and lists tools with FalkorDB down."""
    tools = catalogue()
    get_store = (lambda: store) if store is not None else lru_cache(wiring.make_store)

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[t for t, _ in tools.values()])

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name not in tools:
            return _text(f"unknown tool {params.name!r}", error=True)
        args = dict(params.arguments or {})
        tenant = str(args.pop("tenant", ""))  # validated by the store: one graph per tenant
        try:  # graph calls block; keep them off the event loop
            return _text(await anyio.to_thread.run_sync(tools[params.name][1], get_store(), tenant, args))
        except Exception as e:  # report to the client as a tool error instead of killing the session
            return _text(f"{type(e).__name__}: {e}", error=True)

    return Server("oncall-brain", version="0.1.0", on_list_tools=list_tools, on_call_tool=call_tool,
                  instructions="Incident agents over a FalkorDB knowledge graph. Start with reset_tenant, then "
                               "respond_to_alert (alert:checkout-latency, then alert:refunds-latency), or call the "
                               "graph tools (blast_radius, dependency_path, service_map, ...) directly.")
