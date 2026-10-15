"""Ports: the interfaces the core depends on. Adapters implement them; tests use in-memory doubles."""

from contextlib import AbstractContextManager
from typing import Any, Protocol

from oncall_brain.domain.models import Decision, QueryRun


class GraphRepository(Protocol):
    """One tenant's graph. Queries are referenced by name (see adapters/falkordb/queries/*.cypher)."""

    tenant: str

    def read(self, name: str, /, **params: Any) -> QueryRun:
        """Run a named query read-only (GRAPH.RO_QUERY: the database rejects any write)."""
        ...

    def write(self, name: str, /, **params: Any) -> QueryRun:
        """Run a named query that may write."""
        ...

    def ensure_schema(self) -> None:
        """Create the indexes the queries rely on (idempotent)."""
        ...

    def lock(self) -> AbstractContextManager:
        """Exclusive lock on this tenant for a whole agent run (see the adapter for why)."""
        ...

    def scratch(self, name: str) -> "GraphRepository":
        """A side graph of this tenant for a projection a graph algorithm runs on; drop it with `drop_graph()`."""
        ...

    def drop_graph(self) -> None:
        """Delete this (scratch) graph."""
        ...


class GraphStore(Protocol):
    """Many isolated graphs in one FalkorDB: one per tenant, plus a pristine copy for demo resets."""

    def tenant(self, tenant: str) -> GraphRepository: ...
    def exists(self, tenant: str) -> bool: ...
    def snapshot(self, tenant: str) -> None: ...
    def restore(self, tenant: str) -> bool: ...
    def drop(self, tenant: str) -> None: ...
    def tenants(self) -> list[str]: ...
    def lock(self, tenant: str) -> AbstractContextManager: ...
    def clone_pristine(self, tenant: str, into: str) -> bool: ...


class LLMProvider(Protocol):
    """Chooses the next tool for an agent role from what the graph currently says (the board)."""

    name: str

    def decide(self, role: str, board: dict[str, Any], tools: list[dict[str, Any]]) -> Decision: ...
