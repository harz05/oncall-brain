// name: recall_similar
// purpose: Episodic recall by structure, not text: resolved incidents whose root-cause service is on the alerting service's live dependency path. Same symptom scores higher.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
MATCH (past:Incident {status: 'resolved'})-[:CAUSED_BY]->(c:Change)-[:CHANGED]->(s:Service)
WHERE past.opened_at < a.at AND past.id <> i.id
WITH o, s, a.at AS alert_at, a, past, c
CALL {
  // Live hops o -> s (same block as path_suspects, which explains it).
  WITH o, s, alert_at
  WITH o, s, alert_at, shortestPath((o)-[:DEPENDS_ON*0..6]->(s)) AS sp
  WHERE sp IS NOT NULL
  WITH o, s, alert_at, sp,
       all(r IN relationships(sp) WHERE r.valid_from <= alert_at AND (r.valid_to IS NULL OR r.valid_to > alert_at)) AS live
  OPTIONAL MATCH p = (o)-[e:DEPENDS_ON*0..6]->(s)
  WHERE NOT live AND e.valid_from <= alert_at AND (e.valid_to IS NULL OR e.valid_to > alert_at)
  WITH live, sp, min(length(p)) AS shortest_live
  WITH CASE WHEN live THEN length(sp) ELSE shortest_live END AS hops
  WHERE hops IS NOT NULL
  RETURN hops
}
OPTIONAL MATCH (past)-[:FIXED_WITH]->(rb:Runbook)
RETURN past.id AS incident, past.title AS title, past.symptom AS symptom, s.id AS cause_service,
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
// purpose: Procedural memory decides: for each recalled incident, the runbook that fixed it names a service and a change kind; suspect in-window changes of that kind on that service, most trusted runbook first.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
MATCH (i)-[x:RECALLS]->(past:Incident)-[:FIXED_WITH]->(rb:Runbook)-[:FOR_SERVICE]->(s:Service)
WHERE x.score >= $min_score
MATCH (c:Change {kind: rb.kind})-[:CHANGED]->(s)
WHERE c.at >= a.at - $window AND c.at <= a.at
WITH o, s, a.at AS alert_at, past, rb, c
CALL {
  // Live hops o -> s (same block as path_suspects, which explains it).
  WITH o, s, alert_at
  WITH o, s, alert_at, shortestPath((o)-[:DEPENDS_ON*0..6]->(s)) AS sp
  WHERE sp IS NOT NULL
  WITH o, s, alert_at, sp,
       all(r IN relationships(sp) WHERE r.valid_from <= alert_at AND (r.valid_to IS NULL OR r.valid_to > alert_at)) AS live
  OPTIONAL MATCH p = (o)-[e:DEPENDS_ON*0..6]->(s)
  WHERE NOT live AND e.valid_from <= alert_at AND (e.valid_to IS NULL OR e.valid_to > alert_at)
  WITH live, sp, min(length(p)) AS shortest_live
  WITH CASE WHEN live THEN length(sp) ELSE shortest_live END AS hops
  WHERE hops IS NOT NULL
  RETURN hops
}
RETURN c.id AS change, s.id AS service, c.kind AS kind, c.at AS at, hops,
       rb.id AS runbook, rb.title AS runbook_title, rb.successes AS successes, rb.uses AS uses,
       collect(DISTINCT past.id) AS recalled
ORDER BY toFloat(successes) / uses DESC, at DESC

