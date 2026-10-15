"""HTTP API: one of the three surfaces of the tool registry (with the agent loop and MCP).

Handlers stay thin: they pick the tenant's graph and call services / the registry. Errors map to
{"detail": str}: unknown things (ValueError from the services) -> 404, bad input -> 422, FalkorDB down -> 503.
Run: uvicorn oncall_brain.api.app:app --port 8000
"""

import os
from functools import lru_cache
from pathlib import Path as FsPath
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from oncall_brain.adapters.falkordb.repository import FalkorGraphStore
from oncall_brain.agents import registry
from oncall_brain.agents.registry import ToolContext
from oncall_brain.config import get_settings
from oncall_brain.ports import GraphRepository, LLMProvider
from oncall_brain.services import respond as respond_svc
from oncall_brain.services.seeding import reset

WEB_DIR = FsPath(os.environ.get("WEB_DIR") or FsPath(__file__).resolve().parents[3] / "web")

Tenant = Annotated[str, Path(pattern=r"^[a-z0-9_]{1,40}$")]

app = FastAPI(title="On-call Brain", description="Incident agents over a FalkorDB knowledge graph.")
# check_dir=False: the web/ folder may appear after the server starts.
app.mount("/web", StaticFiles(directory=WEB_DIR, check_dir=False), name="web")


# Built on first use, not at import, so the app imports (and /api/health answers) with FalkorDB down.
# lru_cache does not cache exceptions, so a failed connect is retried on the next request.
@lru_cache
def store() -> FalkorGraphStore:
    from oncall_brain.wiring import make_store

    return make_store()


@lru_cache
def llm() -> LLMProvider:
    from oncall_brain.wiring import make_llm

    return make_llm()


def _detail(errors: list[dict[str, Any]]) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errors)


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def _invalid(_: Request, e: RequestValidationError | ValidationError) -> JSONResponse:
    return JSONResponse({"detail": _detail(e.errors())}, status_code=422)


@app.exception_handler(ValueError)
async def _unknown(_: Request, e: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=404)


@app.exception_handler(RedisConnectionError)
async def _db_down(_: Request, e: RedisConnectionError) -> JSONResponse:
    return JSONResponse({"detail": f"FalkorDB unavailable: {e}"}, status_code=503)


def tenant_repo(tenant: Tenant) -> GraphRepository:
    if not store().exists(tenant):
        raise HTTPException(404, f"unknown tenant {tenant!r}; POST /api/tenants/{tenant}/reset seeds it")
    return store().tenant(tenant)


Repo = Annotated[GraphRepository, Depends(tenant_repo)]


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    page = WEB_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(404, f"no UI at {page}")
    return FileResponse(page)


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        up = bool(store().db.connection.ping())
    except Exception:  # any failure here just means "not reachable"; health itself must answer
        up = False
    return {"ok": True, "falkordb": up, "planner": llm().name, "default_tenant": get_settings().default_tenant}


@app.get("/api/tenants")
def tenants() -> dict[str, Any]:
    return {"tenants": store().tenants(), "default": get_settings().default_tenant}


@app.post("/api/tenants/{tenant}/reset")
def reset_tenant(tenant: Tenant) -> dict[str, str]:
    return {"tenant": tenant, "status": reset(store(), tenant)}


@app.get("/api/tenants/{tenant}/alerts")
def alerts(repo: Repo) -> list[dict[str, Any]]:
    return repo.read("list_alerts").rows


@app.post("/api/tenants/{tenant}/alerts/{alert_id}/respond")
def respond(repo: Repo, alert_id: str) -> dict[str, Any]:
    run = respond_svc.respond(repo, alert_id, llm())
    run["steps"] = [s.model_dump(mode="json") for s in run["steps"]]
    run["outcome"]["highlight"] = run["outcome"]["highlight"].model_dump(mode="json")
    return run


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
    return registry.call(name, ToolContext(repo), args or {}).model_dump(mode="json")
