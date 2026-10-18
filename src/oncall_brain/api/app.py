"""HTTP API: one of the three surfaces of the tool registry (with the agent loop and MCP).

Handlers stay thin: they pick the tenant's graph and call services / the registry. Errors map to
{"detail": str}: unknown things (ValueError from the services) -> 404, bad input -> 422, FalkorDB down or
erroring -> 503, misconfigured planner -> 503, tenant cap reached or agent runs busy -> 429.
Guards in front of every route: Host allow-list (DNS rebinding), same-origin writes (CSRF), per-client throttles and a
body cap (api/guards.py), optional API_TOKEN; security headers on every response.
Run: uvicorn oncall_brain.api.app:app --port 8000
"""

import json
import logging
import os
import queue
import re
import secrets
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path as FsPath
from typing import Annotated, Any, Literal

import anyio
from fastapi import Body, Depends, FastAPI, HTTPException, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import LockError, RedisError
from starlette.datastructures import QueryParams
from starlette.middleware.trustedhost import TrustedHostMiddleware

from oncall_brain.adapters import slack
from oncall_brain.adapters.falkordb.queries import all_queries
from oncall_brain.adapters.falkordb.repository import FalkorGraphStore
from oncall_brain.agents import registry
from oncall_brain.agents.registry import ToolContext
from oncall_brain.api.guards import BodyLimit, SameOrigin, SecurityHeaders, Throttle
from oncall_brain.config import get_settings
from oncall_brain.domain.models import cypher_sha
from oncall_brain.ports import GraphRepository, LLMProvider
from oncall_brain.services import respond as respond_svc
from oncall_brain.services import sessions
from oncall_brain.services.limits import DailyBudget, RunsBusy
from oncall_brain.services.seeding import TenantLimitReached, reset
from oncall_brain.services.tools import AlertEvent
from oncall_brain.wiring import exposure_warning

WEB_DIR = FsPath(os.environ.get("WEB_DIR") or FsPath(__file__).resolve().parents[3] / "web")

Tenant = Annotated[str, Path(pattern=r"^[a-z0-9_]{1,40}$")]

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    if warning := exposure_warning():  # once per server start: a public URL that can spend on a paid model
        log.warning(warning)
    # Sync routes run on anyio's worker threads (40 by default); a /respond holds one for its whole run and a write
    # waiting on a tenant lock holds one for up to LOCK_WAIT_SECONDS. With every thread taken even /health hangs, so
    # leave headroom.
    anyio.to_thread.current_default_thread_limiter().total_tokens = 100
    yield


app = FastAPI(title="On-call Brain", description="Incident agents over a FalkorDB knowledge graph.",
              lifespan=_lifespan)
# check_dir=False: the web/ folder may appear after the server starts.
# html=True serves web/index.html at /web/. Asset paths in the page are relative, so the same files also work as a
# static site (e.g. GitHub Pages with ?offline=1).
app.mount("/web", StaticFiles(directory=WEB_DIR, html=True, check_dir=False), name="web")


# Built on first use, not at import, so the app imports (and /api/health answers) with FalkorDB down.
# lru_cache does not cache exceptions, so a failed connect is retried on the next request.
@lru_cache
def store() -> FalkorGraphStore:
    from oncall_brain.wiring import make_store

    return make_store()


@lru_cache
def llm() -> LLMProvider:
    from oncall_brain.wiring import make_llm

    try:
        return make_llm()
    except ValueError as e:  # a bad LLM_PROVIDER is a server misconfiguration, not an unknown thing (404)
        raise HTTPException(503, f"planner misconfigured: {e}") from e


def _detail(errors: list[dict[str, Any]]) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errors)


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def _invalid(_: Request, e: RequestValidationError | ValidationError) -> JSONResponse:
    return JSONResponse({"detail": _detail(e.errors())}, status_code=422)


@app.exception_handler(ValueError)
async def _unknown(_: Request, e: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=404)


