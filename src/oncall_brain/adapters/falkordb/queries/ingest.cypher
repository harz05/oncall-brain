// name: ingest_teams
// purpose: Upsert teams. Every ingest statement MERGEs on a stable id, so re-seeding is idempotent.
UNWIND $rows AS r
MERGE (t:Team {id: r.id})
SET t.name = r.name

// name: ingest_people
// purpose: Upsert people (fake names) and their team membership.
UNWIND $rows AS r
MERGE (p:Person {id: r.id})
SET p.name = r.name, p.handle = r.handle
WITH p, r
MATCH (t:Team {id: r.team})
MERGE (p)-[:MEMBER_OF]->(t)

// name: ingest_services
// purpose: Upsert services and which team owns each.
UNWIND $rows AS r
MERGE (s:Service {id: r.id})
SET s.name = r.name, s.tier = r.tier
WITH s, r
MATCH (t:Team {id: r.team})
MERGE (t)-[:OWNS]->(s)

// name: ingest_depends_on
// purpose: Upsert caller -> callee dependencies. valid_from / valid_to make the dependency map temporal.
UNWIND $rows AS r
MATCH (a:Service {id: r.src}), (b:Service {id: r.dst})
MERGE (a)-[d:DEPENDS_ON {valid_from: r.valid_from}]->(b)
SET d.valid_to = r.valid_to

// name: ingest_on_call
// purpose: Upsert on-call rotation shifts as (Person)-[:ON_CALL {start, end}]->(Team).
UNWIND $rows AS r
MATCH (p:Person {id: r.person}), (t:Team {id: r.team})
MERGE (p)-[oc:ON_CALL {start: r.start}]->(t)
SET oc.end = r.end

// name: ingest_changes
// purpose: Upsert deploys and config changes, the service each touched, and the author.
UNWIND $rows AS r
MERGE (c:Change {id: r.id})
SET c.kind = r.kind, c.summary = r.summary, c.at = r.at, c.rolled_back_at = r.rolled_back_at,
    c.version = r.version
WITH c, r
MATCH (s:Service {id: r.service}), (p:Person {id: r.author})
MERGE (c)-[:CHANGED]->(s)
MERGE (c)-[:AUTHORED_BY]->(p)

// name: ingest_alerts
// purpose: Upsert alerts and the service each fired on.
UNWIND $rows AS r
MERGE (a:Alert {id: r.id})
SET a.name = r.name, a.symptom = r.symptom, a.at = r.at, a.act = r.act
WITH a, r
MATCH (s:Service {id: r.service})
MERGE (a)-[:FIRED_ON]->(s)

// name: ingest_anomalies
// purpose: Upsert monitoring anomalies (latency / errors / saturation) on services.
UNWIND $rows AS r
MERGE (x:Anomaly {id: r.id})
SET x.kind = r.kind, x.summary = r.summary, x.at = r.at
WITH x, r
MATCH (s:Service {id: r.service})
MERGE (x)-[:ON]->(s)

// name: ingest_runbooks
// purpose: Upsert runbooks (procedural memory) and the service each one fixes.
UNWIND $rows AS r
MERGE (rb:Runbook {id: r.id})
SET rb.title = r.title, rb.steps = r.steps, rb.kind = r.kind, rb.uses = r.uses, rb.successes = r.successes
WITH rb, r
MATCH (s:Service {id: r.service})
MERGE (rb)-[:FOR_SERVICE]->(s)

// name: ingest_incidents
// purpose: Upsert past, resolved incidents (episodic memory) with their cause and the runbook that fixed them.
UNWIND $rows AS r
MERGE (i:Incident {id: r.id})
SET i.title = r.title, i.symptom = r.symptom, i.status = r.status, i.opened_at = r.opened_at,
    i.resolved_at = r.resolved_at
WITH i, r
MATCH (s:Service {id: r.service}), (c:Change {id: r.cause}), (rb:Runbook {id: r.runbook})
MERGE (i)-[:IMPACTS {hops: 0}]->(s)
MERGE (i)-[:CAUSED_BY]->(c)
MERGE (i)-[:FIXED_WITH]->(rb)

// name: ingest_tickets
// purpose: Upsert change-request tickets (a source a status update can cite).
UNWIND $rows AS r
MERGE (t:Ticket {id: r.id})
SET t.title = r.title, t.text = r.text, t.at = r.at
WITH t, r
MATCH (c:Change {id: r.change}), (p:Person {id: r.author})
MERGE (t)-[:REQUESTED]->(c)
MERGE (t)-[:AUTHORED_BY]->(p)

// name: ingest_messages
// purpose: Upsert chat messages that mention a change (another citable source).
UNWIND $rows AS r
MERGE (m:Message {id: r.id})
SET m.channel = r.channel, m.text = r.text, m.at = r.at, m.kind = 'chat'
WITH m, r
MATCH (c:Change {id: r.change}), (p:Person {id: r.author})
MERGE (m)-[:MENTIONS]->(c)
MERGE (m)-[:AUTHORED_BY]->(p)
