// name: list_alerts
// purpose: The UI's incident inbox: every alert in story order (act 1, 2, 3, then alerts raised live), with the incident handling it (opened for it, or one it was folded into) and that incident's status.
MATCH (a:Alert)-[:FIRED_ON]->(s:Service)
OPTIONAL MATCH (i:Incident)-[:TRIGGERED_BY|CORRELATED_WITH]->(a)
OPTIONAL MATCH (i)-[:HAS_HYPOTHESIS]->(h:Hypothesis)
WHERE h.status IN ['supported', 'confirmed']
OPTIONAL MATCH (i)-[:HAS_UPDATE]->(m:Message)
WITH a, s, i, count(DISTINCT h) AS causes, count(DISTINCT m) AS updates
ORDER BY i.id
WITH a, s, collect({id: i.id, status: i.status, has_cause: causes > 0, has_update: updates > 0})[0] AS inc
RETURN a.id AS id, a.name AS name, s.id AS service, a.symptom AS symptom, a.at AS at, a.act AS act,
       inc.id AS incident, inc.status AS status, coalesce(inc.has_cause, false) AS has_cause,
       coalesce(inc.has_update, false) AS has_update
ORDER BY act, at