def _db_detail(e: RedisError) -> str:
    if isinstance(e, LockError):  # the database is fine; another run holds the tenant
        return ("another agent run holds this tenant's lock (one run per tenant at a time; a crashed holder frees it "
                "after 15 min): retry shortly")
    if isinstance(e, RedisConnectionError):  # also covers auth failures
        return f"FalkorDB unavailable: {e}"
    # Timeouts and ResponseError (e.g. "GRAPH.COPY failed, could not fork"). First line only, capped: FalkorDB
    # error texts can quote the whole query.
    return f"FalkorDB error ({type(e).__name__}): {(str(e).splitlines() or [''])[0][:160]}"


@app.exception_handler(RedisError)
async def _db_error(_: Request, e: RedisError) -> JSONResponse:
    return JSONResponse({"detail": _db_detail(e)}, status_code=409 if isinstance(e, LockError) else 503)


@app.exception_handler(RunsBusy)
async def _busy(_: Request, e: RunsBusy) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=429, headers={"Retry-After": "60"})


def _bearer_ok(request: Request, token: str) -> bool:
    sent = request.headers.get("authorization", "").encode("latin-1")  # Starlette decodes headers as latin-1
    scheme, _, cred = sent.partition(b" ")  # the scheme is case-insensitive (RFC 7235)
    return scheme.lower() == b"bearer" and secrets.compare_digest(cred.strip(), token.encode())


