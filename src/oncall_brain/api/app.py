"""HTTP API: one of the three surfaces of the tool registry (with the agent loop and MCP).

Handlers stay thin: they pick the tenant's graph and call services / the registry. Errors map to
{"detail": str}: unknown things (ValueError from the services) -> 404, bad input -> 422, FalkorDB down or
erroring -> 503, misconfigured planner -> 503, tenant cap reached -> 429.
Guards in front of every route: Host allow-list (DNS rebinding), same-origin writes (CSRF), optional API_TOKEN.
Run: uvicorn oncall_brain.api.app:app --port 8000
"""

import os
import secrets
from collections.abc import Awaitable, Callable
from functools import lru_cache
from pathlib import Path as FsPath
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Body, Depends, FastAPI, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from oncall_brain.adapters.falkordb.repository import FalkorGraphStore
from oncall_brain.agents import registry
from oncall_brain.agents.registry import ToolContext
from oncall_brain.config import get_settings
from oncall_brain.ports import GraphRepository, LLMProvider
from oncall_brain.services import respond as respond_svc
from oncall_brain.services.seeding import TenantLimitReached, reset

WEB_DIR = FsPath(os.environ.get("WEB_DIR") or FsPath(__file__).resolve().parents[3] / "web")

Tenant = Annotated[str, Path(pattern=r"^[a-z0-9_]{1,40}$")]

app = FastAPI(title="On-call Brain", description="Incident agents over a FalkorDB knowledge graph.")
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


@app.exception_handler(RedisError)
async def _db_error(_: Request, e: RedisError) -> JSONResponse:
    if isinstance(e, RedisConnectionError):  # also covers auth failures
        return JSONResponse({"detail": f"FalkorDB unavailable: {e}"}, status_code=503)
    # Timeouts and ResponseError (e.g. "GRAPH.COPY failed, could not fork"). First line only, capped: FalkorDB
    # error texts can quote the whole query.
    msg = (str(e).splitlines() or [""])[0][:160]
    return JSONResponse({"detail": f"FalkorDB error ({type(e).__name__}): {msg}"}, status_code=503)


@app.middleware("http")
async def _guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    path = request.url.path
    # CSRF: any web page can fire a body-less POST at localhost, but the browser then sends its own Origin. host:port
    # only (no scheme), so a TLS-terminating proxy in front still matches.
    origin = request.headers.get("origin")
    cross = origin is not None and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower()
    if cross and request.method not in ("GET", "HEAD", "OPTIONS"):
        return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
    token = get_settings().api_token
    if token and path.startswith("/api/") and path != "/api/health":
        sent = request.headers.get("authorization", "").encode("latin-1")  # Starlette decodes headers as latin-1
        if not secrets.compare_digest(sent, f"Bearer {token}".encode()):
            return JSONResponse({"detail": "missing or wrong API token"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
    # FalkorDB refuses string parameters containing NUL; that is bad input (422), not a server error.
    if "\x00" in path or b"\\u0000" in await request.body():
        return JSONResponse({"detail": "NUL characters are not allowed"}, status_code=422)
    return await call_next(request)


# Added last so it runs first. DNS rebinding: a hostile name resolving to 127.0.0.1 still sends its own Host header.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_settings().hosts())


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


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        up = bool(store().db.connection.ping())
    except Exception:  # any failure here just means "not reachable"; health itself must answer
        up = False
    try:
        planner, ok = llm().name, True
    except HTTPException as e:
        planner, ok = f"<error: {e.detail}>", False
    return {"ok": ok, "falkordb": up, "planner": planner, "default_tenant": get_settings().default_tenant}


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
    return repo.read("list_alerts").rows


@app.post("/api/tenants/{tenant}/alerts/{alert_id}/respond")
def respond(repo: Repo, alert_id: str) -> dict[str, Any]:
    return respond_svc.respond(repo, alert_id, llm())  # FastAPI serialises the TraceStep models inside


class ResolveBody(BaseModel):
    change_id: str


@app.post("/api/tenants/{tenant}/incidents/{incident_id}/resolve")
def resolve(repo: Repo, incident_id: str, body: ResolveBody) -> dict[str, Any]:
    return respond_svc.resolve(repo, incident_id, body.change_id)


@app.get("/api/tenants/{tenant}/incidents/{incident_id}/steps")
def steps(repo: Repo, incident_id: str) -> list[dict[str, Any]]:
    rows = repo.read("incident_steps", incident_id=incident_id).rows
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


@app.post("/api/tenants/{tenant}/tools/{name}")
def call_tool(repo: Repo, name: str, args: Annotated[dict[str, Any] | None, Body()] = None) -> dict[str, Any]:
    if name not in registry.REGISTRY:
        raise HTTPException(404, f"unknown tool {name!r}")
    return respond_svc.run_tool(repo, name, args or {}).model_dump(mode="json")
