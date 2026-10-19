"""FalkorDB adapter: one graph per tenant (`tenant_<name>`), a pristine copy per tenant for demo resets."""

import re
import threading
import time
import weakref
from pathlib import Path
from typing import Any

from falkordb import FalkorDB
from redis.exceptions import ResponseError

from oncall_brain.adapters.falkordb import queries
from oncall_brain.adapters.falkordb.coordination import Coordination, GraphLock
from oncall_brain.domain.models import QueryRun

_TENANT = re.compile(r"^[a-z0-9_]{1,40}$")
PREFIX, PRISTINE, RESTORING, SCRATCH = "tenant_", "pristine_", "restoring_", "scratch_"
SEEDING = "seeding_"  # a seed's own staging graph, apart from a reset's restoring_<tenant>
SCRATCH_TTL = 300  # seconds; an algorithm's projection lives for one tool call

# Index every label we MERGE or look up by id, and give each a UNIQUE constraint on `id` (ensure_schema), so the
# database itself refuses a second node with an id that exists. FalkorDB raises if an index already exists; that's fine.
INDEXED_LABELS = ["Team", "Person", "Service", "Change", "Alert", "Anomaly", "Incident", "Hypothesis",
                  "Evidence", "Runbook", "Message", "Ticket", "Doc", "AgentStep", "Session", "Question", "Initiative"]
TIME_INDEXED = ["Change", "Anomaly", "Alert"]  # range index on .at: the alert-window filters scan these
# Other properties a query starts from (tests/integration/test_plans.py checks every query's plan).
PROP_INDEXED = [("Person", "handle"), ("Session", "user"), ("Doc", "kind"), ("Incident", "status")]
FULLTEXT = {"Doc": ["title", "text"], "Ticket": ["title", "text"], "Message": ["text"]}  # what `ask` searches
# The temporal edges every point-in-time query filters on: a MANDATORY constraint makes FalkorDB refuse one without
# valid_from, so "what was true at alert time" can never meet an undated dependency or owner (ensure_schema).
DATED_EDGES = [("DEPENDS_ON", "valid_from"), ("OWNS", "valid_from")]
# A dependency's identity, '<caller id>><callee id>@<valid_from>': UNIQUE (with MANDATORY, since UNIQUE skips a missing
# value), so two writers racing to record one dependency make one edge, whatever the lock does. Retired and re-added
# dependencies between one pair stay apart: they start at different times.
KEYED_EDGES = [("DEPENDS_ON", "key")]
EDGE_CONSTRAINTS = ([("MANDATORY", rel, prop) for rel, prop in DATED_EDGES + KEYED_EDGES]
                    + [("UNIQUE", rel, prop) for rel, prop in KEYED_EDGES])

# The `oncall` user-defined function library (udf/oncall.js), called from Cypher as oncall.<name>(...). UDFs belong to
# the whole database, so one GRAPH.UDF LOAD REPLACE per client (per process) is enough and ships a changed file on the
# next start; a database that lost it (FalkorDB Cloud Free keeps nothing across a restart) gets it again in _run.
_WRITES = re.compile(r"\b(MERGE|CREATE|SET|DELETE|REMOVE)\b")  # a query with any of these is never profiled
WRITE_STATS = ("nodes_created", "relationships_created", "properties_set", "nodes_deleted", "relationships_deleted")
# Two libraries: ours (udf/oncall.js) and FalkorDB's FLEX (udf/flex.js, vendored, MIT), called as flex.<group>.<fn>.
_UDF_DIR = Path(__file__).parent / "udf"
UDF_LIBS = {lib: (_UDF_DIR / f"{lib}.js").read_text() for lib in ("oncall", "flex")}
UDF_LIB, UDF_JS = "oncall", UDF_LIBS["oncall"]
UDF_MISSING = tuple(f"{say}'{lib}." for lib in UDF_LIBS for say in ("Unknown function ", "undefined function: "))
_udf_loaded: "weakref.WeakSet[FalkorDB]" = weakref.WeakSet()
_udf_lock = threading.Lock()