// name: path_suspects
// purpose: Multi-hop suspects: every change in the alert window on a service the alerting service depends on at alert time, nearest first. Starts from the few in-window changes (Change.at range index), not from every dependency path.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
WITH o, a.at AS alert_at
MATCH (c:Change)
WHERE c.at >= alert_at - $window AND c.at <= alert_at
MATCH (c)-[:CHANGED]->(s:Service)
WITH o, s, alert_at, collect(c) AS changes
CALL {
  // Live hops o -> s: the fewest DEPENDS_ON hops (0..6) over edges valid at alert_at, without listing paths.
  // shortestPath ignores validity, so it is only a lower bound: kept when every edge on it is live at alert_at.
  // When it crosses a retired (or not yet live) edge, the traversal with the validity test on each hop (FalkorDB
  // checks a WHERE on the variable-length edge `e` per hop, inside the traversal) settles it, for this pair only.
  WITH o, s, alert_at
  WITH o, s, alert_at, shortestPath((o)-[:DEPENDS_ON*0..6]->(s)) AS sp
  WHERE sp IS NOT NULL
  WITH o, s, alert_at, sp,
       all(r IN relationships(sp) WHERE r.valid_from <= alert_at AND (r.valid_to IS NULL OR r.valid_to > alert_at)) AS live
  OPTIONAL MATCH p = (o)-[e:DEPENDS_ON*0..6]->(s)
  WHERE NOT live AND e.valid_from <= alert_at AND (e.valid_to IS NULL OR e.valid_to > alert_at)
  WITH live, sp, min(length(p)) AS shortest_live
  WITH CASE WHEN live THEN length(sp) ELSE shortest_live END AS hops
  WHERE hops IS NOT NULL
  RETURN hops
}
UNWIND changes AS c
RETURN c.id AS change, s.id AS service, c.kind AS kind, c.at AS at, c.summary AS summary, hops
ORDER BY hops, at DESC, change

// name: recent_changes
// purpose: The flat baseline: newest changes anywhere before the alert, no traversal. This is what a change log alone would blame. ($since/$until are literal bounds so the Change.at range index is used.)
MATCH (c:Change)-[:CHANGED]->(s:Service)
WHERE c.at >= $since AND c.at <= $until
RETURN c.id AS change, s.id AS service, c.kind AS kind, c.at AS at, c.summary AS summary
ORDER BY at DESC, change
LIMIT 5

// name: add_hypotheses
// purpose: Put suspects on the board as open Hypothesis nodes (idempotent per incident + change).
UNWIND $rows AS r
MATCH (i:Incident {id: $incident_id}), (c:Change {id: r.change})
MERGE (h:Hypothesis {id: r.id})
ON CREATE SET h.status = 'open', h.source = r.source, h.hops = r.hops, h.created_at = $at, h.runbook = r.runbook
MERGE (i)-[:HAS_HYPOTHESIS]->(h)
MERGE (h)-[:SUSPECTS]->(c)
RETURN h.id AS id

// name: hypothesis_facts
// purpose: What a check needs about one suspect: changed service, change time, rollback, alerting service and time.
MATCH (i:Incident)-[:HAS_HYPOTHESIS]->(h:Hypothesis {id: $hypothesis_id})-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
MATCH (i)-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
OPTIONAL MATCH (i)-[:CORRELATED_WITH]->(:Alert)-[:FIRED_ON]->(cs:Service)
RETURN i.id AS incident, h.status AS status, c.id AS change, c.summary AS summary, c.at AS change_at,
       c.rolled_back_at AS rolled_back_at, s.id AS service, o.id AS origin, a.at AS at,
       collect(DISTINCT cs.id) AS storm_services

// name: live_paths
// purpose: Up to 20 live dependency paths (edges valid at alert time) from the alerting service to a suspect's service, shortest first; the check picks the one the anomaly actually travelled.
MATCH (o:Service {id: $origin}), (t:Service {id: $target})
// No path at all within 6 hops (live or not): done, without walking every path out of the origin.
WITH o, shortestPath((o)-[:DEPENDS_ON*0..6]->(t)) AS sp
WHERE sp IS NOT NULL
// Otherwise list the paths as before: which 20 are kept among equally long ones, and their order, is the order this
// traversal meets them, so it stays exactly as it was (a per-hop filter on the edges would change that order). The
// target is matched again, not carried over, so the traversal still runs from the origin.
MATCH p = (o)-[:DEPENDS_ON*0..6]->(:Service {id: $target})
WHERE all(r IN relationships(p) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at))
WITH p
ORDER BY length(p)
LIMIT 20
RETURN [n IN nodes(p) | n.id] AS path

