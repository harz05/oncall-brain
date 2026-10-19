// name: record_change
// purpose: Keep knowledge current: record a deploy or config change as it happens (idempotent on id).
MATCH (s:Service {id: $service})
MERGE (c:Change {id: $id})
// Two times: at is when the change happened (valid time), recorded_at when the graph first learned of it
// (transaction time, the server clock), so a change reported late by CI/CD is seen as late (learned_late).
SET c.kind = $kind, c.summary = $summary, c.at = $at, c.rolled_back_at = $rolled_back_at,
    c.recorded_at = coalesce(c.recorded_at, timestamp() / 1000.0)
WITH s, c
// Re-recording an id corrects the change: drop its old service and author links first.
OPTIONAL MATCH (c)-[old:CHANGED|AUTHORED_BY]->()
DELETE old
WITH DISTINCT s, c
MERGE (c)-[:CHANGED]->(s)
WITH c
OPTIONAL MATCH (p:Person {id: $author})
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (c)-[:AUTHORED_BY]->(x))
RETURN c.id AS change

// name: record_anomaly
// purpose: Keep knowledge current: record a monitoring anomaly on a service.
MATCH (s:Service {id: $service})
MERGE (x:Anomaly {id: $id})
SET x.kind = $kind, x.summary = $summary, x.at = $at, x.recorded_at = coalesce(x.recorded_at, timestamp() / 1000.0)
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
OPTIONAL MATCH (a)-[live:DEPENDS_ON]->(b)
WHERE live.valid_to IS NULL
WITH a, b, collect(live) AS existing
// The record that already starts at $at, if any (its key is unique): a retired one is reopened, not duplicated.
OPTIONAL MATCH (a)-[same:DEPENDS_ON {key: a.id + '>' + b.id + '@' + toString($at)}]->(b)
WITH a, b, existing, same, size(existing) > 0 AND same IS NOT NULL AND same.valid_to IS NOT NULL
                           AND any(x IN existing WHERE $at < x.valid_from) AS refused
// No live edge: reopen the record that starts at $at (a retire and a re-add in one second, or a retired dependency
// re-added at its own start), else start a new one.
FOREACH (_ IN CASE WHEN size(existing) = 0 AND same IS NOT NULL THEN [1] ELSE [] END | SET same.valid_to = NULL)
FOREACH (_ IN CASE WHEN size(existing) = 0 AND same IS NULL THEN [1] ELSE [] END |
  CREATE (a)-[:DEPENDS_ON {key: a.id + '>' + b.id + '@' + toString($at), valid_from: $at,
                           recorded_at: timestamp() / 1000.0}]->(b))
// Only one live edge per pair: a live dependency keeps going, its start moved earlier if $at is (the key moves with
// it), unless a retired record already starts there (refused: the tool says so).
FOREACH (d IN [x IN existing WHERE $at < x.valid_from AND NOT refused] |
  SET d.valid_from = $at, d.key = a.id + '>' + b.id + '@' + toString($at))
WITH a, b, refused
MATCH (a)-[d:DEPENDS_ON]->(b)
WHERE d.valid_to IS NULL
RETURN a.id AS caller, b.id AS callee, d.valid_from AS valid_from, refused

// name: retire_dependency
// purpose: Keep knowledge current: close the live caller -> callee dependency at $at (history is kept; queries at later times stop using it).
MATCH (:Service {id: $caller})-[d:DEPENDS_ON]->(:Service {id: $callee})
WHERE d.valid_to IS NULL AND d.valid_from <= $at
SET d.valid_to = $at
RETURN count(d) AS retired

