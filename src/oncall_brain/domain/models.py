"""Value objects shared by every layer. Pure data, no I/O."""

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field


def cypher_sha(cypher: str) -> str:
    """A short fingerprint of a query's text. A stored step keeps it, so a later edit of that query shows."""
    return hashlib.sha256(cypher.encode()).hexdigest()[:12]


class QueryRun(BaseModel):
    """One Cypher execution, kept for the trace so every answer shows its queries."""

    name: str
    cypher: str
    params: dict[str, Any]
    rows: list[dict[str, Any]]
    ms: float  # the round trip, as the app saw it
    readonly: bool
    # FalkorDB's own account of the run, from its reply: execution time inside the database, whether the plan came
    # from its cache, and what a write changed (only the non-zero counts: nodes_created, relationships_created, ...).
    db_ms: float | None = None
    cached: bool | None = None
    wrote: dict[str, int] | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)


class Highlight(BaseModel):
    """Graph ids the UI lights up as evidence for a step."""

    nodes: list[str] = Field(default_factory=list)
    edges: list[tuple[str, str, str]] = Field(default_factory=list)  # (source id, target id, rel type)


class ToolOutput(BaseModel):
    summary: str
    data: Any = None
    queries: list[QueryRun] = Field(default_factory=list)
    highlight: Highlight = Field(default_factory=Highlight)


class Decision(BaseModel):
    """What an agent role does next: call a tool, or finish (optionally handing off to another role)."""

    action: Literal["call", "done"]
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str
    handoff_to: str | None = None
    by: str = "rules"  # who decided: "rules" (the deterministic planner) or the model id (e.g. claude-opus-5-5)
    usage: int = 0  # tokens the provider billed for this decision (services/respond.py RunBudget counts them)


class TraceStep(BaseModel):
    seq: int
    role: str
    tool: str
    reason: str
    summary: str
    by: str = "rules"  # see Decision.by
    writes: bool = False
    queries: list[QueryRun] = Field(default_factory=list)
    highlight: Highlight = Field(default_factory=Highlight)
    data: Any = None
