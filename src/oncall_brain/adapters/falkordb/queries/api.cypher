// name: list_alerts
// purpose: The alerts a user can respond to from the UI, in story order (act 1, act 2).
MATCH (a:Alert)-[:FIRED_ON]->(s:Service)
RETURN a.id AS id, a.name AS name, s.id AS service, a.symptom AS symptom, a.at AS at, a.act AS act
ORDER BY act, at
