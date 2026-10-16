// name: who_knows
// purpose: Who knows a service, ranked by graph evidence: on the team that owns it now (3), on a team that owned it before a transfer (2: they ran it), authored changes to it (2 each), was paged for it in an incident (1 each), wrote docs, tickets or chat that mention or decide it (1 each, at most 3: writing about a service supports hands-on evidence, never outweighs it).
MATCH (s:Service {id: $service})
MATCH (p:Person)-[:MEMBER_OF]->(t:Team)
WITH s, p, t,
     size([(s)<-[own:OWNS]-(t) WHERE own.valid_to IS NULL | 1]) AS owns,
     size([(s)<-[had:OWNS]-(t) WHERE had.valid_to IS NOT NULL | 1]) AS owned,
     size(list.dedup([(s)<-[:CHANGED]-(c:Change)-[:AUTHORED_BY]->(p) | c.id])) AS changes,
     size(list.dedup([(i:Incident)-[pg:PAGED]->(p) WHERE pg.for_service = s.id | i.id])) AS incidents,
     size(list.dedup([(s)<-[:MENTIONS|DECIDES]-(x)-[:AUTHORED_BY]->(p) | x.id])) AS docs
WITH s, p, t, owns, CASE WHEN owns = 0 AND owned > 0 THEN 1 ELSE 0 END AS former, changes, incidents, docs
WHERE owns + former + changes + incidents + docs > 0
RETURN p.id AS person, p.name AS name, p.handle AS handle, t.name AS team, owns > 0 AS on_owning_team,
       former > 0 AS on_former_owning_team, changes, incidents, docs,
       3 * owns + 2 * former + 2 * changes + incidents + CASE WHEN docs > 3 THEN 3 ELSE docs END AS score
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

// name: link_entities
// purpose: Entity linking for ask: the services, teams, people (full or first name), changes (id, or the part after 'chg:'), tickets (id or key), incidents (id, or the part after 'inc:', with the time it opened, so "at the time of inc:0911" names a time) and initiatives (name, id or the part after 'init:') named in $q, the question lowered to space-separated tokens and padded with a space each side. A name must sit between spaces, so 'cart' never matches inside 'cartography'.
MATCH (s:Service)
WHERE $q CONTAINS (' ' + toLower(s.name) + ' ')
RETURN s.id AS id, 'service' AS kind, s.name AS name, toLower(s.name) AS matched, null AS at
UNION ALL
MATCH (t:Team)
WHERE $q CONTAINS (' ' + toLower(t.name) + ' ')
RETURN t.id AS id, 'team' AS kind, t.name AS name, toLower(t.name) AS matched, null AS at
UNION ALL
MATCH (p:Person)
WITH p, [x IN [toLower(p.name), toLower(split(p.name, ' ')[0])] WHERE $q CONTAINS (' ' + x + ' ')] AS found
WHERE size(found) > 0
RETURN p.id AS id, 'person' AS kind, p.name AS name, found[0] AS matched, null AS at
UNION ALL
MATCH (c:Change)
WITH c, [x IN [toLower(c.id), last(split(toLower(c.id), ':'))] WHERE $q CONTAINS (' ' + x + ' ')] AS found
WHERE size(found) > 0
RETURN c.id AS id, 'change' AS kind, c.summary AS name, found[0] AS matched, null AS at
UNION ALL
MATCH (t:Ticket)
WITH t, [x IN [toLower(t.id), last(split(toLower(t.id), ':'))] WHERE $q CONTAINS (' ' + x + ' ')] AS found
WHERE size(found) > 0
RETURN t.id AS id, 'ticket' AS kind, t.title AS name, found[0] AS matched, null AS at
UNION ALL
MATCH (i:Incident)
WITH i, [x IN [toLower(i.id), last(split(toLower(i.id), ':'))] WHERE $q CONTAINS (' ' + x + ' ')] AS found
WHERE size(found) > 0
RETURN i.id AS id, 'incident' AS kind, i.title AS name, found[0] AS matched, i.opened_at AS at
UNION ALL
MATCH (n:Initiative)
WITH n, [x IN [toLower(n.name), toLower(n.id), last(split(toLower(n.id), ':'))] WHERE $q CONTAINS (' ' + x + ' ')] AS found
WHERE size(found) > 0
RETURN n.id AS id, 'initiative' AS kind, n.name AS name, found[0] AS matched, null AS at

