// name: who_knows
// purpose: Who knows a service, ranked by graph evidence: on the owning team (3), authored changes to it (2 each), was paged for it in an incident (1 each), wrote docs, tickets or chat that mention or decide it (1 each, at most 3: writing about a service supports hands-on evidence, never outweighs it).
MATCH (s:Service {id: $service})
MATCH (p:Person)-[:MEMBER_OF]->(t:Team)
WITH s, p, t,
     size([(s)<-[:OWNS]-(t) | 1]) AS owns,
     size(list.dedup([(s)<-[:CHANGED]-(c:Change)-[:AUTHORED_BY]->(p) | c.id])) AS changes,
     size(list.dedup([(i:Incident)-[pg:PAGED]->(p) WHERE pg.for_service = s.id | i.id])) AS incidents,
     size(list.dedup([(s)<-[:MENTIONS|DECIDES]-(x)-[:AUTHORED_BY]->(p) | x.id])) AS docs
WHERE owns + changes + incidents + docs > 0
RETURN p.id AS person, p.name AS name, p.handle AS handle, t.name AS team, owns > 0 AS on_owning_team,
       changes, incidents, docs, 3 * owns + 2 * changes + incidents + CASE WHEN docs > 3 THEN 3 ELSE docs END AS score
ORDER BY score DESC, name
LIMIT 5

// name: change_story
// purpose: Trace a change to its sources: author and team, the ticket that requested it, the docs and chat that mention it (with their authors), incidents it caused.
MATCH (c:Change {id: $change_id})-[:CHANGED]->(s:Service)
OPTIONAL MATCH (c)-[:AUTHORED_BY]->(a:Person)-[:MEMBER_OF]->(t:Team)
OPTIONAL MATCH (src)-[:REQUESTED|MENTIONS]->(c)
OPTIONAL MATCH (src)-[:AUTHORED_BY]->(sa:Person)
OPTIONAL MATCH (i:Incident)-[:CAUSED_BY]->(c)
RETURN c.id AS change, c.kind AS kind, c.summary AS summary, c.at AS at, s.id AS service, a.id AS author_id,
       a.name AS author, t.name AS team,
       collect(DISTINCT {id: src.id, kind: labels(src)[0], title: src.title, channel: src.channel,
                         text: src.text, at: src.at, by: sa.name}) AS sources,
       collect(DISTINCT i.id) AS incidents

// name: search_knowledge
// purpose: Full-text search over docs, tickets and chat (one FalkorDB full-text index per label, $query is the caller's terms OR-ed), the best hits per label with author and, for a doc, the newer doc that supersedes it.
CALL db.idx.fulltext.queryNodes('Doc', $query) YIELD node, score
WITH node, score ORDER BY score DESC LIMIT $limit
OPTIONAL MATCH (node)-[:AUTHORED_BY]->(p:Person)
OPTIONAL MATCH (newer:Doc)-[:SUPERSEDES]->(node)
RETURN node.id AS id, 'Doc' AS label, node.kind AS kind, node.title AS title, node.text AS text, node.at AS at,
       p.name AS author, newer.id AS superseded_by, newer.title AS superseded_title, score
UNION ALL
CALL db.idx.fulltext.queryNodes('Ticket', $query) YIELD node, score
WITH node, score ORDER BY score DESC LIMIT $limit
OPTIONAL MATCH (node)-[:AUTHORED_BY]->(p:Person)
RETURN node.id AS id, 'Ticket' AS label, 'ticket' AS kind, node.title AS title, node.text AS text, node.at AS at,
       p.name AS author, null AS superseded_by, null AS superseded_title, score
UNION ALL
CALL db.idx.fulltext.queryNodes('Message', $query) YIELD node, score
WITH node, score ORDER BY score DESC LIMIT $limit
OPTIONAL MATCH (node)-[:AUTHORED_BY]->(p:Person)
RETURN node.id AS id, 'Message' AS label, node.kind AS kind, node.channel AS title, node.text AS text,
       node.at AS at, p.name AS author, null AS superseded_by, null AS superseded_title, score

// name: knowledge_context
// purpose: The graph around search hits: what each mentions, decides, requests, supersedes or cites, who wrote it, what mentions, supersedes or cites it, the incident a status update belongs to; then each neighbour's author, a change's service and a service's owning team.
UNWIND $ids AS hid
OPTIONAL MATCH (d:Doc {id: hid})
OPTIONAL MATCH (t:Ticket {id: hid})
OPTIONAL MATCH (m:Message {id: hid})
WITH coalesce(d, t, m) AS h
WHERE h IS NOT NULL
MATCH (h)-[r:MENTIONS|AUTHORED_BY|DECIDES|SUPERSEDES|REQUESTED|CITES|HAS_UPDATE]-(x)
OPTIONAL MATCH (x)-[:AUTHORED_BY]->(xa:Person)
OPTIONAL MATCH (x)-[:CHANGED]->(xs:Service)
OPTIONAL MATCH (x)<-[:OWNS]-(xt:Team)
RETURN h.id AS hit, type(r) AS rel, startNode(r) = h AS outgoing, x.id AS id, labels(x)[0] AS label,
       coalesce(x.name, x.title, x.summary, x.channel) AS name, xa.id AS author, xa.name AS author_name,
       xs.id AS service, xs.name AS service_name, xt.id AS team, xt.name AS team_name

// name: record_consult
// purpose: Comms records who it will ask about the culprit service (an action the who_knows ranking drives).
MATCH (i:Incident {id: $incident_id}), (p:Person {id: $person})
MERGE (i)-[x:CONSULTED]->(p)
ON CREATE SET x.for_service = $service, x.score = $score
