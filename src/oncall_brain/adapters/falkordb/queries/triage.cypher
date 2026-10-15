// name: open_incident
// purpose: Open the incident for an alert (idempotent). The incident is the shared board every agent reads and writes.
MATCH (a:Alert {id: $alert_id})-[:FIRED_ON]->(s:Service)
MERGE (i:Incident {id: $incident_id})
ON CREATE SET i.status = 'open', i.opened_at = a.at, i.symptom = a.symptom, i.title = a.name
MERGE (i)-[:TRIGGERED_BY]->(a)
MERGE (i)-[:IMPACTS {hops: 0}]->(s)
RETURN i.id AS incident, i.status AS status, s.id AS service, a.at AS at, a.symptom AS symptom, a.name AS alert

// name: incident_head
// purpose: The incident's alerting service, alert time and status.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
RETURN i.id AS incident, i.status AS status, o.id AS service, a.id AS alert, a.at AS at, a.symptom AS symptom,
       a.name AS alert_name

// name: blast_radius
// purpose: Multi-hop impact: every service that transitively depends on $service via DEPENDS_ON edges valid at $at, with its shortest path.
MATCH p = (caller:Service)-[:DEPENDS_ON*1..6]->(:Service {id: $service})
WHERE all(r IN relationships(p) WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at))
WITH caller, p
ORDER BY length(p)
WITH caller, collect(p)[0] AS p
MATCH (t:Team)-[:OWNS]->(caller)
RETURN caller.id AS service, caller.tier AS tier, length(p) AS hops, t.name AS team, [n IN nodes(p) | n.id] AS path
ORDER BY hops, service

// name: record_impacts
// purpose: Write impacted / at-risk services onto the incident board.
UNWIND $rows AS r
MATCH (i:Incident {id: $incident_id}), (s:Service {id: r.service})
MERGE (i)-[x:IMPACTS]->(s)
ON CREATE SET x.hops = r.hops, x.via = $via

// name: on_call_for
// purpose: Who is on call at $at for the team that owns $service (rotation edges carry start/end).
MATCH (s:Service {id: $service})<-[:OWNS]-(t:Team)<-[oc:ON_CALL]-(p:Person)
WHERE oc.start <= $at AND oc.end > $at
RETURN p.id AS person, p.name AS name, p.handle AS handle, t.id AS team, t.name AS team_name

// name: record_page
// purpose: Record that the incident paged this person (an action taken because of what the graph showed).
MATCH (i:Incident {id: $incident_id}), (p:Person {id: $person})
MERGE (i)-[pg:PAGED]->(p)
ON CREATE SET pg.at = $at, pg.for_service = $service
RETURN pg.for_service AS first_for