// name: known_ids
// purpose: Keep knowledge current: which of $ids the graph has, looked up per label (Person, Service, Change, Incident, Doc, Ticket, Initiative) so the id indexes are used. record_doc, record_message and record_ticket refuse a record that names an unknown id before writing anything, so nothing is written half-linked.
UNWIND $ids AS x
OPTIONAL MATCH (p:Person {id: x})
OPTIONAL MATCH (s:Service {id: x})
OPTIONAL MATCH (c:Change {id: x})
OPTIONAL MATCH (i:Incident {id: x})
OPTIONAL MATCH (d:Doc {id: x})
OPTIONAL MATCH (t:Ticket {id: x})
OPTIONAL MATCH (n:Initiative {id: x})
WITH x, coalesce(p, s, c, i, d, t, n) AS found
WHERE found IS NOT NULL
RETURN x AS id

// name: record_doc
// purpose: Keep knowledge current: record a decision record, design note, postmortem or runbook page as it is written (idempotent on id): its author, the service it DECIDES for, what it MENTIONS (services, changes, incidents, docs, tickets, initiatives, each looked up per label), and the older doc it SUPERSEDES, so ask puts the new decision of record first and flags the old one.
MERGE (d:Doc {id: $id})
SET d.kind = $kind, d.title = $title, d.text = $text, d.at = $at
WITH d
// Re-recording an id corrects the doc: drop its old links first.
OPTIONAL MATCH (d)-[old:AUTHORED_BY|DECIDES|MENTIONS|SUPERSEDES]->()
DELETE old
WITH DISTINCT d
OPTIONAL MATCH (p:Person {id: $author})
OPTIONAL MATCH (s:Service {id: $decides})
OPTIONAL MATCH (prev:Doc {id: $supersedes})
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (d)-[:AUTHORED_BY]->(x))
FOREACH (x IN CASE WHEN s IS NULL THEN [] ELSE [s] END | MERGE (d)-[:DECIDES]->(x) MERGE (d)-[:MENTIONS]->(x))
FOREACH (x IN CASE WHEN prev IS NULL THEN [] ELSE [prev] END | MERGE (d)-[:SUPERSEDES]->(x))
WITH d, s, prev
// The empty-id sentinel keeps the row alive when there are no mentions.
UNWIND coalesce($mentions, []) + [''] AS m
OPTIONAL MATCH (ms:Service {id: m})
OPTIONAL MATCH (mc:Change {id: m})
OPTIONAL MATCH (mi:Incident {id: m})
OPTIONAL MATCH (md:Doc {id: m})
OPTIONAL MATCH (mt:Ticket {id: m})
OPTIONAL MATCH (mn:Initiative {id: m})
WITH d, s, prev, coalesce(ms, mc, mi, md, mt, mn) AS x
FOREACH (y IN CASE WHEN x IS NULL THEN [] ELSE [x] END | MERGE (d)-[:MENTIONS]->(y))
RETURN DISTINCT d.id AS doc, s.id AS decides, prev.id AS supersedes

// name: record_message
// purpose: Keep knowledge current: record a chat message as it is posted (idempotent on id): its channel, who AUTHORED it and what it MENTIONS (services, changes, incidents, docs, tickets, initiatives, each looked up per label so the id indexes are used). Message.text is full-text indexed, so ask finds it at once; change_story lists it for a change it mentions. Re-recording an id corrects the message: its old links are dropped first.
MERGE (m:Message {id: $id})
SET m.kind = 'chat', m.channel = $channel, m.text = $text, m.at = $at
WITH m
OPTIONAL MATCH (m)-[old:AUTHORED_BY|MENTIONS]->()
DELETE old
WITH DISTINCT m
OPTIONAL MATCH (p:Person {id: $author})
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (m)-[:AUTHORED_BY]->(x))
WITH m
UNWIND coalesce($mentions, []) + [''] AS ref
OPTIONAL MATCH (ms:Service {id: ref})
OPTIONAL MATCH (mc:Change {id: ref})
OPTIONAL MATCH (mi:Incident {id: ref})
OPTIONAL MATCH (md:Doc {id: ref})
OPTIONAL MATCH (mt:Ticket {id: ref})
OPTIONAL MATCH (mn:Initiative {id: ref})
WITH m, coalesce(ms, mc, mi, md, mt, mn) AS x
FOREACH (y IN CASE WHEN x IS NULL THEN [] ELSE [x] END | MERGE (m)-[:MENTIONS]->(y))
RETURN DISTINCT m.id AS message

