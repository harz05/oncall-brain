// name: path_suspects_reference
// purpose: Reference implementation (the pre-rewrite, path-enumerating path_suspects, plus the storm rule the rewrite has: a change on a folded alert's live paths counts too, at the origin's distance when the origin reaches it, else at the nearest folded alert's): used only by tests/integration/test_query_equivalence.py and scripts/bench.py, never by the product.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o0:Service)
OPTIONAL MATCH (i)-[:CORRELATED_WITH]->(:Alert)-[:FIRED_ON]->(cs:Service)
WITH a, o0, collect(DISTINCT cs) AS folded
WITH a, o0, [o0] + folded AS origins
UNWIND origins AS o
WITH DISTINCT a, o0, o
MATCH p = (o)-[:DEPENDS_ON*0..6]->(s:Service)
WHERE all(r IN relationships(p) WHERE r.valid_from <= a.at AND (r.valid_to IS NULL OR r.valid_to > a.at))
WITH a, o0, o, s, min(length(p)) AS hops
WITH a, s, min(CASE WHEN o = o0 THEN hops END) AS own, min(hops) AS nearest
WITH a, s, coalesce(own, nearest) AS hops
MATCH (c:Change)-[:CHANGED]->(s)
WHERE c.at >= a.at - $window AND c.at <= a.at
RETURN c.id AS change, s.id AS service, c.kind AS kind, c.at AS at, c.summary AS summary, hops
ORDER BY hops, at DESC, change

// name: memory_suspects_reference
// purpose: Reference implementation (the pre-rewrite memory_suspects, kept verbatim): used only by tests/integration/test_query_equivalence.py and scripts/bench.py, never by the product.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
MATCH (i)-[x:RECALLS]->(past:Incident)-[:FIXED_WITH]->(rb:Runbook)-[:FOR_SERVICE]->(cs:Service)
WHERE x.score >= $min_score
MATCH (c:Change {kind: rb.kind})-[:CHANGED]->(cs)
WHERE c.at >= a.at - $window AND c.at <= a.at
MATCH p = (o)-[:DEPENDS_ON*0..6]->(cs)
WHERE all(r IN relationships(p) WHERE r.valid_from <= a.at AND (r.valid_to IS NULL OR r.valid_to > a.at))
RETURN c.id AS change, cs.id AS service, c.kind AS kind, c.at AS at, min(length(p)) AS hops,
       rb.id AS runbook, rb.title AS runbook_title, rb.successes AS successes, rb.uses AS uses,
       collect(DISTINCT past.id) AS recalled
ORDER BY toFloat(successes) / uses DESC, at DESC

// name: recall_similar_reference
// purpose: Reference implementation (the pre-rewrite recall_similar, kept verbatim): used only by tests/integration/test_query_equivalence.py and scripts/bench.py, never by the product.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
MATCH (past:Incident {status: 'resolved'})-[:CAUSED_BY]->(c:Change)-[:CHANGED]->(cs:Service)
WHERE past.opened_at < a.at AND past.id <> i.id
MATCH p = (o)-[:DEPENDS_ON*0..6]->(cs)
WHERE all(r IN relationships(p) WHERE r.valid_from <= a.at AND (r.valid_to IS NULL OR r.valid_to > a.at))
WITH past, c, cs, a, min(length(p)) AS hops
OPTIONAL MATCH (past)-[:FIXED_WITH]->(rb:Runbook)
RETURN past.id AS incident, past.title AS title, past.symptom AS symptom, cs.id AS cause_service,
       c.kind AS cause_kind, c.id AS cause_change, hops, rb.id AS runbook, rb.title AS runbook_title,
       2 + CASE WHEN past.symptom = a.symptom THEN 1 ELSE 0 END AS score
ORDER BY score DESC, past.opened_at DESC
LIMIT 5

// name: live_paths_reference
// purpose: Reference implementation (the pre-rewrite live_paths, kept verbatim): used only by tests/integration/test_query_equivalence.py and scripts/bench.py, never by the product.
MATCH p = (:Service {id: $origin})-[:DEPENDS_ON*0..6]->(:Service {id: $target})
WHERE all(r IN relationships(p) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at))
WITH p
ORDER BY length(p)
LIMIT 20
RETURN [n IN nodes(p) | n.id] AS path

// name: storm_unexplained_reference
// purpose: Reference implementation (the pre-rewrite storm_unexplained, kept verbatim): used only by tests/integration/test_query_equivalence.py and scripts/bench.py, never by the product.
UNWIND $services AS sid
OPTIONAL MATCH p = (:Service {id: sid})-[:DEPENDS_ON*0..6]->(:Service {id: $target})
WHERE all(r IN relationships(p) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at))
WITH sid, count(p) AS paths
WHERE paths = 0
RETURN sid AS service

// name: depends_among_reference
// purpose: Reference implementation (the pre-rewrite depends_among, kept verbatim): used only by tests/integration/test_query_equivalence.py and scripts/bench.py, never by the product.
MATCH (a:Service), (b:Service)
WHERE a.id IN $services AND b.id IN $services AND a.id <> b.id
MATCH p = (a)-[:DEPENDS_ON*1..6]->(b)
WHERE all(r IN relationships(p) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at))
RETURN DISTINCT a.id AS service, b.id AS upstream

