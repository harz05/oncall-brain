// name: list_alerts
// purpose: The UI's incident inbox: every alert in story order (act 1, 2, 3, then alerts raised live), with the incident handling it (opened for it, or one it was folded into) and that incident's status.
MATCH (a:Alert)-[:FIRED_ON]->(s:Service)
OPTIONAL MATCH (i:Incident)-[:TRIGGERED_BY|CORRELATED_WITH]->(a)
WITH a, s, collect(i)[0] AS i
RETURN a.id AS id, a.name AS name, s.id AS service, a.symptom AS symptom, a.at AS at, a.act AS act,
       i.id AS incident, i.status AS status
ORDER BY act, at
