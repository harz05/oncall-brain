"""The tool registry: every graph tool is defined once here and exposed to the agent loop, the MCP
server and the HTTP API. A tool is a plain function `fn(ctx, args) -> ToolOutput` whose pydantic args
model doubles as its JSON schema."""

import inspect
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


def call(name: str, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    if name not in REGISTRY:
        raise KeyError(f"unknown tool {name!r}")
    t = REGISTRY[name]
    return t.fn(ctx, t.args_model.model_validate(args))


def specs(agents_only: bool = False) -> list[dict[str, Any]]:
    return [t.spec() for t in REGISTRY.values() if t.agent or not agents_only]
