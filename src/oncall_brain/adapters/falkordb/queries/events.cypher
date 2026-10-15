// name: record_change
// purpose: Keep knowledge current: record a deploy or config change as it happens (idempotent on id).
MATCH (s:Service {id: $service})
MERGE (c:Change {id: $id})
SET c.kind = $kind, c.summary = $summary, c.at = $at, c.rolled_back_at = $rolled_back_at
MERGE (c)-[:CHANGED]->(s)
WITH c
OPTIONAL MATCH (p:Person {id: $author})
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (c)-[:AUTHORED_BY]->(x))
RETURN c.id AS change

// name: record_anomaly
// purpose: Keep knowledge current: record a monitoring anomaly on a service.
MATCH (s:Service {id: $service})
MERGE (x:Anomaly {id: $id})
SET x.kind = $kind, x.summary = $summary, x.at = $at
MERGE (x)-[:ON]->(s)
RETURN x.id AS anomaly

// name: raise_alert
// purpose: Record an alert on a service so the agents can respond to it.
MATCH (s:Service {id: $service})
MERGE (a:Alert {id: $id})
SET a.name = $alert_name, a.symptom = $symptom, a.at = $at
MERGE (a)-[:FIRED_ON]->(s)
RETURN a.id AS alert

// name: add_dependency
// purpose: Keep knowledge current: caller starts depending on callee at $at (a new temporal DEPENDS_ON edge).
MATCH (a:Service {id: $caller}), (b:Service {id: $callee})
MERGE (a)-[d:DEPENDS_ON {valid_from: $at}]->(b)
RETURN a.id AS caller, b.id AS callee, d.valid_from AS valid_from

// name: retire_dependency
// purpose: Keep knowledge current: close the live caller -> callee dependency at $at (history is kept; queries at later times stop using it).
MATCH (:Service {id: $caller})-[d:DEPENDS_ON]->(:Service {id: $callee})
WHERE d.valid_to IS NULL AND d.valid_from <= $at
SET d.valid_to = $at
RETURN count(d) AS retired
