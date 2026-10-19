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

    def plan(self, name: str, params: dict[str, Any], profile: bool = False) -> dict[str, Any]:
        """The database's plan for a named query: {"kind", "ran", "plan": [one line per operation]}. Profiling runs
        the query, so it is done only for a query that cannot write; any other is explained. An unknown name, or
        missing parameters: ValueError."""
        ...

    def ensure_schema(self) -> None:
        """Create the indexes the queries rely on (idempotent)."""
        ...

    def lock(self, scope: str = "") -> AbstractContextManager:
        """Exclusive lock on this tenant for a whole agent run (see the adapter for why); with a scope, a narrower
        lock beside it for a part of the graph no run touches (a conversation session)."""
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
    def staging(self, tenant: str) -> GraphRepository: ...
    def publish(self, tenant: str) -> None: ...
    def restore(self, tenant: str) -> bool: ...
    def drop(self, tenant: str) -> None: ...
    def tenants(self) -> list[str]: ...
    def lock(self, tenant: str) -> AbstractContextManager: ...
    def clone_pristine(self, tenant: str, into: str, ttl: int = 0) -> bool: ...

    def incr(self, key: str, ttl: int, by: int = 1) -> int:
        """Add to a counter every process on this database shares (throttles, the daily LLM budget) and return it; a
        new counter expires after `ttl` seconds."""
        ...

    def counter(self, key: str) -> int:
        """A shared counter's value (0 when it does not exist or has expired)."""
        ...

    def claim(self, key: str, ttl: float) -> bool:
        """Mark a shared key taken for `ttl` seconds; False if someone already holds it."""
        ...

    def unclaim(self, key: str) -> None: ...


class LLMProvider(Protocol):
    """Chooses the next tool for an agent role from what the graph currently says (the board)."""

    name: str

    def decide(self, role: str, board: dict[str, Any], tools: list[dict[str, Any]]) -> Decision: ...