// name: ownership
// purpose: ask, "who owns": the team whose OWNS edge to each linked service (or every service of a linked team) is valid at $at (the live edge when there is no $at), its members, who is ON_CALL for it at $at (with no $at: at the latest alert in the graph, the synthetic company's "now", or the wall clock if there is none; clock says which), and that edge's history: since and until when, the owner before it and the one after it, so "who owned payments-gw at the time of inc:0911" and "since when" are answered from the edges.
OPTIONAL MATCH (al:Alert)
WITH max(al.at) AS last
WITH CASE WHEN $at IS NOT NULL THEN $at WHEN last IS NOT NULL THEN last ELSE timestamp() / 1000 END AS now,
     CASE WHEN $at IS NOT NULL THEN 'given' WHEN last IS NOT NULL THEN 'latest alert' ELSE 'clock' END AS clock
MATCH (t:Team)-[o:OWNS]->(s:Service)
WHERE (s.id IN $ids OR t.id IN $ids)
  AND (($at IS NULL AND o.valid_to IS NULL)
       OR ($at IS NOT NULL AND o.valid_from <= $at AND (o.valid_to IS NULL OR o.valid_to > $at)))
OPTIONAL MATCH (p:Person)-[oc:ON_CALL]->(t)
WHERE oc.start <= now AND oc.end > now
RETURN s.id AS service, s.name AS service_name, t.id AS team, t.name AS team_name,
       [(m:Person)-[:MEMBER_OF]->(t) | {id: m.id, name: m.name}] AS members, p.id AS on_call,
       p.name AS on_call_name, p.handle AS handle, now AS at, clock, o.valid_from AS since, o.valid_to AS until,
       [(s)<-[ob:OWNS]-(b:Team) WHERE ob.valid_to IS NOT NULL AND ob.valid_to <= o.valid_from
        | {team: b.id, name: b.name, from: ob.valid_from, until: ob.valid_to}] AS before,
       [(s)<-[on:OWNS]-(n:Team) WHERE o.valid_to IS NOT NULL AND on.valid_from >= o.valid_to
        | {team: n.id, name: n.name, from: on.valid_from, until: on.valid_to}] AS after
ORDER BY team_name, service_name

// name: decisions_about
// purpose: ask, "why": the docs that DECIDE each linked service (its decisions of record), who wrote each, the newer doc that SUPERSEDES it (null: still current) and the older doc it replaces.
UNWIND $ids AS sid
MATCH (s:Service {id: sid})<-[:DECIDES]-(d:Doc)
OPTIONAL MATCH (d)-[:AUTHORED_BY]->(p:Person)
OPTIONAL MATCH (newer:Doc)-[:SUPERSEDES]->(d)
OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Doc)
RETURN d.id AS id, d.kind AS kind, d.title AS title, d.text AS text, d.at AS at, p.name AS author, s.id AS service,
       s.name AS service_name, newer.id AS superseded_by, old.id AS replaces, old.title AS replaces_title

// name: service_runbooks
// purpose: ask, "how do I": the Runbooks FOR_SERVICE each linked service (procedural memory, with uses and successes), the runbook pages (Doc kind 'runbook') that MENTION it, and the general runbook pages that mention no service at all.
UNWIND $ids AS sid
MATCH (s:Service {id: sid})<-[:FOR_SERVICE]-(rb:Runbook)
RETURN 'runbook' AS source, rb.id AS id, rb.title AS title, s.id AS service, s.name AS service_name,
       rb.steps AS steps, rb.uses AS uses, rb.successes AS successes, null AS text, null AS author
UNION ALL
UNWIND $ids AS sid
MATCH (s:Service {id: sid})<-[:MENTIONS]-(d:Doc {kind: 'runbook'})
OPTIONAL MATCH (d)-[:AUTHORED_BY]->(p:Person)
RETURN 'page' AS source, d.id AS id, d.title AS title, s.id AS service, s.name AS service_name, null AS steps,
       null AS uses, null AS successes, d.text AS text, p.name AS author