def ensure_udfs(db: FalkorDB) -> None:
    """Load the library once per client, as gently as the server needs: LOAD only when it is missing, REPLACE only
    when the server holds other code (a deploy shipped a changed file), and one thread at a time. Two REPLACEs close
    together while queries run can crash FalkorDB 4.22 (upstream issue #3357), and on Cloud Free a crash loses every
    graph, so a restart's burst of "unknown function" misses must not each reload it."""
    if db in _udf_loaded:
        return
    with _udf_lock:
        if db in _udf_loaded:
            return
        for lib, js in UDF_LIBS.items():
            code = _udf_code(db, lib)
            if code is None:
                try:
                    db.udf_load(lib, js)
                except ResponseError as e:  # another process loaded it a moment ago
                    if "already" not in str(e):
                        raise
            elif code != js:
                db.udf_load(lib, js, replace=True)
        _udf_loaded.add(db)


def _udf_code(db: FalkorDB, lib: str = UDF_LIB) -> str | None:
    """The code the server holds for a library, None when it holds none. GRAPH.UDF LIST answers a map per library,
    which the client hands over as a dict or as a flat key/value list depending on how it connected."""
    rows = db.udf_list(lib, with_code=True)
    if not rows:
        return None
    row = rows[0] if isinstance(rows[0], dict) else dict(zip(rows[0][::2], rows[0][1::2], strict=False))
    code = row.get("library_code", row.get(b"library_code"))
    return code.decode() if isinstance(code, bytes) else code


def _check_tenant(tenant: str) -> str:
    if not _TENANT.fullmatch(tenant):
        raise ValueError("tenant must match [a-z0-9_]{1,40}")
    return tenant


