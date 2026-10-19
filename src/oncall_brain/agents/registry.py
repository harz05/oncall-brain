"""The tool registry: every graph tool is defined once here and exposed to the agent loop, the MCP
server and the HTTP API. A tool is a plain function `fn(ctx, args) -> ToolOutput` whose pydantic args
model doubles as its JSON schema."""

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from oncall_brain.domain.models import ToolOutput
from oncall_brain.ports import GraphRepository


@dataclass
class ToolContext:
    repo: GraphRepository


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[ToolContext, Any], ToolOutput]
    writes: bool
    agent: bool  # False: only humans and outside clients may call it (confirming a fix, recording facts)

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "writes": self.writes,
                "input_schema": self.args_model.model_json_schema()}


REGISTRY: dict[str, Tool] = {}


def tool(writes: bool = False, agent: bool = True):
    """Register a function as a tool. Its docstring is the description agents and MCP clients see.
    agent=False keeps it away from agent runs: an agent must not confirm its own fix or invent graph facts."""

    def deco(fn: Callable[[ToolContext, Any], ToolOutput]):
        args_model = list(inspect.signature(fn).parameters.values())[1].annotation
        REGISTRY[fn.__name__] = Tool(fn.__name__, inspect.getdoc(fn) or "", args_model, fn, writes, agent)
        return fn

    return deco


SERVICE_ARGS = ("service", "from_service", "to_service", "caller", "callee")
_GENERIC = {"svc", "service", "services", "api", "app", "server", "prod", "the"}


def name_tokens(name: str) -> list[str]:
    """The words of a service name worth matching on: "payment-service" -> ["payment"]."""
    return [t for t in re.split(r"[^a-z0-9]+", name.lower().removeprefix("svc:")) if len(t) > 2 and t not in _GENERIC]


def resolve_service(ctx: ToolContext, name: str) -> tuple[str | None, list[str]]:
    """(the service id `name` means, None) or (None, the closest service ids), from the graph (resolve_service)."""
    rows = ctx.repo.read("resolve_service", service=name, tokens=name_tokens(name)).rows
    return (rows[0]["id"], []) if rows and rows[0]["exact"] else (None, [r["id"] for r in rows])


def call(name: str, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    """Run a tool. Every service argument is resolved against the graph first, for every surface (agents, MCP, HTTP):
    a name without `svc:` or by its display name becomes the id, and a name the graph does not hold is refused with
    the closest ones, so no tool answers "0 services depend on payment-service" about a service that does not exist."""
    if name not in REGISTRY:
        raise KeyError(f"unknown tool {name!r}")
    t = REGISTRY[name]
    for k in SERVICE_ARGS:
        if isinstance(args.get(k), str) and args[k]:
            found, closest = resolve_service(ctx, args[k])
            if not found:
                raise ValueError(f"No service named {args[k]!r} in the graph" + (
                    f"; did you mean {', '.join(closest)}?" if closest else ""))
            args = {**args, k: found}
    return t.fn(ctx, t.args_model.model_validate(args))


def specs(agents_only: bool = False) -> list[dict[str, Any]]:
    return [t.spec() for t in REGISTRY.values() if t.agent or not agents_only]