// name: record_ticket
// purpose: Keep knowledge current: record a ticket as it is filed or updated (idempotent on id): title, text and status, who AUTHORED it, the change it REQUESTED (change_story lists the ticket), the initiative it is PART_OF (ask's initiative story lists it) and what it MENTIONS, each looked up per label. title and text are full-text indexed, so ask finds it at once. Re-recording an id corrects the ticket: its old links are dropped first.
MERGE (t:Ticket {id: $id})
SET t.title = $title, t.text = $text, t.status = $status, t.at = $at
WITH t
OPTIONAL MATCH (t)-[old:AUTHORED_BY|REQUESTED|PART_OF|MENTIONS]->()
DELETE old
WITH DISTINCT t
OPTIONAL MATCH (p:Person {id: $author})
OPTIONAL MATCH (c:Change {id: $requests})
OPTIONAL MATCH (n:Initiative {id: $part_of})
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (t)-[:AUTHORED_BY]->(x))
FOREACH (x IN CASE WHEN c IS NULL THEN [] ELSE [c] END | MERGE (t)-[:REQUESTED]->(x))
FOREACH (x IN CASE WHEN n IS NULL THEN [] ELSE [n] END | MERGE (t)-[:PART_OF]->(x))
WITH t
UNWIND coalesce($mentions, []) + [''] AS ref
OPTIONAL MATCH (ms:Service {id: ref})
OPTIONAL MATCH (mc:Change {id: ref})
OPTIONAL MATCH (mi:Incident {id: ref})
OPTIONAL MATCH (md:Doc {id: ref})
OPTIONAL MATCH (mt:Ticket {id: ref})
OPTIONAL MATCH (mn:Initiative {id: ref})
WITH t, coalesce(ms, mc, mi, md, mt, mn) AS x
FOREACH (y IN CASE WHEN x IS NULL THEN [] ELSE [x] END | MERGE (t)-[:MENTIONS]->(y))
RETURN DISTINCT t.id AS ticket

// name: transfer_ownership
// purpose: Keep knowledge current: $team takes over $service at $at. The previous owner's live OWNS edge is closed (valid_to = $at; history is kept, never deleted) and a new OWNS {valid_from: $at} edge is created; a team that already owns the service changes nothing (transferred = false); an $at before the live edge's valid_from writes nothing (backdated = true: history is append-only). Every query that asks who owns a service at a time (on_call_for, blast_radius, warn_candidates, service_map, ownership) filters OWNS by validity, so paging and "who owned X at the time of inc:0911" follow the history. history lists every OWNS edge of the service after the write.
MATCH (s:Service {id: $service}), (t:Team {id: $team})
OPTIONAL MATCH (prev:Team)-[o:OWNS]->(s)
WHERE o.valid_to IS NULL
WITH s, t, prev, o ORDER BY o.valid_from DESC
LIMIT 1
WITH s, t, prev, o, (prev IS NULL OR prev.id <> t.id) AS moves,
     (o IS NOT NULL AND coalesce(o.valid_from, 0) > $at) AS backdated
FOREACH (x IN CASE WHEN moves AND NOT backdated AND o IS NOT NULL THEN [o] ELSE [] END | SET x.valid_to = $at)
FOREACH (_ IN CASE WHEN moves AND NOT backdated THEN [1] ELSE [] END | CREATE (t)-[:OWNS {valid_from: $at}]->(s))
RETURN s.id AS service, t.id AS team, prev.id AS previous, moves AS transferred, backdated, o.valid_from AS live_from,
       [(s)<-[x:OWNS]-(b:Team) | {team: b.id, from: x.valid_from, until: x.valid_to}] AS history