class FalkorRepository:
    def __init__(self, db: FalkorDB, tenant: str, graph: str | None = None, lock_wait: float = 120,
                 coord: Coordination | None = None, read_timeout_ms: int = 0):
        self.tenant = _check_tenant(tenant)
        self._db, self._lock_wait, self._coord = db, lock_wait, coord or Coordination(db)
        self._read_timeout = read_timeout_ms or None
        self._graph = db.select_graph(graph or PREFIX + tenant)

    def scratch(self, name: str) -> "FalkorRepository":
        """A repository on a side graph of this tenant (`scratch_<tenant>_<name>`): a projection built from the
        tenant graph for a graph algorithm to run on (the algorithms see every edge, so the projection holds only the
        edges live at the time in question). Callers drop it with `drop_graph()` when done."""
        return FalkorRepository(self._db, self.tenant, graph=SCRATCH + f"{self.tenant}_{_check_tenant(name)}",
                                lock_wait=self._lock_wait, coord=self._coord,
                                read_timeout_ms=self._read_timeout or 0)

    def drop_graph(self) -> None:
        """Delete this graph (meant for scratch projections; a tenant graph is dropped through the store)."""
        if self._graph.name in self._db.list_graphs():
            self._graph.delete()

    def lock(self, scope: str = ""):
        """One agent run per tenant at a time, across processes (API, MCP, scripts): a lease in the coordination
        graph next to the tenant graphs (coordination.py).
        With a scope, a narrower lock beside it (`oncall_brain:lock:<tenant>:<scope>`, 30 s lease) for a part of the
        graph no agent run touches, such as one engineer's conversation session: its writers queue on it, never on
        the investigation.
        Each write query commits atomically, but MERGE is not a uniqueness guarantee under concurrency: in our test
        (12 clients x 100 concurrent `MERGE (:N {id:7})` on an unconstrained label) FalkorDB created 2 nodes. Node ids
        are now guarded by unique constraints (`_ensure_unique_ids`), and DEPENDS_ON by its UNIQUE key (KEYED_EDGES),
        but the board edges the agents write carry no key, and 12 clients racing `MERGE` on such an edge made a
        duplicate (scripts/concurrency.py). And two concurrent runs
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
        return GraphLock(self._coord, key, ttl=30 if scope else 120, blocking_timeout=self._lock_wait)

    def _run(self, name: str, params: dict[str, Any], readonly: bool) -> QueryRun:
        q = queries.get(name)
        ensure_udfs(self._db)
        t0 = time.perf_counter()
        try:
            res = self._send(q.cypher, params, readonly)
        except ResponseError as e:  # refused at compile time, before anything ran: load the library, run it again
            if not any(m in str(e) for m in UDF_MISSING):
                raise
            _udf_loaded.discard(self._db)
            ensure_udfs(self._db)
            res = self._send(q.cypher, params, readonly)
        ms = (time.perf_counter() - t0) * 1000
        cols = [h[1] if isinstance(h, list | tuple) else h for h in (res.header or [])]
        rows = [dict(zip(cols, r, strict=False)) for r in res.result_set]
        wrote = None if readonly else {k: n for k in WRITE_STATS if (n := getattr(res, k))}
        return QueryRun(name=name, cypher=q.cypher, params=params, rows=rows, ms=round(ms, 2), readonly=readonly,
                        db_ms=round(res.run_time_ms, 3), cached=bool(res.cached_execution), wrote=wrote or None)

    def _send(self, cypher: str, params: dict[str, Any], readonly: bool):
        """Reads go as GRAPH.RO_QUERY with the read timeout (FalkorDB aborts them past it: "Query timed out")."""
        if readonly:
            return self._graph.ro_query(cypher, params, timeout=self._read_timeout)
        return self._graph.query(cypher, params)

    def plan(self, name: str, params: dict[str, Any], profile: bool = False) -> dict[str, Any]:
        """FalkorDB's plan for a named product query, one line per operation: GRAPH.PROFILE (it runs, and each line
        gets its rows and time) for a query with no write clause, GRAPH.EXPLAIN (nothing runs) for any other."""
        q = queries.all_queries().get(name)
        if q is None or q.file == "coordination.cypher":
            raise ValueError(f"no product query named {name!r} (GET /api/queries lists them)")
        ran = profile and not _WRITES.search(q.cypher)
        ensure_udfs(self._db)
        run = self._graph.profile if ran else self._graph.explain
        try:
            try:
                res = run(q.cypher, params)
            except ResponseError as e:  # the database lost a UDF library (a restart): load it, plan again, as _run does
                if not any(m in str(e) for m in UDF_MISSING):
                    raise
                _udf_loaded.discard(self._db)
                ensure_udfs(self._db)
                res = run(q.cypher, params)
        except ResponseError as e:
            if "Missing parameters" not in str(e):
                raise
            needed = sorted(set(re.findall(r"\$(\w+)", q.cypher)) - set(params))
            raise ValueError(f"{name} needs its parameters: {', '.join(needed)}") from None
        return {"kind": "GRAPH.PROFILE" if ran else "GRAPH.EXPLAIN", "ran": ran, "plan": [str(op) for op in res.plan]}

    def read(self, name: str, /, **params: Any) -> QueryRun:
        return self._run(name, params, readonly=True)

    def write(self, name: str, /, **params: Any) -> QueryRun:
        run = self._run(name, params, readonly=False)
        if self._graph.name.startswith(SCRATCH):  # a backstop: a process that dies mid-algorithm never drops it,
            self._db.connection.expire(self._graph.name, SCRATCH_TTL)  # and on Cloud Free every MB counts
        return run

    def ensure_schema(self) -> None:
        """Indexes and the UNIQUE `id` constraints the queries rely on (idempotent; a reset re-runs it)."""
        # Labels and properties come from the constants above, never from input.
        targets = ([(label, "id") for label in INDEXED_LABELS] + [(label, "at") for label in TIME_INDEXED]
                   + PROP_INDEXED)
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
        self._ensure_edge_constraints()

    def _ensure_edge_constraints(self, wait: float = 5.0) -> None:
        """EDGE_CONSTRAINTS (GRAPH.CONSTRAINT CREATE ... MANDATORY|UNIQUE RELATIONSHIP <type> PROPERTIES 1 <prop>),
        created only when missing (creating a constraint while writes run can crash the server: FalkorDB issue #3154)
        and waited for. GRAPH.COPY carries them into pristine copies and resets. A graph from before the dependency
        key gets its keys first (backfill_dependency_keys), else the key constraints would come up FAILED."""
        def have() -> dict[tuple, str]:
            return {(c["type"], c["label"], tuple(c["properties"])): c["status"]
                    for c in self._graph.list_constraints() if c["entitytype"] == "RELATIONSHIP"}
        status = have()
        if any((kind, rel, (prop,)) not in status for kind, rel, prop in EDGE_CONSTRAINTS if prop == "key"):
            self._graph.query(queries.get("backfill_dependency_keys").cypher)
        for kind, rel, prop in EDGE_CONSTRAINTS:
            if (kind, rel, (prop,)) not in status:
                create = (self._graph.create_edge_unique_constraint if kind == "UNIQUE"
                          else self._graph.create_edge_mandatory_constraint)
                create(rel, prop)  # UNIQUE creates the relationship index it needs first
        wanted = {(kind, rel, (prop,)) for kind, rel, prop in EDGE_CONSTRAINTS}
        deadline = time.monotonic() + wait
        while not all((status := have()).get(c) == "OPERATIONAL" for c in wanted):
            if failed := sorted(f"{k} {r}.{p[0]}" for (k, r, p), st in status.items() if st == "FAILED"):
                raise RuntimeError(f"edge constraint failed: {', '.join(failed)} (an edge breaks it; re-seed)")
            if time.monotonic() > deadline:
                raise RuntimeError(f"edge constraints still not operational after {wait} s: {status}")
            time.sleep(0.02)

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
                 password: str | None = None, ssl: bool = False, url: str = "", lock_wait: float = 120,
                 read_timeout_ms: int = 0):
        self.db = (FalkorDB.from_url(url) if url
                   else FalkorDB(host=host, port=port, username=username, password=password, ssl=ssl,
                                 ssl_check_hostname=ssl))  # the falkordb client defaults this to False
        self.lock_wait, self.coord, self.read_timeout_ms = lock_wait, Coordination(self.db), read_timeout_ms

    def tenant(self, tenant: str) -> FalkorRepository:
        return FalkorRepository(self.db, tenant, lock_wait=self.lock_wait, coord=self.coord,
                                read_timeout_ms=self.read_timeout_ms)

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

    def staging(self, tenant: str) -> FalkorRepository:
        """An empty graph beside the tenant (`seeding_<tenant>`) for a seed to be built on; publish() swaps it in."""
        name = SEEDING + _check_tenant(tenant)
        if name in self._names():
            self.db.select_graph(name).delete()
        return FalkorRepository(self.db, tenant, graph=name, lock_wait=self.lock_wait, coord=self.coord,
                                read_timeout_ms=self.read_timeout_ms)

    def publish(self, tenant: str) -> None:
        """The staged graph becomes the pristine copy (GRAPH.COPY) and then the tenant graph (RENAME, atomic)."""
        staging = SEEDING + _check_tenant(tenant)
        if PRISTINE + tenant in self._names():
            self.db.select_graph(PRISTINE + tenant).delete()
        self._copy(staging, PRISTINE + tenant)
        self.db.connection.execute_command("RENAME", staging, PREFIX + tenant)

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
        # The schema is brought up to date on the pristine graph, where no query ever writes, so a copy made before
        # an index or constraint existed gets it once, and a constraint is never built under live writes (#3154).
        FalkorRepository(self.db, tenant, graph=PRISTINE + tenant, coord=self.coord).ensure_schema()
        try:
            self._copy(PRISTINE + tenant, staging)
        except ResponseError:
            return False  # caller re-seeds from scratch
        self.db.connection.execute_command("RENAME", staging, PREFIX + tenant)
        return True

    def lock(self, tenant: str):
        return self.tenant(tenant).lock()

    def incr(self, key: str, ttl: int, by: int = 1) -> int:
        """A counter in the coordination graph, so the app and a standalone MCP process share it and it survives
        restarts."""
        return self.coord.incr(key, ttl, by)

    def counter(self, key: str) -> int:
        return self.coord.counter(key)

    def claim(self, key: str, ttl: float) -> bool:
        """Mark `key` taken for `ttl` seconds; False if it already is (Slack's replay guard and pending run)."""
        return self.coord.claim(key, ttl)

    def unclaim(self, key: str) -> None:
        self.coord.release(key)

    def clone_pristine(self, tenant: str, into: str, ttl: int = 0) -> bool:
        """Copy the tenant's pristine graph into another tenant's slot (for what-if replays). False if none. With a
        ttl, the copy expires after that many seconds even if the process that made it dies before dropping it."""
        if PRISTINE + _check_tenant(tenant) not in self._names():
            return False
        self.drop(into)
        self._copy(PRISTINE + tenant, PREFIX + _check_tenant(into))
        if ttl:
            self.db.connection.expire(PREFIX + into, ttl)
        return True

    def drop(self, tenant: str) -> None:
        names = self._names()
        scratch = [n for n in names if n.startswith(SCRATCH + _check_tenant(tenant) + "_")]
        for name in (PREFIX + tenant, PRISTINE + tenant, RESTORING + tenant, SEEDING + tenant, *scratch):
            if name in names:
                self.db.select_graph(name).delete()
