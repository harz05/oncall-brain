"""FalkorDB adapter: one graph per tenant (`tenant_<name>`), a pristine copy per tenant for demo resets."""

import re
import time
from typing import Any

from falkordb import FalkorDB
from redis.exceptions import ResponseError

from oncall_brain.adapters.falkordb import queries
from oncall_brain.domain.models import QueryRun

_TENANT = re.compile(r"^[a-z0-9_]{1,40}$")
PREFIX, PRISTINE = "tenant_", "pristine_"

# Index every label we MERGE or look up by id. FalkorDB raises if an index already exists; that's fine.
INDEXED_LABELS = ["Team", "Person", "Service", "Change", "Alert", "Anomaly", "Incident", "Hypothesis",
                  "Evidence", "Runbook", "Message", "Ticket", "AgentStep"]
TIME_INDEXED = ["Change", "Anomaly"]  # range index on .at: the alert-window filters scan these


def _check_tenant(tenant: str) -> str:
    if not _TENANT.fullmatch(tenant):
        raise ValueError("tenant must match [a-z0-9_]{1,40}")
    return tenant


class FalkorRepository:
    def __init__(self, db: FalkorDB, tenant: str):
        self.tenant = _check_tenant(tenant)
        self._db = db
        self._graph = db.select_graph(PREFIX + tenant)

    def lock(self):
        """One writer per tenant across processes (API, MCP, scripts): a Redis lock next to the graph.
        FalkorDB commits each write query atomically, but two agents MERGE-ing the same edge at the same
        moment can both miss it and both create it, so whole agent runs on a tenant are serialised."""
        # The lease outlives any sane run (an LLM planner can take minutes); a crashed holder frees it after 15 min.
        return self._db.connection.lock(f"oncall_brain:lock:{self.tenant}", timeout=900, blocking_timeout=120)

    def _run(self, name: str, params: dict[str, Any], readonly: bool) -> QueryRun:
        q = queries.get(name)
        t0 = time.perf_counter()
        res = (self._graph.ro_query if readonly else self._graph.query)(q.cypher, params)
        ms = (time.perf_counter() - t0) * 1000
        cols = [h[1] if isinstance(h, list | tuple) else h for h in (res.header or [])]
        rows = [dict(zip(cols, r, strict=False)) for r in res.result_set]
        return QueryRun(name=name, cypher=q.cypher, params=params, rows=rows, ms=round(ms, 2), readonly=readonly)

    def read(self, name: str, /, **params: Any) -> QueryRun:
        return self._run(name, params, readonly=True)

    def write(self, name: str, /, **params: Any) -> QueryRun:
        return self._run(name, params, readonly=False)

    def ensure_schema(self) -> None:
        targets = [(label, "id") for label in INDEXED_LABELS] + [(label, "at") for label in TIME_INDEXED]
        for label, prop in targets:
            try:
                # Labels and properties come from the constant lists above, never from input.
                self._graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            except Exception as e:  # already indexed
                if "already indexed" not in str(e):
                    raise


class FalkorGraphStore:
    def __init__(self, host: str = "localhost", port: int = 6379, username: str | None = None,
                 password: str | None = None, ssl: bool = False, url: str = ""):
        self.db = (FalkorDB.from_url(url) if url
                   else FalkorDB(host=host, port=port, username=username, password=password, ssl=ssl))

    def tenant(self, tenant: str) -> FalkorRepository:
        return FalkorRepository(self.db, tenant)

    def _names(self) -> list[str]:
        return self.db.list_graphs()

    def exists(self, tenant: str) -> bool:
        return PREFIX + _check_tenant(tenant) in self._names()

    def tenants(self) -> list[str]:
        return sorted(g[len(PREFIX):] for g in self._names() if g.startswith(PREFIX))

    def _copy(self, src: str, dst: str) -> None:
        """GRAPH.COPY forks like BGSAVE, and Redis allows one fork at a time, so a copy that overlaps a
        background save fails with 'could not fork'. That is transient: retry with backoff."""
        for attempt in range(7):
            try:
                self.db.select_graph(src).copy(dst)
                return
            except ResponseError as e:
                if "fork" not in str(e) or attempt == 6:
                    raise
                time.sleep(0.05 * 2**attempt)

    def snapshot(self, tenant: str) -> None:
        """Keep a pristine copy (GRAPH.COPY) so the demo can be replayed from the same state."""
        if PRISTINE + tenant in self._names():
            self.db.select_graph(PRISTINE + tenant).delete()
        self._copy(PREFIX + _check_tenant(tenant), PRISTINE + tenant)

    def restore(self, tenant: str) -> bool:
        """Replace the tenant graph with its pristine copy. False if there is no usable copy."""
        if PRISTINE + _check_tenant(tenant) not in self._names():
            return False
        if self.exists(tenant):
            self.db.select_graph(PREFIX + tenant).delete()
        try:
            self._copy(PRISTINE + tenant, PREFIX + tenant)
        except ResponseError:
            return False  # caller re-seeds from scratch
        return True

    def lock(self, tenant: str):
        return self.tenant(tenant).lock()

    def drop(self, tenant: str) -> None:
        for name in (PREFIX + _check_tenant(tenant), PRISTINE + tenant):
            if name in self._names():
                self.db.select_graph(name).delete()
