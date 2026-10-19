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
// purpose: Upsert services and which team owns each. OWNS carries valid_from (r.since: when the company started, unless the row says otherwise) and, once transfer_ownership closes it, valid_to; an edge seeded before validity existed gets its valid_from on the next seed.
UNWIND $rows AS r
MERGE (s:Service {id: r.id})
SET s.name = r.name, s.tier = r.tier
WITH s, r
MATCH (t:Team {id: r.team})
// The date is part of the pattern, as in ingest_depends_on: FalkorDB checks the MANDATORY valid_from constraint the
// moment an edge is made, before any SET (even ON CREATE SET) runs.
MERGE (t)-[o:OWNS {valid_from: coalesce(r.since, 0)}]->(s)

// name: ingest_depends_on
// purpose: Upsert caller -> callee dependencies. valid_from / valid_to make the dependency map temporal.
UNWIND $rows AS r
MATCH (a:Service {id: r.src}), (b:Service {id: r.dst})
// The key is the edge's identity (UNIQUE): in the pattern, since FalkorDB checks constraints as the edge is made.
MERGE (a)-[d:DEPENDS_ON {key: a.id + '>' + b.id + '@' + toString(r.valid_from), valid_from: r.valid_from}]->(b)
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
// purpose: Upsert past, resolved incidents (episodic memory) with their cause, the runbook that fixed them and who was paged for the culprit service.
UNWIND $rows AS r
MERGE (i:Incident {id: r.id})
SET i.title = r.title, i.symptom = r.symptom, i.status = r.status, i.opened_at = r.opened_at,
    i.resolved_at = r.resolved_at
WITH i, r
MATCH (s:Service {id: r.service}), (c:Change {id: r.cause}), (rb:Runbook {id: r.runbook})
MERGE (i)-[:IMPACTS {hops: 0}]->(s)
MERGE (i)-[:CAUSED_BY]->(c)
MERGE (i)-[:FIXED_WITH]->(rb)
WITH i, r
OPTIONAL MATCH (p:Person {id: r.paged})
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END |
  MERGE (i)-[pg:PAGED]->(x)
  ON CREATE SET pg.at = r.opened_at, pg.for_service = r.paged_for)

// name: ingest_initiatives
// purpose: Upsert initiatives (a project, programme or review with a goal, a status and a due date): the team that DRIVES it and the person who LEADS it. Tickets join one in ingest_tickets (PART_OF); docs and chat can MENTION one; ask walks it for "what is the Q4 cost review changing and who is on it".
UNWIND $rows AS r
MERGE (i:Initiative {id: r.id})
SET i.name = r.name, i.goal = r.goal, i.status = r.status, i.due = r.due, i.since = r.since
WITH i, r
OPTIONAL MATCH (t:Team {id: r.team})
OPTIONAL MATCH (p:Person {id: r.lead})
FOREACH (x IN CASE WHEN t IS NULL THEN [] ELSE [t] END | MERGE (x)-[:DRIVES]->(i))
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (x)-[:LEADS]->(i))

// name: ingest_docs
// purpose: Upsert docs (postmortems, design notes, decisions, runbook pages): who wrote each, the service a decision is about, and what it mentions: services, changes, incidents and initiatives (a runbook page that mentions no service is a general one, which ask offers for any service). Mention lookups are per label so the id indexes are used.
UNWIND $rows AS r
MERGE (d:Doc {id: r.id})
SET d.kind = r.kind, d.title = r.title, d.text = r.text, d.at = r.at
WITH d, r
OPTIONAL MATCH (p:Person {id: r.author})
OPTIONAL MATCH (s:Service {id: r.decides})
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (d)-[:AUTHORED_BY]->(x))
FOREACH (x IN CASE WHEN s IS NULL THEN [] ELSE [s] END | MERGE (d)-[:DECIDES]->(x))
WITH d, r
UNWIND r.mentions AS m
OPTIONAL MATCH (s:Service {id: m})
OPTIONAL MATCH (c:Change {id: m})
OPTIONAL MATCH (i:Incident {id: m})
OPTIONAL MATCH (n:Initiative {id: m})
WITH d, coalesce(s, c, i, n) AS x
WHERE x IS NOT NULL
MERGE (d)-[:MENTIONS]->(x)