// name: storm_unexplained
// purpose: In an alert storm: which of the other alerting services have no live dependency path to the suspect's service (so the suspect cannot explain their alerts).
UNWIND $services AS sid
MATCH (o:Service {id: sid}), (s:Service {id: $target})
WITH o, s, $at AS alert_at
CALL {
  // Live hops o -> s (same block as path_suspects, which explains it).
  WITH o, s, alert_at
  WITH o, s, alert_at, shortestPath((o)-[:DEPENDS_ON*0..6]->(s)) AS sp
  WHERE sp IS NOT NULL
  WITH o, s, alert_at, sp,
       all(r IN relationships(sp) WHERE r.valid_from <= alert_at AND (r.valid_to IS NULL OR r.valid_to > alert_at)) AS live
  OPTIONAL MATCH p = (o)-[e:DEPENDS_ON*0..6]->(s)
  WHERE NOT live AND e.valid_from <= alert_at AND (e.valid_to IS NULL OR e.valid_to > alert_at)
  WITH live, sp, min(length(p)) AS shortest_live
  WITH CASE WHEN live THEN length(sp) ELSE shortest_live END AS hops
  WHERE hops IS NOT NULL
  RETURN hops
}
WITH collect(o.id) AS explained
UNWIND $services AS sid
WITH DISTINCT sid, explained
WHERE NOT sid IN explained
RETURN sid AS service

// name: any_path
// purpose: shortestPath ignoring validity, to tell a retired (or not yet live) dependency apart from no dependency at all.
MATCH (o:Service {id: $origin}), (t:Service {id: $target})
WITH shortestPath((o)-[:DEPENDS_ON*]->(t)) AS p
WHERE p IS NOT NULL
RETURN [n IN nodes(p) | n.id] AS path, [r IN relationships(p) | r.valid_to] AS retired_at,
       [r IN relationships(p) | r.valid_from] AS live_from

// name: red_before
// purpose: The latest anomaly on a service between the start of the alert window and a change landing on it: was the service already failing before its own change (a cascade victim)?
MATCH (x:Anomaly)-[:ON]->(:Service {id: $service})
WHERE x.at >= $since AND x.at < $until
RETURN max(x.at) AS at

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
SET e.verdict = $verdict, e.reason = $reason, e.tag = $tag, e.path = $path, e.at = $at, e.explained = $explained
WITH h, e, h.status AS before
// A human-confirmed cause stays confirmed whatever a later re-check says.
SET h.status = CASE WHEN h.status = 'confirmed' THEN h.status WHEN $verdict = 'supports' THEN 'supported'
                    WHEN $verdict = 'refutes' THEN 'refuted' ELSE 'inconclusive' END,
    h.explained = $explained, h.onset = $onset, h.gaps = $gaps, h.red_before = $red_before
FOREACH (_ IN CASE WHEN $verdict = 'supports' THEN [1] ELSE [] END | MERGE (e)-[:SUPPORTS]->(h))
FOREACH (_ IN CASE WHEN $verdict = 'refutes' THEN [1] ELSE [] END | MERGE (e)-[:REFUTES]->(h))
WITH h, before
// Procedural memory learns from misses too: a runbook whose suggestion was refuted loses confidence (once).
OPTIONAL MATCH (rb:Runbook {id: h.runbook})
FOREACH (x IN CASE WHEN rb IS NOT NULL AND $verdict = 'refutes' AND before = 'open' THEN [rb] ELSE [] END |
  SET x.uses = x.uses + 1)
RETURN h.id AS hypothesis, h.status AS status

