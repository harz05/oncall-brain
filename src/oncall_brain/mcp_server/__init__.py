"""MCP surface of the tool registry: the primary interface of On-call Brain for outside agents (Claude Code, Claude
Desktop, any MCP client). Every graph tool in agents.registry is exposed as-is (its docstring and pydantic schema,
plus a required `tenant`), next to two use cases: respond_to_alert and reset_tenant, and two prompts for the two
workflows (work an alert, answer a company question). Nothing is defined twice: add a tool to the registry and it
shows up here, in the agent loop and in the HTTP API."""

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import anyio
from mcp import types
from mcp.server import Server
from pydantic import BaseModel
from pydantic_core import to_json
from redis.exceptions import LockError

from oncall_brain import wiring
from oncall_brain.agents import registry
from oncall_brain.config import get_settings
from oncall_brain.ports import GraphRepository, GraphStore
from oncall_brain.services import respond, seeding, sessions
from oncall_brain.services.limits import DailyBudget, RunsBusy, Throttled, client_key, throttle
from oncall_brain.services.tools import AlertArgs

TENANT = {"type": "string", "pattern": "^[a-z0-9_]{1,40}$",
          "description": "The company to work in: one isolated FalkorDB graph per tenant, e.g. acme (the demo company)"}

INSTRUCTIONS = """On-call Brain: incident agents and a company brain over one FalkorDB graph per company (tenant).
Three ways to use it:
1. An alert fired: respond_to_alert(tenant, alert_id) runs triage -> investigator -> comms on the graph and returns
   the likely cause with a confidence label, who was paged, the suspects ruled out and why, the fix (runbook) and
   the status update. When a human confirms the cause, call resolve_incident(tenant, incident_id, change_id) so the
   fix becomes memory for the next incident. raise_alert records a new alert first if it is not in the graph yet.
2. A question about the company: ask(tenant, question) answers "who owns kafka", "why was legacy-billing retired",
   "how do I roll back a bad deploy on cart", "what happened to auth", "what is the Q4 cost review changing and who
   is on it" with sources. who_knows ranks the people who know a service; change_story traces a change to its
   ticket, chat, docs and author; dependency_path, blast_radius
   and service_map answer structural questions. Pass user (a Person id such as person:hana-costa) and keep one
   session key through a conversation: each question is then remembered in the graph, a follow-up can say "it" or
   "them", and my_questions(tenant, user) or asking "what did I ask about payments-gw" recalls them with sources.
3. Keeping the graph current: record_change (deploys, config changes), record_anomaly, raise_alert, add_dependency,
   retire_dependency, record_doc (a new decision record, with the doc it supersedes) and transfer_ownership (a team
   takes over a service; the old owner's OWNS edge is closed, never deleted) write live facts; the next investigation
   and the next question see them, and "who owned X at the time of inc:0911" still names the owner back then.
Ids look like svc:checkout, alert:checkout-latency, inc:checkout-latency, chg:pgw-pool-1, person:sana-brandt. Every
result includes the Cypher it ran. If a tenant has no graph yet, reset_tenant(tenant) seeds the demo company."""

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
        if sessions.reserved(args.get("user")):
            raise ValueError(sessions.RESERVED)
        out = respond.run_tool(_repo(store, tenant), name, args)
        return {"summary": out.summary, "data": out.data,
                "queries": [{"name": q.name, "readonly": q.readonly, "rows": q.row_count, "ms": q.ms,
                             "cypher": q.cypher} for q in out.queries]}

    return run


