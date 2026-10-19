"""Locks, leases and shared counters as nodes in one FalkorDB graph (`oncall_brain_coord`), not Redis keys.

FalkorDB Cloud's users get the graph commands and a few key commands (RENAME, DEL, EXPIRE, MULTI), but never the
string, counter or scripting ones (SET, GET, INCR, EVAL), so everything the processes share lives in a graph next to
the tenant graphs, and the product needs nothing from the database but FalkorDB itself. Two database guarantees
carry it, both checked on Cloud with 16 racing clients (tests/integration/test_coordination.py):
- a UNIQUE constraint on Lease.key, so of any number of concurrent `CREATE (:Lease {key})` exactly one succeeds:
  that is the mutex;
- each write query applies atomically, so `SET c.n = c.n + $by` loses no increment.
Expiry runs on the server's clock (`timestamp()`), so processes on different machines agree on it.
"""

import contextlib
import itertools
import logging
import time
import uuid

from redis.exceptions import LockError, LockNotOwnedError, RedisError, ResponseError

from oncall_brain.adapters.falkordb import queries

GRAPH = "oncall_brain_coord"
_LABELS = ("Lease", "Counter")
SWEEP_EVERY = 500  # writes between sweeps of expired nodes
log = logging.getLogger(__name__)


def _taken(e: ResponseError) -> bool:
    return "unique constraint" in str(e)


class Coordination:
    def __init__(self, db):
        self._db, self._g, self._writes = db, None, itertools.count(1)  # _g is set once the constraints are up

    def _setup(self):
        """The coordination graph, with the UNIQUE constraints everything here rests on, checked once per process
        (and again by recheck) and waited for: a claim made while one is still PENDING would not be exclusive."""
        if g := self._g:
            return g
        g = self._db.select_graph(GRAPH)
        deadline, created, repaired = time.monotonic() + 10, set(), set()
        while True:
            have = ({c["label"]: c["status"] for c in g.list_constraints()
                     if c["type"] == "UNIQUE" and list(c["properties"]) == ["key"]}
                    if GRAPH in self._db.list_graphs() else {})
            if all(have.get(label) == "OPERATIONAL" for label in _LABELS):
                break
            # Create what is missing, once per label: GRAPH.CONSTRAINT CREATE bypasses the graph's write queue, and
            # overlapping it with writes can crash the server (FalkorDB issue #3154), so a process that finds the
            # constraints in place never issues it. FAILED (now or after our own create): claims made after a
            # database restart, before this check, left two nodes with one key; remove the extra ones, drop the
            # failed constraint and build it again, once per label.
            for label in _LABELS:
                status = have.get(label)
                if status == "FAILED" and label not in repaired:
                    log.warning("coordination: the %s constraint FAILED (duplicates after a restart): repairing", label)
                    g.query(queries.get(f"coord_dedupe_{label.lower()}s").cypher)
                    g.drop_node_unique_constraint(label, "key")
                    repaired.add(label)
                    created.discard(label)
                    status = None
                if status is None and label not in created:
                    try:
                        g.create_node_unique_constraint(label, "key")  # creates the range index it needs first
                    except ResponseError as e:  # another process got there first
                        if "already exists" not in str(e):
                            raise
                    created.add(label)
            if time.monotonic() > deadline:
                raise RuntimeError(f"coordination constraints not operational: {have}")
            time.sleep(0.02)
        self._g = g
        return g

    def recheck(self) -> None:
        """Check the constraints again (serve.py's watchdog, once a minute). FalkorDB Cloud Free keeps nothing
        across a restart, and the first claim after one would recreate this graph without its constraints, so
        leases would stop being exclusive until the next check."""
        # ponytail: a minute without exclusive leases after a database restart; check per claim if that matters.
        self._g = None
        self._setup()

    def _write(self, name: str, **params):
        g = self._setup()
        res = g.query(queries.get(name).cypher, params)
        if next(self._writes) % SWEEP_EVERY == 0:  # housekeeping: its failure must not fail the write that committed
            with contextlib.suppress(RedisError):
                g.query(queries.get("coord_sweep").cypher)
        return res

    def _read(self, name: str, **params) -> list:
        return self._setup().ro_query(queries.get(name).cypher, params).result_set

    def claim(self, key: str, ttl: float, owner: str = "") -> bool:
        """Take `key` for `ttl` seconds unless someone holds it (Redis's SET NX EX). An expired lease is cleared and
        claimed again in the same call."""
        for _ in range(2):
            try:
                self._write("coord_claim", key=key, owner=owner, ms=int(ttl * 1000))
                return True
            except ResponseError as e:
                if not _taken(e):
                    raise
            if not self._write("coord_expire", key=key).nodes_deleted:
                return False
        return False

    def renew(self, key: str, owner: str, ttl: float) -> bool:
        return bool(self._write("coord_renew", key=key, owner=owner, ms=int(ttl * 1000)).result_set)

    def release(self, key: str, owner: str = "") -> None:
        self._write("coord_release", key=key, owner=owner)

    def runs_in_flight(self) -> int:
        """Agent runs holding a tenant now (deploy/aws/host.sh waits for 0 before restarting the app)."""
        return int(self._read("coord_runs_in_flight")[0][0])

    def held(self, key: str) -> bool:
        return bool(self._read("coord_held", key=key)[0][0])

    def incr(self, key: str, ttl: int, by: int = 1) -> int:
        try:
            return int(self._write("coord_incr", key=key, ms=ttl * 1000, by=by).result_set[0][0])
        except ResponseError as e:  # two first writers raced the MERGE: the constraint refused one, which now matches
            if not _taken(e):
                raise
            return int(self._write("coord_incr", key=key, ms=ttl * 1000, by=by).result_set[0][0])

    def counter(self, key: str) -> int:
        rows = self._read("coord_counter", key=key)
        return int(rows[0][0]) if rows else 0


class GraphLock:
    """The parts of redis-py's Lock the product uses (a lease taken with a bounded wait, renewed by its holder,
    LockError when the wait runs out), on a Lease node."""

    def __init__(self, coord: Coordination, key: str, ttl: float, blocking_timeout: float, sleep: float = 0.01):
        self.coord, self.key, self.ttl, self.wait, self.sleep = coord, key, ttl, blocking_timeout, sleep
        self.token: str | None = None

    def acquire(self, blocking: bool = True) -> bool:
        token, deadline = uuid.uuid4().hex, time.monotonic() + self.wait
        while not self.coord.claim(self.key, self.ttl, token):
            if not blocking or time.monotonic() >= deadline:
                return False
            time.sleep(self.sleep)
        self.token = token
        return True

    def release(self) -> None:
        if self.token:
            self.coord.release(self.key, self.token)
            self.token = None

    def reacquire(self) -> None:
        if not (self.token and self.coord.renew(self.key, self.token, self.ttl)):
            raise LockNotOwnedError(f"the lease on {self.key} lapsed; another run may hold it now")

    def locked(self) -> bool:
        return self.coord.held(self.key)

    def __enter__(self) -> "GraphLock":
        if not self.acquire():
            raise LockError("Unable to acquire lock within the time specified")
        return self

    def __exit__(self, *exc) -> None:
        self.release()