// name: ingest_doc_links
// purpose: Link a doc to the older doc it supersedes, once every doc exists, so "what is current" is one hop.
UNWIND $rows AS r
MATCH (new:Doc {id: r.id}), (old:Doc {id: r.supersedes})
MERGE (new)-[:SUPERSEDES]->(old)

// name: ingest_tickets
// purpose: Upsert tickets (change requests and other work, a source a status update can cite): the change each requested, its author, the initiative it is PART_OF, and the services and docs it mentions.
UNWIND $rows AS r
MERGE (t:Ticket {id: r.id})
SET t.title = r.title, t.text = r.text, t.at = r.at
WITH t, r
OPTIONAL MATCH (c:Change {id: r.change})
OPTIONAL MATCH (p:Person {id: r.author})
OPTIONAL MATCH (n:Initiative {id: r.initiative})
FOREACH (x IN CASE WHEN c IS NULL THEN [] ELSE [c] END | MERGE (t)-[:REQUESTED]->(x))
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (t)-[:AUTHORED_BY]->(x))
FOREACH (x IN CASE WHEN n IS NULL THEN [] ELSE [n] END | MERGE (t)-[:PART_OF]->(x))
WITH t, r
UNWIND coalesce(r.mentions, []) AS m
OPTIONAL MATCH (s:Service {id: m})
OPTIONAL MATCH (c:Change {id: m})
OPTIONAL MATCH (d:Doc {id: m})
WITH t, coalesce(s, c, d) AS x
WHERE x IS NOT NULL
MERGE (t)-[:MENTIONS]->(x)

// name: ingest_messages
// purpose: Upsert chat messages (another citable source): the change one announces, its author, and the services, changes, incidents, docs, tickets and initiatives it mentions.
UNWIND $rows AS r
MERGE (m:Message {id: r.id})
SET m.channel = r.channel, m.text = r.text, m.at = r.at, m.kind = 'chat'
WITH m, r
OPTIONAL MATCH (c:Change {id: r.change})
OPTIONAL MATCH (p:Person {id: r.author})
FOREACH (x IN CASE WHEN c IS NULL THEN [] ELSE [c] END | MERGE (m)-[:MENTIONS]->(x))
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (m)-[:AUTHORED_BY]->(x))
WITH m, r
UNWIND coalesce(r.mentions, []) AS ref
OPTIONAL MATCH (s:Service {id: ref})
OPTIONAL MATCH (c:Change {id: ref})
OPTIONAL MATCH (i:Incident {id: ref})
OPTIONAL MATCH (d:Doc {id: ref})
OPTIONAL MATCH (t:Ticket {id: ref})
OPTIONAL MATCH (n:Initiative {id: ref})
WITH m, coalesce(s, c, i, d, t, n) AS x
WHERE x IS NOT NULL
MERGE (m)-[:MENTIONS]->(x)

// name: ingest_meta
// purpose: Stamp the graph with a fingerprint of the generated data, so a stale pristine copy (built by an older generator) is detected and rebuilt.
MERGE (m:Meta {id: 'meta'})
SET m.version = $version, m.seed = $seed

// name: data_version
// purpose: Read the data fingerprint and generator seed a graph was seeded with.
MATCH (m:Meta {id: 'meta'})
RETURN m.version AS version, m.seed AS seed

// name: backfill_dependency_keys
// purpose: Give every DEPENDS_ON edge from before the dependency key its key (caller>callee@valid_from), so the UNIQUE and MANDATORY key constraints can be built on an older graph (ensure_schema runs it only when they are missing).
MATCH (a:Service)-[d:DEPENDS_ON]->(b:Service)
WHERE d.key IS NULL
SET d.key = a.id + '>' + b.id + '@' + toString(d.valid_from)
