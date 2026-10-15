// name: update_facts
// purpose: Facts for the status update: impact, who was paged, the supported cause with its author and sources (ticket, chat).
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)
OPTIONAL MATCH (i)-[imp:IMPACTS]->(s0:Service)
WITH i, a, collect(DISTINCT {service: s0.id, via: imp.via}) AS impacts
OPTIONAL MATCH (i)-[:PAGED]->(p:Person)-[:MEMBER_OF]->(t:Team)
WITH i, a, impacts, collect(DISTINCT {name: p.name, handle: p.handle, team: t.name}) AS paged
OPTIONAL MATCH (i)-[cx:CONSULTED]->(x:Person)-[:MEMBER_OF]->(xt:Team)
WITH i, a, impacts, paged,
     collect(DISTINCT {id: x.id, name: x.name, handle: x.handle, team: xt.name, service: cx.for_service}) AS experts
OPTIONAL MATCH (i)-[:HAS_HYPOTHESIS]->(h:Hypothesis)-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
WHERE h.status IN ['confirmed', 'supported']
WITH i, a, impacts, paged, experts, h, c, s ORDER BY h.status
LIMIT 1
OPTIONAL MATCH (c)-[:AUTHORED_BY]->(author:Person)
OPTIONAL MATCH (src)-[:REQUESTED|MENTIONS]->(c)
OPTIONAL MATCH (rb:Runbook)-[:FOR_SERVICE]->(s)
WHERE rb.kind = c.kind
RETURN a.name AS alert, impacts, paged, experts, c.id AS change, c.summary AS change_summary,
       s.id AS cause_service,
       author.name AS author, collect(DISTINCT src.id) AS sources,
       collect(DISTINCT {id: rb.id, title: rb.title, steps: rb.steps, successes: rb.successes,
                         uses: rb.uses}) AS runbooks

// name: refuted_hypotheses
// purpose: Suspects the agents ruled out, with the reason recorded on their Evidence.
MATCH (:Incident {id: $incident_id})-[:HAS_HYPOTHESIS]->(h:Hypothesis)-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
MATCH (e:Evidence)-[:REFUTES]->(h)
RETURN c.id AS change, s.id AS service, c.summary AS summary, e.reason AS reason, h.source AS source

// name: post_update
// purpose: Post (or rewrite) the status update on the incident and link it to every node it cites; stale citations are dropped. Lookups are per label so the id indexes are used.
MATCH (i:Incident {id: $incident_id})
MERGE (m:Message {id: $message_id})
SET m.kind = 'status_update', m.channel = '#incidents', m.text = $text, m.at = $at
MERGE (i)-[:HAS_UPDATE]->(m)
WITH m
OPTIONAL MATCH (m)-[old:CITES]->()
DELETE old
WITH DISTINCT m
UNWIND $cites AS cid
OPTIONAL MATCH (c:Change {id: cid})
OPTIONAL MATCH (t:Ticket {id: cid})
OPTIONAL MATCH (msg:Message {id: cid})
OPTIONAL MATCH (rb:Runbook {id: cid})
OPTIONAL MATCH (p:Person {id: cid})
WITH m, coalesce(c, t, msg, rb, p) AS n
WHERE n IS NOT NULL
MERGE (m)-[:CITES]->(n)
RETURN count(n) AS cited

// name: change_info
// purpose: One change and the service it touched.
MATCH (c:Change {id: $change_id})-[:CHANGED]->(s:Service)
RETURN c.id AS change, c.kind AS kind, c.summary AS summary, s.id AS service, s.name AS service_name

// name: resolve_incident
// purpose: A human-confirmed fix becomes memory: CAUSED_BY (episodic) and a Runbook for (service, change kind) whose success count grows (procedural).
MATCH (i:Incident {id: $incident_id}), (c:Change {id: $change_id})-[:CHANGED]->(s:Service)
WHERE i.status <> 'resolved'
SET i.status = 'resolved', i.resolved_at = $at
MERGE (i)-[:CAUSED_BY]->(c)
MERGE (rb:Runbook {id: $runbook_id})
ON CREATE SET rb.title = $title, rb.steps = $steps, rb.kind = c.kind, rb.uses = 0, rb.successes = 0,
              rb.learned_from = i.id
SET rb.uses = rb.uses + 1, rb.successes = rb.successes + 1
MERGE (rb)-[:FOR_SERVICE]->(s)
MERGE (i)-[:FIXED_WITH]->(rb)
WITH i, c, rb
OPTIONAL MATCH (i)-[:HAS_HYPOTHESIS]->(h:Hypothesis)-[:SUSPECTS]->(c)
FOREACH (x IN CASE WHEN h IS NULL THEN [] ELSE [h] END | SET x.status = 'confirmed')
RETURN i.id AS incident, rb.id AS runbook, rb.title AS title, rb.steps AS steps, rb.successes AS successes

// name: service_map
// purpose: Services, owners and dependency edges (flagged live or retired at $at) for the UI.
MATCH (t:Team)-[:OWNS]->(s:Service)
OPTIONAL MATCH (s)-[d:DEPENDS_ON]->(x:Service)
RETURN s.id AS id, s.name AS name, s.tier AS tier, t.name AS team,
       collect({to: x.id, live: d.valid_from <= $at AND (d.valid_to IS NULL OR d.valid_to > $at)}) AS deps