// name: record_outranked
// purpose: When several suspects are supported, record why each one the leader covers lost, as a separate REFUTES Evidence node (the check's own SUPPORTS evidence stays, so a human can still confirm it later).
UNWIND $rows AS r
MATCH (h:Hypothesis {id: r.id})
MERGE (e:Evidence {id: r.evidence_id})
SET e.verdict = 'outranked', e.reason = r.reason, e.tag = 'outranked', e.at = $at
MERGE (e)-[:REFUTES]->(h)
SET h.status = 'outranked'
RETURN count(h) AS outranked

// name: depends_among
// purpose: Which of the given services depend (directly or transitively, live at $at) on which others: lets conclude tell a cascade victim from the change upstream that started it.
MATCH (o:Service), (s:Service)
WHERE o.id IN $services AND s.id IN $services AND o.id <> s.id
WITH o, s, $at AS alert_at
CALL {
  // Live hops o -> s (same block as path_suspects, which explains it); o <> s, so any path has 1..6 hops.
  WITH o, s, alert_at
  WITH o, s, alert_at, shortestPath((o)-[:DEPENDS_ON*0..6]->(s)) AS sp
  WHERE sp IS NOT NULL
  WITH o, s, alert_at, sp,
       all(r IN relationships(sp) WHERE r.valid_from <= alert_at AND (r.valid_to IS NULL OR r.valid_to > alert_at)) AS live
  OPTIONAL MATCH p = (o)-[e:DEPENDS_ON*0..6]->(s)
  WHERE NOT live AND e.valid_from <= alert_at AND (e.valid_to IS NULL OR e.valid_to > alert_at)
  WITH live, sp, min(length(p)) AS shortest_live
  WITH CASE WHEN live THEN length(sp) ELSE shortest_live END AS hops
  WHERE hops IS NOT NULL
  RETURN hops
}
RETURN DISTINCT o.id AS service, s.id AS upstream

// name: record_co_causes
// purpose: A supported suspect that explains an alerting service the leading cause cannot is kept as a co-cause, not ruled out.
UNWIND $rows AS r
MATCH (h:Hypothesis {id: r.id})
SET h.status = 'co-cause', h.note = r.note
RETURN count(h) AS co_causes

// name: co_causes
// purpose: Changes kept as co-causes of an incident (each explains an alerting service the leading cause cannot).
MATCH (:Incident {id: $incident_id})-[:HAS_HYPOTHESIS]->(h:Hypothesis {status: 'co-cause'})-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
RETURN c.id AS change, s.id AS service, c.summary AS summary, h.note AS reason, h.explained AS explained
ORDER BY change

// name: cause_facts
// purpose: The incident's leading cause as the graph records it (confirmed, else supported) with its evidence.
MATCH (:Incident {id: $incident_id})-[:HAS_HYPOTHESIS]->(h:Hypothesis)-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
WHERE h.status IN ['confirmed', 'supported']
OPTIONAL MATCH (e:Evidence)-[:SUPPORTS]->(h)
OPTIONAL MATCH (c)-[:AUTHORED_BY]->(p:Person)
RETURN c.id AS change, s.id AS service, c.summary AS summary, c.kind AS kind, c.at AS at, p.name AS author,
       e.reason AS reason, e.path AS live_path, h.status AS status, coalesce(h.explained, []) AS explained,
       coalesce(h.gaps, []) AS gaps
ORDER BY status, size(coalesce(e.path, [])) DESC
LIMIT 1

// name: anomaly_baseline
// purpose: The stronger flat baseline (no traversal, the same rule as the eval's anomaly-aware change log): of the in-window changes not rolled back, blame the one whose own service went red first after it.
MATCH (c:Change)-[:CHANGED]->(s:Service)<-[:ON]-(x:Anomaly)
WHERE c.at >= $since AND c.at <= $until AND (c.rolled_back_at IS NULL OR c.rolled_back_at > $until)
  AND x.at >= c.at AND x.at <= $until
WITH c, s, min(x.at) AS red_at
RETURN c.id AS change, s.id AS service, c.kind AS kind, c.at AS at, c.summary AS summary, red_at
ORDER BY red_at, at DESC, change
LIMIT 1