def _respond(store: GraphStore, tenant: str, args: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    run = respond.respond(_repo(store, tenant), AlertArgs.model_validate(args).alert_id, _llm(),
                          max_runs=s.max_concurrent_runs,
                          daily=DailyBudget(store, s.llm_daily_token_cap, s.llm_hourly_token_cap))
    return {"incident_id": run["incident_id"], "planner": run["planner"], "llm_tokens": run.get("llm_tokens", 0),
            "outcome": run["outcome"],
            "steps": [{"seq": s.seq, "role": s.role, "tool": s.tool, "by": s.by, "summary": s.summary,
                       "reason": s.reason} for s in run["steps"]]}


def _reset(store: GraphStore, tenant: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"tenant": tenant, "graph": seeding.reset(store, tenant, max_tenants=get_settings().max_tenants)}


@lru_cache
def _llm():
    return wiring.make_llm()


RUNS = {"respond_to_alert", "reset_tenant"}  # count against RUNS_PER_HOUR per client, as the API's respond and reset do


def _client(ctx: Any) -> str | None:
    """The caller's throttle key over HTTP (limits.client_key of its address: the transport attaches the request,
    uvicorn has applied trusted proxy headers); None over stdio, which is a local process."""
    request = getattr(ctx, "request", None)
    client = getattr(request, "client", None)
    return client_key(client.host) if client else None


USE_CASES: dict[str, tuple[str, type[BaseModel], bool, Handler]] = {
    "respond_to_alert": ("Work an alert end to end: run the triage -> investigator -> comms agents on it over the "
                         "graph. They hand off through the incident node and record every step. Returns the incident "
                         "id and the outcome: likely cause (change, service, author) with a confidence label, who was "
                         "paged, impact, the suspects ruled out and why, the fix (runbook) if memory has one, the "
                         "status update text, and every step with who decided it. Use this for 'X is slow/erroring, "
                         "find out why' when an alert id exists (raise_alert creates one).", AlertArgs, True, _respond),
    "reset_tenant": ("Restore the company's pristine seeded graph (GRAPH.COPY), seeding the demo company first if it "
                     "has none. Wipes incidents, memory, runbooks and conversation history learned since. Use "
                     "before a demo, never during "
                     "a real incident.", _NoArgs, True, _reset),
}

PROMPTS: dict[str, types.Prompt] = {
    "work_alert": types.Prompt(
        name="work_alert",
        description="Work an alert end to end: run the three agents on it and report what an on-call engineer "
                    "needs (cause, confidence, who is paged, the fix, what was ruled out), then offer to confirm.",
        arguments=[types.PromptArgument(name="tenant", description="Company graph, e.g. acme", required=True),
                   types.PromptArgument(name="alert_id", description="Alert id, e.g. alert:checkout-latency",
                                        required=True)]),
    "company_question": types.Prompt(
        name="company_question",
        description="Answer a question about the company from its graph (owners, on-call, decisions, past incidents, "
                    "runbooks), leading with the answer and citing the sources.",
        arguments=[types.PromptArgument(name="tenant", description="Company graph, e.g. acme", required=True),
                   types.PromptArgument(name="question", description="The question in plain words", required=True),
                   types.PromptArgument(name="user", description="Who is asking, e.g. person:hana-costa: the "
                                        "question is remembered in their session, so a follow-up can say 'it'"),
                   types.PromptArgument(name="session", description="Session key for this conversation (default: "
                                        "default)")]),
}


def prompt_text(name: str, args: dict[str, str]) -> str:
    """The user message a prompt expands to (also what the Claude Code skills send)."""
    tenant, a = args.get("tenant", "acme"), args
    if name == "work_alert":
        return (f"An alert fired on company '{tenant}': {a.get('alert_id', '')}. Call respond_to_alert with that "
                "tenant and alert_id. Then report, in plain words and in this order: (1) the likely cause: the "
                "change, the service it touched, who made it, and the confidence label with its reason; (2) who is "
                "paged; "
                "(3) the fix (runbook) if there is one; (4) what was ruled out and why, one line each; (5) the status "
                "update text as written. Use ids exactly as returned. End by asking whether the cause is right; if I "
                "say yes, call resolve_incident with the incident id and change id so the fix is remembered.")
    if name == "company_question":
        who = (f" and user={a['user']!r}, session={a.get('session') or 'default'!r} (the question is then remembered "
               "in that person's session, so a follow-up can say 'it', and 'what did I ask about X' works)"
               if a.get("user") else "")
        return (f"Answer this question about company '{tenant}' from its graph: {a.get('question', '')}. Call ask "
                f"with that tenant and question{who}. Lead with a one- or two-sentence answer, then list the "
                "sources it returned (kind and title). If the question is about who owns or knows a service, "
                "who_knows adds the ranking; if it is about why a change was made, change_story adds the ticket, "
                "chat and author.")
    raise ValueError(f"unknown prompt {name!r}")


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
                          annotations=types.ToolAnnotations(read_only_hint=not writes and name != "ask"))
        out[name] = (tool, handler)
    return out


def _text(payload: Any, error: bool = False) -> types.CallToolResult:
    text = payload if isinstance(payload, str) else to_json(payload, fallback=str).decode()
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)


log = logging.getLogger(__name__)


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
        (tool, handler), client = tools[params.name], _client(ctx)

        def run() -> Any:
            if client:  # the API's buckets: every write tool (Ask included) is a write, the use cases are also runs
                s = get_settings()
                if not tool.annotations.read_only_hint:
                    throttle(get_store(), "write", client, s.writes_per_min)
                if params.name in RUNS:
                    throttle(get_store(), "run", client, s.runs_per_hour)
            return handler(get_store(), tenant, args)

        try:  # graph calls block; keep them off the event loop
            return _text(await anyio.to_thread.run_sync(run))
        except (Throttled, RunsBusy) as e:  # a limit's own words, as the API answers them with 429
            return _text(str(e), error=True)
        except LockError:  # the database is fine; another run holds the tenant
            return _text(f"tenant {tenant!r} is busy: another agent run holds its lock (one run per tenant at a "
                         "time; a crashed holder frees it after 15 min). Retry shortly.", error=True)
        except Exception as e:  # the client gets a tool error instead of a dead session; the log gets the traceback
            log.exception("tool %s on tenant %s failed", params.name, tenant)
            return _text(f"{type(e).__name__}: {e}", error=True)

    async def list_prompts(ctx: Any, params: Any) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=list(PROMPTS.values()))

    async def get_prompt(ctx: Any, params: types.GetPromptRequestParams) -> types.GetPromptResult:
        if params.name not in PROMPTS:
            raise ValueError(f"unknown prompt {params.name!r}")
        text = prompt_text(params.name, {k: str(v) for k, v in (params.arguments or {}).items()})
        return types.GetPromptResult(description=PROMPTS[params.name].description, messages=[
            types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))])

    return Server("oncall-brain", version="0.2.0", on_list_tools=list_tools, on_call_tool=call_tool,
                  on_list_prompts=list_prompts, on_get_prompt=get_prompt, instructions=INSTRUCTIONS)