UNION ALL
MATCH (d:Doc {kind: 'runbook'})
WHERE NOT (d)-[:MENTIONS]->(:Service)
OPTIONAL MATCH (d)-[:AUTHORED_BY]->(p:Person)
RETURN 'general' AS source, d.id AS id, d.title AS title, null AS service, null AS service_name, null AS steps,
       null AS uses, null AS successes, d.text AS text, p.name AS author

// name: service_incidents
// purpose: ask, "what happened" and "how do I": incidents that IMPACT a linked service, were CAUSED_BY a linked change or a change to a linked service, or are linked by id, newest first, with the cause and the runbook that fixed each (FIXED_WITH).
// ponytail: scans every incident's IMPACTS / CAUSED_BY edges (tens here); start from the linked ids if incidents grow to many thousands.
MATCH (i:Incident)-[:IMPACTS|CAUSED_BY]->(x)
OPTIONAL MATCH (x)-[:CHANGED]->(xs:Service)
WITH i, x, xs
WHERE x.id IN $ids OR xs.id IN $ids OR i.id IN $ids
WITH DISTINCT i
OPTIONAL MATCH (i)-[:CAUSED_BY]->(c:Change)-[:CHANGED]->(cs:Service)
OPTIONAL MATCH (i)-[:FIXED_WITH]->(rb:Runbook)
RETURN i.id AS id, i.title AS title, i.status AS status, i.opened_at AS at, c.id AS cause, c.kind AS cause_kind,
       cs.id AS cause_service, cs.name AS cause_service_name, rb.id AS runbook, rb.title AS runbook_title,
       rb.uses AS uses, rb.successes AS successes,
       [(i)-[:IMPACTS]->(s:Service) WHERE s.id IN $ids OR i.id IN $ids | s.id] AS impacts
ORDER BY at DESC
LIMIT 10

// name: search_knowledge
// purpose: Full-text search over docs, tickets and chat (one FalkorDB full-text index per label, $query is the caller's terms OR-ed), the best hits per label with author, for a doc the newer doc that supersedes it, and refs: what the hit MENTIONS, DECIDES, REQUESTED or was AUTHORED_BY (ask prefers hits tied to the entities the question names).
CALL db.idx.fulltext.queryNodes('Doc', $query) YIELD node, score
WITH node, score ORDER BY score DESC LIMIT $limit
OPTIONAL MATCH (node)-[:AUTHORED_BY]->(p:Person)
OPTIONAL MATCH (newer:Doc)-[:SUPERSEDES]->(node)
RETURN node.id AS id, 'Doc' AS label, node.kind AS kind, node.title AS title, node.text AS text, node.at AS at,
       p.name AS author, newer.id AS superseded_by, newer.title AS superseded_title, score,
       [(node)-[:MENTIONS|DECIDES|REQUESTED|AUTHORED_BY]->(x) | x.id] AS refs
UNION ALL
CALL db.idx.fulltext.queryNodes('Ticket', $query) YIELD node, score
WITH node, score ORDER BY score DESC LIMIT $limit
OPTIONAL MATCH (node)-[:AUTHORED_BY]->(p:Person)
RETURN node.id AS id, 'Ticket' AS label, 'ticket' AS kind, node.title AS title, node.text AS text, node.at AS at,
       p.name AS author, null AS superseded_by, null AS superseded_title, score,
       [(node)-[:MENTIONS|DECIDES|REQUESTED|AUTHORED_BY]->(x) | x.id] AS refs
UNION ALL
CALL db.idx.fulltext.queryNodes('Message', $query) YIELD node, score
WITH node, score ORDER BY score DESC LIMIT $limit
OPTIONAL MATCH (node)-[:AUTHORED_BY]->(p:Person)
RETURN node.id AS id, 'Message' AS label, node.kind AS kind, node.channel AS title, node.text AS text,
       node.at AS at, p.name AS author, null AS superseded_by, null AS superseded_title, score,
       [(node)-[:MENTIONS|DECIDES|REQUESTED|AUTHORED_BY]->(x) | x.id] AS refs