@app.middleware("http")
async def _guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    path = request.url.path  # cross-origin writes were refused before this (api/guards.py SameOrigin)
    token = get_settings().api_token
    if token and path.startswith("/api/") and path != "/api/health":
        if not _bearer_ok(request, token):
            return JSONResponse({"detail": "missing or wrong API token"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
    # FalkorDB refuses string parameters containing NUL; that is bad input (422), not a server error.
    if "\x00" in path or b"\\u0000" in await request.body():
        return JSONResponse({"detail": "NUL characters are not allowed"}, status_code=422)
    return await call_next(request)


_RUN = re.compile(r"/api/tenants/[^/]+/(alerts/[^/]+/respond(/stream)?|reset)")
_ALERTS = re.compile(r"/api/tenants/[^/]+/alerts")
_TRUE = {"1", "true", "t", "yes", "y", "on"}  # what FastAPI reads as respond=true


def throttle_buckets(method: str, path: str, query: QueryParams) -> list[str]:
    """The throttles a request counts against (api/guards.py Throttle): every /api/* call but health; writes (any
    non-GET: the webhook, and Ask, which records the question in the asker's session); agent runs (respond, its stream,
    the webhook with ?respond=true, reset). ?compare=memory is two runs: it replays the incident without memory."""
    if not path.startswith("/api/") or path == "/api/health":
        return []
    write = method not in ("GET", "HEAD", "OPTIONS")
    run = method == "POST" and bool(
        _RUN.fullmatch(path) or (_ALERTS.fullmatch(path) and query.get("respond", "").lower() in _TRUE))
    return ["req"] + ["write"] * write + ["run"] * run * (2 if query.get("compare") == "memory" else 1)


# The last one added runs first: headers on every answer, then Host (DNS rebinding: a hostile name resolving to
# 127.0.0.1 still sends its own Host header), then same-origin writes (so a refused one counts nowhere), then the
# throttles, then the body cap (on every path: _guard reads the body of any request), then _guard above.
app.add_middleware(BodyLimit)
app.add_middleware(Throttle, store=store, buckets=throttle_buckets)
app.add_middleware(SameOrigin)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_settings().hosts())
app.add_middleware(SecurityHeaders)


def tenant_repo(tenant: Tenant) -> GraphRepository:
    if not store().exists(tenant):
        raise HTTPException(404, f"unknown tenant {tenant!r}; POST /api/tenants/{tenant}/reset seeds it")
    return store().tenant(tenant)


Repo = Annotated[GraphRepository, Depends(tenant_repo)]


@app.get("/", include_in_schema=False)
def index(request: Request) -> RedirectResponse:
    if not (WEB_DIR / "index.html").is_file():
        raise HTTPException(404, f"no UI at {WEB_DIR / 'index.html'}")
    return RedirectResponse(f"/web/{'?' + request.url.query if request.url.query else ''}")


def _db_category(e: Exception) -> str:
    """A fixed description of why FalkorDB did not answer, safe for an unauthenticated response."""
    from redis.exceptions import AuthenticationError
    from redis.exceptions import TimeoutError as RedisTimeout

    if isinstance(e, AuthenticationError):
        return "authentication failed (check FALKORDB_PASSWORD or FALKORDB_URL)"
    if isinstance(e, RedisTimeout):
        return "timed out"
    if isinstance(e, RedisConnectionError):
        return "connection refused or unreachable (is FalkorDB running? make db)"
    if isinstance(e, ValueError):
        return "FALKORDB_URL is invalid (percent-encode / ? # @ : in the password)"
    return f"{type(e).__name__} (see the server log)"


def health_body() -> dict[str, Any]:
    """ok only when the planner is configured AND FalkorDB answers a ping; a platform health check reads the
    status (503 when not ok), a human reads falkordb_error."""
    try:
        up, db_error = bool(store().db.connection.ping()), None
        budget = daily_budget()
        used, hour = budget.used_today(), budget.used_this_hour()
    except Exception as e:  # health must answer; say what kind of failure, log the details (they can hold the URL)
        log.warning("health: FalkorDB check failed: %s", e)
        up, db_error, used, hour = False, _db_category(e), None, None
    try:
        planner, ok = llm().name, True
    except HTTPException as e:
        planner, ok = f"<error: {e.detail}>", False
    return {"ok": ok and up, "falkordb": up, "falkordb_error": db_error, "planner": planner,
            "default_tenant": get_settings().default_tenant, "slack": bool(get_settings().slack_webhook_url),
            "llm_budget": {"cap": get_settings().llm_daily_token_cap, "used_today": used,
                           "hourly_cap": get_settings().llm_hourly_token_cap, "used_this_hour": hour}}


@app.get("/api/health")
def health() -> JSONResponse:
    body = health_body()
    return JSONResponse(body, status_code=200 if body["ok"] else 503)


@app.get("/api/tenants")
def tenants() -> dict[str, Any]:
    return {"tenants": store().tenants(), "default": get_settings().default_tenant}


@app.post("/api/tenants/{tenant}/reset")
def reset_tenant(tenant: Tenant) -> dict[str, str]:
    try:
        return {"tenant": tenant, "status": reset(store(), tenant, max_tenants=get_settings().max_tenants)}
    except TenantLimitReached as e:
        raise HTTPException(429, str(e)) from None


@app.get("/api/tenants/{tenant}/alerts")
def alerts(repo: Repo) -> list[dict[str, Any]]:
    """Every alert, with the incident handling it (if any) and its status: the UI's incident inbox."""
    return repo.read("list_alerts").rows


@app.post("/api/tenants/{tenant}/alerts")
def new_alert(repo: Repo, body: AlertEvent, respond: bool = False) -> dict[str, Any]:
    """Alert webhook: record an alert on a service (the raise_alert tool). ?respond=true also runs the agents on it
    and returns the run, like POST .../alerts/{id}/respond."""
    out = respond_svc.run_tool(repo, "raise_alert", body.model_dump(exclude_none=True))
    return run_agents(repo, out.data["alert"]) if respond else out.data


def daily_budget() -> DailyBudget:
    return DailyBudget(store(), get_settings().llm_daily_token_cap, get_settings().llm_hourly_token_cap)


def run_agents(repo: GraphRepository, alert_id: str, on_step: Callable[[Any], None] | None = None,
               post: bool = True) -> dict[str, Any]:
    """post=False: the caller answers in Slack itself (/oncall incident), so the webhook does not post it twice."""
    run = respond_svc.respond(repo, alert_id, llm(), on_step, max_runs=get_settings().max_concurrent_runs,
                              daily=daily_budget())
    run["slack"] = slack.post(run["outcome"]["update_text"]) if post else "answered in Slack"
    return run


@app.post("/api/tenants/{tenant}/alerts/{alert_id}/respond")
def respond(repo: Repo, alert_id: str, compare: Literal["memory"] | None = None) -> dict[str, Any]:
    """?compare=memory also replays the same incident on a copy of the pristine graph (no learned memory) and
    returns its counters under "ablation" -- the fair before/after for memory."""
    run = run_agents(repo, alert_id)  # FastAPI serialises the TraceStep models inside
    if compare == "memory":
        run["ablation"] = {"without_memory": respond_svc.without_memory(store(), repo.tenant, alert_id, llm(),
                                                                        daily_budget())}
    return run


@app.post("/api/tenants/{tenant}/alerts/{alert_id}/respond/stream")
def respond_stream(repo: Repo, alert_id: str, compare: Literal["memory"] | None = None) -> StreamingResponse:
    """The same run, streamed while it happens as NDJSON: one {"step": ...} line per agent step as it is recorded,
    then {"result": ...} (the full run, as /respond returns it), then {"ablation": ...} if ?compare=memory, or
    {"error": "..."} if the run fails part way."""
    llm()  # a misconfigured planner is a 503 before the stream starts
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def work() -> None:
        try:
            run = run_agents(repo, alert_id, lambda s: events.put({"step": s}))
            events.put({"result": run})
            if compare == "memory":
                events.put({"ablation": {"without_memory": respond_svc.without_memory(
                    store(), repo.tenant, alert_id, llm(), daily_budget())}})
        except RedisError as e:
            events.put({"error": _db_detail(e)})
        except RunsBusy as e:  # MAX_CONCURRENT_RUNS: the stream has already answered 200, so the line says it
            events.put({"error": str(e)})
        except ValueError as e:  # an unknown alert: the message is the answer
            events.put({"error": str(e)})
        except Exception as e:  # anything else: the client gets the type, the server log gets the traceback
            log.exception("agent run for %s on tenant %s failed", alert_id, repo.tenant)
            events.put({"error": f"agent run failed ({type(e).__name__})"})
        finally:
            events.put(None)

    def lines() -> Iterator[str]:
        while (event := events.get()) is not None:
            yield json.dumps(jsonable_encoder(event)) + "\n"

    # The run finishes (and persists) even if the client goes away; it holds the tenant lock, like /respond.
    threading.Thread(target=work, daemon=True).start()
    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.get("/api/tenants/{tenant}/incidents/{incident_id}")
def incident(repo: Repo, incident_id: str) -> dict[str, Any]:
    """An incident as the graph has it: head (alert, service, status), its outcome (cause, confidence, pages,
    sources, update; counters are 0 without a live trace) and its persisted steps."""
    head = repo.read("incident_head", incident_id=incident_id).rows
    if not head:
        raise HTTPException(404, f"unknown incident {incident_id!r}")
    return {**head[0], "outcome": respond_svc.outcome(repo, incident_id, []), "steps": _stored_steps(repo, incident_id)}


def _stored_steps(repo: GraphRepository, incident_id: str) -> list[dict[str, Any]]:
    """The persisted AgentSteps, each with the queries it ran ({name, row_count, ms, readonly, params, sha}; the Cypher
    text is GET /api/queries/{name}). Steps stored before the queries were kept have queries None."""
    rows = repo.read("incident_steps", incident_id=incident_id).rows
    return [{**r, "queries": json.loads(r["queries"]) if r["queries"] else None} for r in rows]


class ResolveBody(BaseModel):
    change_id: str


@app.post("/api/tenants/{tenant}/incidents/{incident_id}/resolve")
def resolve(repo: Repo, incident_id: str, body: ResolveBody) -> dict[str, Any]:
    out = respond_svc.resolve(repo, incident_id, body.change_id)
    update = repo.read("incident_update", incident_id=incident_id).rows  # re-posted with the confirmed cause
    out["update_text"] = update[0]["text"] if update else None
    # Already resolved (data None): nothing changed, so nothing is re-posted; repeat calls cannot flood Slack.
    out["slack"] = slack.post(out["update_text"]) if out.get("data") is not None else "nothing to post"
    return out


@app.get("/api/tenants/{tenant}/incidents/{incident_id}/steps")
def steps(repo: Repo, incident_id: str) -> list[dict[str, Any]]:
    rows = _stored_steps(repo, incident_id)
    if not rows:
        raise HTTPException(404, f"no agent steps for incident {incident_id!r}")
    return rows


@app.get("/api/tenants/{tenant}/graph")
def graph(repo: Repo, at: int | None = None) -> dict[str, list[dict[str, Any]]]:
    if at is None:  # default to the act-1 alert time, so the retired dependency shows as retired
        at = next((a["at"] for a in repo.read("list_alerts").rows if a["act"] == 1), None)
    rows = registry.call("service_map", ToolContext(repo), {"at": at}).data
    return {
        "nodes": [{k: r[k] for k in ("id", "name", "tier", "team")} for r in rows],
        # OPTIONAL MATCH + collect() leaves one {to: null} map for services with no dependencies.
        "edges": [{"source": r["id"], "target": d["to"], "live": d["live"]} for r in rows for d in r["deps"]
                  if d["to"]],
    }


@app.get("/api/tools")
def tools() -> list[dict[str, Any]]:
    return registry.specs()


@app.get("/api/queries/{name}")
def query_text(name: str) -> dict[str, str]:
    """One named query from the adapter's catalogue (code, not tenant data): how a stored step shows its Cypher. The
    sha matches the one the step stored unless the query was edited since."""
    if not (q := all_queries().get(name)):
        raise HTTPException(404, f"unknown query {name!r}")
    return {"name": q.name, "purpose": q.purpose, "cypher": q.cypher, "sha": cypher_sha(q.cypher)}


@app.post("/api/tenants/{tenant}/tools/{name}")
def call_tool(request: Request, repo: Repo, name: str,
              args: Annotated[dict[str, Any] | None, Body()] = None) -> dict[str, Any]:
    if name not in registry.REGISTRY:
        raise HTTPException(404, f"unknown tool {name!r}")
    if sessions.reserved((args or {}).get("user")):
        raise HTTPException(403, sessions.RESERVED)
    user, token = str((args or {}).get("user") or ""), get_settings().mcp_bearer()
    if user and token and not user.startswith("web-") and not _bearer_ok(request, token):
        raise HTTPException(403, "only web-* conversation ids are open here; a named user (person:..., @handle) "
                                 "needs Authorization: Bearer <the MCP_TOKEN>")
    # The UI only reads through this route (ask, graph tools). Writing facts (record_change, transfer_ownership,
    # retire_dependency...) would rewrite the shared demo company for every visitor after you, so on a deployment
    # (a token is set) a write needs it, the same one /mcp takes. Locally, with no token, everything stays open.
    tool, token = registry.REGISTRY[name], get_settings().mcp_bearer()
    writes = tool.writes and ("incident_id" not in tool.args_model.model_fields or (args or {}).get("incident_id"))
    if writes and token and not _bearer_ok(request, token):
        raise HTTPException(401, f"{name} writes to the graph: send Authorization: Bearer <the MCP_TOKEN>",
                            headers={"WWW-Authenticate": "Bearer"})
    return respond_svc.run_tool(repo, name, args or {}).model_dump(mode="json")


from oncall_brain.api.slack_app import router as slack_router  # noqa: E402  (it uses the names above)

app.include_router(slack_router)
