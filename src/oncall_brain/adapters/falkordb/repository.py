"""FalkorDB adapter: one graph per tenant (`tenant_<name>`), a pristine copy per tenant for demo resets."""

import re
import time
from typing import Any

from falkordb import FalkorDB
from redis.exceptions import ResponseError

from oncall_brain.adapters.falkordb import queries
from oncall_brain.domain.models import QueryRun

_TENANT = re.compile(r"^[a-z0-9_]{1,40}$")
PREFIX, PRISTINE, RESTORING, SCRATCH = "tenant_", "pristine_", "restoring_", "scratch_"

# Index every label we MERGE or look up by id, and give each a UNIQUE constraint on `id` (ensure_schema), so the
# database itself refuses a second node with an id that exists. FalkorDB raises if an index already exists; that's fine.
INDEXED_LABELS = ["Team", "Person", "Service", "Change", "Alert", "Anomaly", "Incident", "Hypothesis",
                  "Evidence", "Runbook", "Message", "Ticket", "Doc", "AgentStep", "Session", "Question", "Initiative"]
TIME_INDEXED = ["Change", "Anomaly"]  # range index on .at: the alert-window filters scan these
FULLTEXT = {"Doc": ["title", "text"], "Ticket": ["title", "text"], "Message": ["text"]}  # what `ask` searches


def _check_tenant(tenant: str) -> str:
    if not _TENANT.fullmatch(tenant):
        raise ValueError("tenant must match [a-z0-9_]{1,40}")
    return tenant


class FalkorRepository:
    def __init__(self, db: FalkorDB, tenant: str, graph: str | None = None, lock_wait: float = 120):
        self.tenant = _check_tenant(tenant)
        self._db, self._lock_wait = db, lock_wait
        self._graph = db.select_graph(graph or PREFIX + tenant)

    def scratch(self, name: str) -> "FalkorRepository":
        """A repository on a side graph of this tenant (`scratch_<tenant>_<name>`): a projection built from the
        tenant graph for a graph algorithm to run on (the algorithms see every edge, so the projection holds only the
        edges live at the time in question). Callers drop it with `drop_graph()` when done."""
        return FalkorRepository(self._db, self.tenant, graph=SCRATCH + f"{self.tenant}_{_check_tenant(name)}",
                                lock_wait=self._lock_wait)

    def drop_graph(self) -> None:
        """Delete this graph (meant for scratch projections; a tenant graph is dropped through the store)."""
        if self._graph.name in self._db.list_graphs():
            self._graph.delete()

    def lock(self, scope: str = ""):
        """One agent run per tenant at a time, across processes (API, MCP, scripts): a Redis lock next to the graph.
        With a scope, a narrower lock beside it (`oncall_brain:lock:<tenant>:<scope>`, 30 s lease) for a part of the
        graph no agent run touches, such as one engineer's conversation session: its writers queue on it, never on
        the investigation.
        Each write query commits atomically, but MERGE is not a uniqueness guarantee under concurrency: in our test
        (12 clients x 100 concurrent `MERGE (:N {id:7})` on an unconstrained label) FalkorDB created 2 nodes. Node ids
        are now guarded by unique constraints (`_ensure_unique_ids`), but FalkorDB has no edge constraint, and
        12 clients racing `MERGE` on one edge still made a duplicate (scripts/concurrency.py). And two concurrent runs
        on one incident would redo each other's work. So whole runs on a tenant are serialised; reads (tools called
        without an incident) stay concurrent, and different tenants run in parallel."""
        # A 2-minute lease that respond() renews on every recorded step, so a long LLM run keeps it and a holder that
        # died (a redeploy, an OOM kill) frees the tenant within 2 minutes instead of blocking it for 15.
        # A waiter gives up after lock_wait seconds (LOCK_WAIT_SECONDS) with LockError, which the surfaces answer as
        # "busy, retry shortly": each waiter holds a server thread, and a long wait behind a 2-minute run let a burst
        # of writes take every thread and freeze the whole site. Waiters poll every 10 ms, not redis-py's default
        # 100 ms: with 8 writers on one tenant the slowest write fell from 1.3 s to 0.3 s and p99 from 400 ms to 225 ms
        # (scripts/concurrency.py, PERF.md "Concurrency").
        key = f"oncall_brain:lock:{self.tenant}" + (f":{scope}" if scope else "")
        return self._db.connection.lock(key, timeout=30 if scope else 120, blocking_timeout=self._lock_wait,
                                        sleep=0.01)

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
        """Indexes and the UNIQUE `id` constraints the queries rely on (idempotent; a reset re-runs it)."""
        # Labels and properties come from the constants above, never from input.
        targets = [(label, "id") for label in INDEXED_LABELS] + [(label, "at") for label in TIME_INDEXED]
        stmts = [f"CREATE INDEX FOR (n:{label}) ON (n.{prop})" for label, prop in targets] + [
            f"CREATE FULLTEXT INDEX FOR (n:{label}) ON ({', '.join('n.' + p for p in props)})"
            for label, props in FULLTEXT.items()]
        for stmt in stmts:
            try:
                self._graph.query(stmt)
            except Exception as e:  # already indexed
                if "already indexed" not in str(e):
                    raise
        self._ensure_unique_ids()

    def unique_constraints(self) -> dict[str, str]:
        """{label: status} of the UNIQUE node constraints on `id`: OPERATIONAL once built, PENDING right after
        creation, FAILED if the label already held two nodes with one id when the constraint was created."""
        return {c["label"]: c["status"] for c in self._graph.list_constraints()
                if c["type"] == "UNIQUE" and c["entitytype"] == "NODE" and list(c["properties"]) == ["id"]}

    def _ensure_unique_ids(self, wait: float = 5.0) -> None:
        """One UNIQUE constraint on `id` per indexed label (GRAPH.CONSTRAINT CREATE ... UNIQUE NODE <label>
        PROPERTIES 1 id). From then on FalkorDB refuses any write that would make a second node with an existing id,
        whoever the writer is, so uniqueness no longer rests on MERGE and the tenant lock alone (MERGE on the id keeps
        updating in place). Creation is asynchronous: wait until every constraint is OPERATIONAL, so the writes that
        follow are already guarded. GRAPH.COPY carries constraints, so pristine copies and resets keep them."""
        have = self.unique_constraints()
        for label in INDEXED_LABELS:
            if label not in have:
                try:
                    self._graph.create_node_unique_constraint(label, "id")
                except ResponseError as e:  # another seeder of the same graph got there first
                    if "already exists" not in str(e):
                        raise
        deadline = time.monotonic() + wait
        while True:
            have = self.unique_constraints()
            failed = sorted(label for label, status in have.items() if status == "FAILED")
            if failed:
                raise RuntimeError(f"unique id constraint failed on {', '.join(failed)}: the graph already holds two "
                                   "nodes with one id; re-seed the tenant")
            if all(have.get(label) == "OPERATIONAL" for label in INDEXED_LABELS):
                return
            if time.monotonic() > deadline:
                pending = sorted(label for label in INDEXED_LABELS if have.get(label) != "OPERATIONAL")
                raise RuntimeError(f"unique id constraints still not operational after {wait} s: {', '.join(pending)}")
            time.sleep(0.02)