// name: knowledge_context
// purpose: The graph around search hits: what each mentions, decides, requests, supersedes or cites, who wrote it, what mentions, supersedes or cites it, the incident a status update belongs to; then each neighbour's author, a change's service and a service's owning team today (the live OWNS edge).
UNWIND $ids AS hid
OPTIONAL MATCH (d:Doc {id: hid})
OPTIONAL MATCH (t:Ticket {id: hid})
OPTIONAL MATCH (m:Message {id: hid})
WITH coalesce(d, t, m) AS h
WHERE h IS NOT NULL
MATCH (h)-[r:MENTIONS|AUTHORED_BY|DECIDES|SUPERSEDES|REQUESTED|CITES|HAS_UPDATE]-(x)
OPTIONAL MATCH (x)-[:AUTHORED_BY]->(xa:Person)
OPTIONAL MATCH (x)-[:CHANGED]->(xs:Service)
OPTIONAL MATCH (x)<-[xo:OWNS]-(xt:Team)
WHERE xo.valid_to IS NULL
RETURN h.id AS hit, type(r) AS rel, startNode(r) = h AS outgoing, x.id AS id, labels(x)[0] AS label,
       coalesce(x.name, x.title, x.summary, x.channel) AS name, xa.id AS author, xa.name AS author_name,
       xs.id AS service, xs.name AS service_name, xt.id AS team, xt.name AS team_name

// name: record_consult
// purpose: Comms records who it will ask about the culprit service (an action the who_knows ranking drives).
MATCH (i:Incident {id: $incident_id}), (p:Person {id: $person})
MERGE (i)-[x:CONSULTED]->(p)
ON CREATE SET x.for_service = $service, x.score = $score

// name: initiative_story
// purpose: ask, "what is X changing" / "who is on X": for each linked initiative its goal, status and due date, the team that DRIVES it, the person who LEADS it, its tickets (PART_OF) with who filed each, the change each REQUESTED (service, author, rolled back or not) and the incidents that change is blamed for (a supported, co-cause or confirmed hypothesis; confirmed means it caused them), and the docs that MENTION it with the newer doc that SUPERSEDES each. People, projects and decisions connect through the work.
UNWIND $ids AS iid
MATCH (i:Initiative {id: iid})
OPTIONAL MATCH (team:Team)-[:DRIVES]->(i)
OPTIONAL MATCH (lead:Person)-[:LEADS]->(i)
OPTIONAL MATCH (t:Ticket)-[:PART_OF]->(i)
OPTIONAL MATCH (t)-[:AUTHORED_BY]->(ta:Person)
OPTIONAL MATCH (t)-[:REQUESTED]->(c:Change)-[:CHANGED]->(s:Service)
OPTIONAL MATCH (c)-[:AUTHORED_BY]->(ca:Person)
OPTIONAL MATCH (inc:Incident)-[:HAS_HYPOTHESIS]->(h:Hypothesis)-[:SUSPECTS]->(c)
WHERE h.status IN ['supported', 'co-cause', 'confirmed']
WITH i, team, lead, t, ta, c, s, ca, collect(DISTINCT {id: inc.id, title: inc.title, status: h.status}) AS blamed0
WITH i, team, lead, t, ta, c, s, ca, [x IN blamed0 WHERE x.id IS NOT NULL] AS blamed
WITH i, team, lead,
     collect(DISTINCT {id: t.id, title: t.title, at: t.at, by: ta.name, by_id: ta.id, change: c.id, summary: c.summary,
                       kind: c.kind, rolled_back: c.rolled_back_at IS NOT NULL, service: s.id, service_name: s.name,
                       change_by: ca.name, change_by_id: ca.id, incidents: blamed}) AS tickets0
WITH i, team, lead, [x IN tickets0 WHERE x.id IS NOT NULL] AS tickets
OPTIONAL MATCH (d:Doc)-[:MENTIONS]->(i)
OPTIONAL MATCH (d)-[:AUTHORED_BY]->(da:Person)
OPTIONAL MATCH (newer:Doc)-[:SUPERSEDES]->(d)
WITH i, team, lead, tickets,
     collect(DISTINCT {id: d.id, kind: d.kind, title: d.title, at: d.at, by: da.name, by_id: da.id,
                       superseded_by: newer.id}) AS docs0
RETURN i.id AS id, i.name AS name, i.goal AS goal, i.status AS status, i.due AS due, i.since AS since,
       team.id AS team, team.name AS team_name, lead.id AS lead, lead.name AS lead_name, tickets,
       [x IN docs0 WHERE x.id IS NOT NULL] AS docs
ORDER BY name