// name: blast_radius_reference
// purpose: Reference implementation (the pre-rewrite blast_radius, kept verbatim): used only by tests/integration/test_query_equivalence.py and scripts/bench.py, never by the product.
MATCH p = (caller:Service)-[:DEPENDS_ON*1..6]->(:Service {id: $service})
WHERE all(r IN relationships(p) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at))
WITH caller, p
ORDER BY length(p)
WITH caller, collect(p)[0] AS p
MATCH (t:Team)-[o:OWNS]->(caller)
WHERE coalesce(o.valid_from, 0) <= $at AND (o.valid_to IS NULL OR o.valid_to > $at)
RETURN caller.id AS service, caller.tier AS tier, length(p) AS hops, t.name AS team, [n IN nodes(p) | n.id] AS path
ORDER BY hops, service

// name: storm_upstream_reference
// purpose: Reference implementation (the pre-rewrite storm_upstream, kept verbatim): used only by tests/integration/test_query_equivalence.py and scripts/bench.py, never by the product.
UNWIND $services AS sid
MATCH p = (:Service {id: sid})-[:DEPENDS_ON*0..6]->(u:Service)
WHERE all(r IN relationships(p) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at))
WITH u, sid, min(length(p)) AS hops
RETURN u.id AS service, sid AS alerting, hops,
       size([(x:Anomaly)-[:ON]->(u) WHERE x.at >= $since AND x.at <= $at | x]) > 0 AS red

// name: blast_radius_cypher
// purpose: The pure-Cypher form of blast_radius that shipped before the user-defined function: the same breadth-first search unrolled into six CALL {} levels. Kept for scripts/bench.py, which times it against the function and against blast_radius_reference; never used by the product.
MATCH (target:Service {id: $service})
WITH [[target]] AS f0
// Breadth-first against the edge direction, one hop per CALL, over edges live at $at: level k lists one path
// [caller, ..., target] per caller k hops away, so each service is expanded once per level instead of once per path.
// A caller keeps its path through its first parent in level order, and callers are ordered by that parent, then by
// id descending: the order a depth-first traversal meets them, so ties pick the same path the plain
// (caller)-[:DEPENDS_ON*1..6]->(target) query does (queries/reference.cypher).
CALL { WITH f0 UNWIND range(0, size(f0) - 1) AS i WITH i, f0[i] AS path, f0[i][0] AS x
       MATCH (n:Service)-[r:DEPENDS_ON]->(x) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)
       WITH n, min(i) AS first, collect(path)[0] AS path ORDER BY first, id(n) DESC
       RETURN collect([n] + path) AS f1 }
CALL { WITH f1 UNWIND range(0, size(f1) - 1) AS i WITH i, f1[i] AS path, f1[i][0] AS x
       MATCH (n:Service)-[r:DEPENDS_ON]->(x) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)
       WITH n, min(i) AS first, collect(path)[0] AS path ORDER BY first, id(n) DESC
       RETURN collect([n] + path) AS f2 }
CALL { WITH f2 UNWIND range(0, size(f2) - 1) AS i WITH i, f2[i] AS path, f2[i][0] AS x
       MATCH (n:Service)-[r:DEPENDS_ON]->(x) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)
       WITH n, min(i) AS first, collect(path)[0] AS path ORDER BY first, id(n) DESC
       RETURN collect([n] + path) AS f3 }
CALL { WITH f3 UNWIND range(0, size(f3) - 1) AS i WITH i, f3[i] AS path, f3[i][0] AS x
       MATCH (n:Service)-[r:DEPENDS_ON]->(x) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)
       WITH n, min(i) AS first, collect(path)[0] AS path ORDER BY first, id(n) DESC
       RETURN collect([n] + path) AS f4 }
CALL { WITH f4 UNWIND range(0, size(f4) - 1) AS i WITH i, f4[i] AS path, f4[i][0] AS x
       MATCH (n:Service)-[r:DEPENDS_ON]->(x) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)
       WITH n, min(i) AS first, collect(path)[0] AS path ORDER BY first, id(n) DESC
       RETURN collect([n] + path) AS f5 }
CALL { WITH f5 UNWIND range(0, size(f5) - 1) AS i WITH i, f5[i] AS path, f5[i][0] AS x
       MATCH (n:Service)-[r:DEPENDS_ON]->(x) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)
       WITH n, min(i) AS first, collect(path)[0] AS path ORDER BY first, id(n) DESC
       RETURN collect([n] + path) AS f6 }
// A service can come back at a later level (a longer walk); its first level is its distance.
UNWIND [f1, f2, f3, f4, f5, f6] AS level
UNWIND level AS path
WITH path[0] AS caller, collect(path)[0] AS path
MATCH (t:Team)-[o:OWNS]->(caller)
WHERE coalesce(o.valid_from, 0) <= $at AND (o.valid_to IS NULL OR o.valid_to > $at)
RETURN caller.id AS service, caller.tier AS tier, size(path) - 1 AS hops, t.name AS team, [n IN path | n.id] AS path
ORDER BY hops, service