class FalkorGraphStore:
    def __init__(self, host: str = "localhost", port: int = 6379, username: str | None = None,
                 password: str | None = None, ssl: bool = False, url: str = "", lock_wait: float = 120):
        self.db = (FalkorDB.from_url(url) if url
                   else FalkorDB(host=host, port=port, username=username, password=password, ssl=ssl))
        self.lock_wait = lock_wait

    def tenant(self, tenant: str) -> FalkorRepository:
        return FalkorRepository(self.db, tenant, lock_wait=self.lock_wait)

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
        """Replace the tenant graph with its pristine copy, in one step: GRAPH.COPY the pristine graph to a
        staging key, then RENAME it over the tenant key. Redis renames atomically and FalkorDB follows the
        rename (GRAPH.LIST, indexes and constraints all move with it), so readers never see a missing graph;
        deleting first and copying after left a window in which every read failed with
        'Invalid graph operation on empty key'. False if there is no usable copy."""
        if PRISTINE + _check_tenant(tenant) not in self._names():
            return False
        staging = RESTORING + tenant
        if staging in self._names():
            self.db.select_graph(staging).delete()  # left behind by an interrupted restore
        try:
            self._copy(PRISTINE + tenant, staging)
        except ResponseError:
            return False  # caller re-seeds from scratch
        self.db.connection.execute_command("RENAME", staging, PREFIX + tenant)
        return True

    def lock(self, tenant: str):
        return self.tenant(tenant).lock()

    def incr(self, key: str, ttl: int, by: int = 1) -> int:
        """A counter in the Redis next to the graphs, so the app and a standalone MCP process share it and it survives
        restarts. One MULTI: SET NX EX creates it with its expiry (any Redis version), INCRBY keeps that expiry."""
        pipe = self.db.connection.pipeline()
        pipe.set(key, 0, ex=ttl, nx=True)
        pipe.incrby(key, by)
        return int(pipe.execute()[1])

    def counter(self, key: str) -> int:
        return int(self.db.connection.get(key) or 0)

    def clone_pristine(self, tenant: str, into: str) -> bool:
        """Copy the tenant's pristine graph into another tenant's slot (for what-if replays). False if none."""
        if PRISTINE + _check_tenant(tenant) not in self._names():
            return False
        self.drop(into)
        self._copy(PRISTINE + tenant, PREFIX + _check_tenant(into))
        return True

    def drop(self, tenant: str) -> None:
        names = self._names()
        scratch = [n for n in names if n.startswith(SCRATCH + _check_tenant(tenant) + "_")]
        for name in (PREFIX + tenant, PRISTINE + tenant, RESTORING + tenant, *scratch):
            if name in names:
                self.db.select_graph(name).delete()
