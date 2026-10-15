// name: who_knows
// purpose: Who knows a service, ranked by graph evidence: on the owning team (3), authored changes to it (2 each), was paged for it in an incident (1 each).
MATCH (s:Service {id: $service})
MATCH (p:Person)-[:MEMBER_OF]->(t:Team)
WITH s, p, t,
     size([(s)<-[:OWNS]-(t) | 1]) AS owns,
     size(list.dedup([(s)<-[:CHANGED]-(c:Change)-[:AUTHORED_BY]->(p) | c.id])) AS changes,
     size(list.dedup([(i:Incident)-[pg:PAGED]->(p) WHERE pg.for_service = s.id | i.id])) AS incidents
WHERE owns + changes + incidents > 0
RETURN p.id AS person, p.name AS name, p.handle AS handle, t.name AS team, owns > 0 AS on_owning_team,
       changes, incidents, 3 * owns + 2 * changes + incidents AS score
ORDER BY score DESC, name
LIMIT 5

// name: change_story
// purpose: Trace a change to its sources: author and team, the ticket that requested it, chat that announced it, incidents it caused.
MATCH (c:Change {id: $change_id})-[:CHANGED]->(s:Service)
OPTIONAL MATCH (c)-[:AUTHORED_BY]->(a:Person)-[:MEMBER_OF]->(t:Team)
OPTIONAL MATCH (src)-[:REQUESTED|MENTIONS]->(c)
OPTIONAL MATCH (i:Incident)-[:CAUSED_BY]->(c)
RETURN c.id AS change, c.kind AS kind, c.summary AS summary, c.at AS at, s.id AS service, a.id AS author_id,
       a.name AS author, t.name AS team,
       collect(DISTINCT {id: src.id, kind: labels(src)[0], title: src.title, channel: src.channel,
                         text: src.text}) AS sources,
       collect(DISTINCT i.id) AS incidents

// name: record_consult
// purpose: Comms records who it will ask about the culprit service (an action the who_knows ranking drives).
MATCH (i:Incident {id: $incident_id}), (p:Person {id: $person})
MERGE (i)-[x:CONSULTED]->(p)
ON CREATE SET x.for_service = $service, x.score = $score
