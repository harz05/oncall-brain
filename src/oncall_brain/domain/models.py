"""Value objects shared by every layer. Pure data, no I/O."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class QueryRun(BaseModel):
    """One Cypher execution, kept for the trace so every answer shows its queries."""

    name: str
    cypher: str
    params: dict[str, Any]
    rows: list[dict[str, Any]]
    ms: float
    readonly: bool

    @property
    def row_count(self) -> int:
        return len(self.rows)


class Highlight(BaseModel):
    """Graph ids the UI lights up as evidence for a step."""

    nodes: list[str] = Field(default_factory=list)
    edges: list[tuple[str, str, str]] = Field(default_factory=list)  # (source id, target id, rel type)

    def merge(self, other: "Highlight") -> "Highlight":
        return Highlight(
            nodes=list(dict.fromkeys(self.nodes + other.nodes)),
            edges=list(dict.fromkeys(self.edges + other.edges)),
        )


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


class TraceStep(BaseModel):
    seq: int
    role: str
    tool: str
    reason: str
    summary: str
    writes: bool = False
    queries: list[QueryRun] = Field(default_factory=list)
    highlight: Highlight = Field(default_factory=Highlight)
    data: Any = None
