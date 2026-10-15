// name: recall_similar
// purpose: Episodic recall by structure, not text: resolved incidents whose root-cause service is on the alerting service's live dependency path. Same symptom scores higher.
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

// name: record_recalls
// purpose: Link the incident to the past incidents it recalled (memory the planner reads back).
UNWIND $rows AS r
MATCH (i:Incident {id: $incident_id}), (past:Incident {id: r.incident})
MERGE (i)-[x:RECALLS]->(past)
ON CREATE SET x.score = r.score, x.cause_service = r.cause_service

// name: memory_suspects
// purpose: Procedural shortcut: changes in the alert window on services that caused the recalled incidents.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
MATCH (i)-[x:RECALLS]->(past:Incident)-[:CAUSED_BY]->(:Change)-[:CHANGED]->(cs:Service)
WHERE x.score >= $min_score
MATCH (c:Change)-[:CHANGED]->(cs)
WHERE c.at >= a.at - $window AND c.at <= a.at
MATCH p = (o)-[:DEPENDS_ON*0..6]->(cs)
WHERE all(r IN relationships(p) WHERE r.valid_from <= a.at AND (r.valid_to IS NULL OR r.valid_to > a.at))
RETURN c.id AS change, cs.id AS service, c.kind AS kind, c.at AS at, min(length(p)) AS hops,
       collect(DISTINCT past.id) AS recalled

// name: path_suspects
// purpose: Multi-hop suspects: every change in the alert window on a service the alerting service depends on at alert time, nearest first.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
MATCH p = (o)-[:DEPENDS_ON*0..6]->(s:Service)
WHERE all(r IN relationships(p) WHERE r.valid_from <= a.at AND (r.valid_to IS NULL OR r.valid_to > a.at))
WITH a, s, min(length(p)) AS hops
MATCH (c:Change)-[:CHANGED]->(s)
WHERE c.at >= a.at - $window AND c.at <= a.at
RETURN c.id AS change, s.id AS service, c.kind AS kind, c.at AS at, c.summary AS summary, hops
ORDER BY hops, at DESC

// name: recent_changes
// purpose: The flat baseline: newest changes anywhere before the alert, no traversal. This is what a change log alone would blame.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)
MATCH (c:Change)-[:CHANGED]->(s:Service)
WHERE c.at >= a.at - $window AND c.at <= a.at
RETURN c.id AS change, s.id AS service, c.kind AS kind, c.at AS at, c.summary AS summary
ORDER BY at DESC
LIMIT 3

// name: add_hypotheses
// purpose: Put suspects on the board as open Hypothesis nodes (idempotent per incident + change).
UNWIND $rows AS r
MATCH (i:Incident {id: $incident_id}), (c:Change {id: r.change})
MERGE (h:Hypothesis {id: r.id})
ON CREATE SET h.status = 'open', h.source = r.source, h.hops = r.hops, h.created_at = $at
MERGE (i)-[:HAS_HYPOTHESIS]->(h)
MERGE (h)-[:SUSPECTS]->(c)
RETURN h.id AS id

// name: hypothesis_facts
// purpose: What a check needs about one suspect: changed service, change time, rollback, alerting service and time.
MATCH (i:Incident)-[:HAS_HYPOTHESIS]->(h:Hypothesis {id: $hypothesis_id})-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
MATCH (i)-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
RETURN i.id AS incident, h.status AS status, c.id AS change, c.summary AS summary, c.at AS change_at,
       c.rolled_back_at AS rolled_back_at, s.id AS service, o.id AS origin, a.at AS at

// name: live_path
// purpose: Shortest dependency path from the alerting service to a suspect's service, using only edges valid at alert time.
MATCH p = (:Service {id: $origin})-[:DEPENDS_ON*0..6]->(:Service {id: $target})
WHERE all(r IN relationships(p) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at))
WITH p
ORDER BY length(p)
LIMIT 1
RETURN [n IN nodes(p) | n.id] AS path

// name: live_paths
// purpose: Up to 20 live dependency paths (edges valid at alert time) from the alerting service to a suspect's service, shortest first; the check picks the one the anomaly actually travelled.
MATCH p = (:Service {id: $origin})-[:DEPENDS_ON*0..6]->(:Service {id: $target})
WHERE all(r IN relationships(p) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at))
WITH p
ORDER BY length(p)
LIMIT 20
RETURN [n IN nodes(p) | n.id] AS path

// name: any_path
// purpose: shortestPath ignoring validity, to tell a retired dependency apart from no dependency at all.
MATCH (o:Service {id: $origin}), (t:Service {id: $target})
WITH shortestPath((o)-[:DEPENDS_ON*]->(t)) AS p
WHERE p IS NOT NULL
RETURN [n IN nodes(p) | n.id] AS path, [r IN relationships(p) | r.valid_to] AS retired_at

// name: anomalies_between
// purpose: Which of the given services showed an anomaly between the change and the alert.
UNWIND $services AS sid
MATCH (x:Anomaly)-[:ON]->(s:Service {id: sid})
WHERE x.at >= $since AND x.at <= $until
RETURN s.id AS service, min(x.at) AS first_at, collect(x.summary)[0] AS summary

// name: record_evidence
// purpose: Attach a check's verdict as an Evidence node (SUPPORTS / REFUTES the hypothesis) and update the hypothesis status.
MATCH (h:Hypothesis {id: $hypothesis_id})
MERGE (e:Evidence {id: $evidence_id})
SET e.verdict = $verdict, e.reason = $reason, e.path = $path, e.at = $at
SET h.status = CASE $verdict WHEN 'supports' THEN 'supported' WHEN 'refutes' THEN 'refuted' ELSE 'inconclusive' END
FOREACH (_ IN CASE WHEN $verdict = 'supports' THEN [1] ELSE [] END | MERGE (e)-[:SUPPORTS]->(h))
FOREACH (_ IN CASE WHEN $verdict = 'refutes' THEN [1] ELSE [] END | MERGE (e)-[:REFUTES]->(h))
RETURN h.id AS hypothesis, h.status AS status
