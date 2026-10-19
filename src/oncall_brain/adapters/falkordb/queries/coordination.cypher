// name: coord_claim
// purpose: Take a lease: the agent-run lock on a tenant, a Slack replay marker, a pending Slack run. Runs on the coordination graph `oncall_brain_coord`, where a UNIQUE constraint on Lease.key makes this CREATE fail while anyone holds the key, so exactly one of any number of concurrent claimers wins (16 racing clients, one winner, every round, on FalkorDB Cloud too).
CREATE (:Lease {key: $key, owner: $owner, exp: timestamp() + $ms})

// name: coord_expire
// purpose: Clear a lease its holder let lapse (a run that died mid-way), so the next claimer can take it. Only an expired one: a live holder never loses its lease.
MATCH (l:Lease {key: $key})
WHERE l.exp <= timestamp()
DELETE l

// name: coord_renew
// purpose: The holder extends its lease; respond() does this on every agent step, so a long run keeps its tenant. No row back: the lease lapsed and the run no longer holds the lock.
WITH timestamp() AS now
MATCH (l:Lease {key: $key, owner: $owner})
WHERE l.exp > now
SET l.exp = now + $ms
RETURN l.exp AS exp

// name: coord_release
// purpose: The holder lets go. The owner check means a holder whose lease lapsed cannot free the next holder's.
MATCH (l:Lease {key: $key, owner: $owner})
DELETE l

// name: coord_held
// purpose: Whether a key is held right now (Slack answers "busy" at once instead of queueing behind a run).
MATCH (l:Lease {key: $key})
WHERE l.exp > timestamp()
RETURN count(l) AS held

// name: coord_incr
// purpose: Add to a counter every process shares (the throttles, the hourly and daily LLM token budget) and return the new value. One write query, which FalkorDB applies atomically: 16 concurrent writers lost no increment. A counter past its expiry starts again from zero.
// timestamp() is the server clock and is read again on every call: read it once.
WITH timestamp() AS now
MERGE (c:Counter {key: $key})
ON CREATE SET c.n = 0, c.exp = now + $ms
WITH c, now, c.exp <= now AS stale
SET c.n = CASE WHEN stale THEN 0 ELSE c.n END + $by,
    c.exp = CASE WHEN stale THEN now + $ms ELSE c.exp END
RETURN c.n AS n

// name: coord_counter
// purpose: A counter's current value; no row when it does not exist or has expired.
MATCH (c:Counter {key: $key})
WHERE c.exp > timestamp()
RETURN c.n AS n

// name: coord_sweep
// purpose: Delete expired leases and counters, so the coordination graph stays a few hundred nodes however long the site runs.
MATCH (n)
WHERE n.exp <= timestamp()
DELETE n

// name: coord_dedupe_leases
// purpose: Repair before a UNIQUE constraint can be built again: after a database restart, claims made before the watchdog restored the constraint can leave two Lease nodes with one key (the constraint then comes up FAILED). Keep the one that lasts longest.
MATCH (n:Lease)
WITH n.key AS key, n ORDER BY n.exp DESC
WITH key, collect(n) AS ns
WHERE size(ns) > 1
UNWIND ns[1..] AS extra
DELETE extra

// name: coord_dedupe_counters
// purpose: The same repair for Counter nodes: two counters with one key are merged into the first, so no count is lost.
MATCH (n:Counter)
WITH n.key AS key, collect(n) AS ns
WHERE size(ns) > 1
WITH ns[0] AS keep, ns[1..] AS extra
SET keep.n = keep.n + reduce(t = 0, x IN extra | t + x.n)
WITH extra
UNWIND extra AS x
DELETE x

// name: coord_runs_in_flight
// purpose: How many agent runs hold a tenant right now: live leases on oncall_brain:lock:<tenant> (a scoped lock, oncall_brain:lock:<tenant>:<scope>, is no run). deploy/aws/host.sh waits for this to reach 0 before it restarts the app.
MATCH (l:Lease)
WHERE l.key STARTS WITH 'oncall_brain:lock:' AND size(split(l.key, ':')) = 3 AND l.exp > timestamp()
RETURN count(l) AS runs
