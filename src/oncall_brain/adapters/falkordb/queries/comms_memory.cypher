// name: update_facts
// purpose: Facts for the status update: impact, who was paged and consulted, the supported cause with its author and sources (ticket, chat), and the runbook memory used.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)
OPTIONAL MATCH (i)-[imp:IMPACTS]->(s0:Service)
WITH i, a, collect(DISTINCT {service: s0.id, via: imp.via}) AS impacts
OPTIONAL MATCH (i)-[:PAGED]->(p:Person)-[:MEMBER_OF]->(t:Team)
WITH i, a, impacts, collect(DISTINCT {name: p.name, handle: p.handle, team: t.name}) AS paged
OPTIONAL MATCH (i)-[w:WARNED]->(wp:Person)-[:MEMBER_OF]->(wt:Team)
WITH i, a, impacts, paged,
     collect(DISTINCT {handle: wp.handle, team: wt.name, service: w.for_service, rank: w.rank}) AS warned
OPTIONAL MATCH (i)-[cx:CONSULTED]->(x:Person)-[:MEMBER_OF]->(xt:Team)
WITH i, a, impacts, paged, warned,
     collect(DISTINCT {id: x.id, name: x.name, handle: x.handle, team: xt.name, service: cx.for_service}) AS experts
OPTIONAL MATCH (i)-[:HAS_HYPOTHESIS]->(h:Hypothesis)-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
WHERE h.status IN ['confirmed', 'supported']
WITH i, a, impacts, paged, warned, experts, h, c, s ORDER BY h.status
LIMIT 1
OPTIONAL MATCH (c)-[:AUTHORED_BY]->(author:Person)
OPTIONAL MATCH (src)-[:REQUESTED|MENTIONS]->(c)
// Suggest the runbook that led memory to this cause, or the one a human confirmed fixed this incident. A runbook
// that merely shares the service and change kind may fix a different failure (a full disk vs a connection limit).
OPTIONAL MATCH (rb:Runbook {id: h.runbook})
OPTIONAL MATCH (i)-[:FIXED_WITH]->(fx:Runbook)
WITH a, impacts, paged, warned, experts, h, c, s, author, src, coalesce(rb, fx) AS rb
RETURN a.name AS alert, impacts, paged, warned, experts, c.id AS change, c.summary AS change_summary,
       c.kind AS change_kind, s.id AS cause_service, h.status AS cause_status, h.gaps AS cause_gaps,
       author.name AS author, collect(DISTINCT src.id) AS sources,
       collect(DISTINCT {id: rb.id, title: rb.title, steps: rb.steps, successes: rb.successes,
                         uses: rb.uses}) AS runbooks

// name: refuted_hypotheses
// purpose: Suspects the agents ruled out, with the reason recorded on their Evidence.
MATCH (:Incident {id: $incident_id})-[:HAS_HYPOTHESIS]->(h:Hypothesis)-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
WHERE h.status IN ['refuted', 'outranked']
MATCH (e:Evidence)-[:REFUTES]->(h)
RETURN c.id AS change, s.id AS service, c.summary AS summary, e.reason AS reason,
       coalesce(e.tag, 'ruled out') AS tag, h.source AS source, h.status AS verdict

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
OPTIONAL MATCH (d:Doc {id: cid})
WITH m, coalesce(c, t, msg, rb, p, d) AS n
WHERE n IS NOT NULL
MERGE (m)-[:CITES]->(n)
RETURN count(n) AS cited

// name: change_info
// purpose: One change and the service it touched.
MATCH (c:Change {id: $change_id})-[:CHANGED]->(s:Service)
RETURN c.id AS change, c.kind AS kind, c.summary AS summary, s.id AS service, s.name AS service_name

// name: resolve_incident
// purpose: A human-confirmed fix becomes memory: CAUSED_BY (episodic) and a Runbook for (service, change kind) whose success count grows (procedural). The confirmed change becomes the incident's confirmed hypothesis (created if no agent suspected it); any other surviving suspect is outranked by the human's call.
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
MERGE (h:Hypothesis {id: $hypothesis_id})
ON CREATE SET h.source = 'human', h.created_at = $at, h.explained = []
MERGE (i)-[:HAS_HYPOTHESIS]->(h)
MERGE (h)-[:SUSPECTS]->(c)
SET h.status = 'confirmed'
MERGE (e:Evidence {id: $evidence_id})
SET e.verdict = 'supports', e.reason = 'confirmed by a human', e.at = $at
MERGE (e)-[:SUPPORTS]->(h)
WITH i, rb, h
OPTIONAL MATCH (i)-[:HAS_HYPOTHESIS]->(o:Hypothesis)
WHERE o.id <> h.id AND o.status IN ['supported', 'co-cause']
FOREACH (x IN CASE WHEN o IS NULL THEN [] ELSE [o] END |
  SET x.status = 'outranked'
  MERGE (oe:Evidence {id: 'ev:' + substring(x.id, 4) + ':human'})
  SET oe.verdict = 'outranked', oe.reason = 'outranked: a human confirmed ' + $change_id + ' as the cause',
      oe.tag = 'a human confirmed another cause'
  MERGE (oe)-[:REFUTES]->(x))
RETURN DISTINCT i.id AS incident, rb.id AS runbook, rb.title AS title, rb.steps AS steps,
       rb.successes AS successes

// name: incident_paged
// purpose: Everyone paged for the incident, with their team.
MATCH (:Incident {id: $incident_id})-[pg:PAGED]->(p:Person)-[:MEMBER_OF]->(t:Team)
RETURN p.id AS person, p.name AS name, p.handle AS handle, t.id AS team, t.name AS team_name, pg.for_service AS service
ORDER BY pg.at, name

// name: incident_storm
// purpose: The alerts folded into the incident and its shared upstream (rank order), as recorded by correlate_alerts.
MATCH (i:Incident {id: $incident_id})
OPTIONAL MATCH (i)-[:CORRELATED_WITH]->(a:Alert)-[:FIRED_ON]->(s:Service)
WITH i, collect(DISTINCT {alert: a.id, name: a.name, service: s.id, at: a.at}) AS alerts
OPTIONAL MATCH (i)-[x:SHARED_UPSTREAM]->(u:Service)
WITH alerts, x, u ORDER BY x.rank
RETURN alerts, collect({service: u.id, hops: x.hops, rank: x.rank}) AS shared

// name: service_map
// purpose: Services, owners and dependency edges (flagged live or retired at $at) for the UI.
MATCH (t:Team)-[:OWNS]->(s:Service)
OPTIONAL MATCH (s)-[d:DEPENDS_ON]->(x:Service)
RETURN s.id AS id, s.name AS name, s.tier AS tier, t.name AS team,
       collect({to: x.id, live: d.valid_from <= $at AND (d.valid_to IS NULL OR d.valid_to > $at)}) AS deps

// name: incident_update
// purpose: The status update the comms agent last posted on the incident.
MATCH (:Incident {id: $incident_id})-[:HAS_UPDATE]->(m:Message)
RETURN m.text AS text

// name: incident_sources
// purpose: What the incident's status update cites (CITES edges), with a human title per node, so the UI can show "CR-881 Reduce idle connections" instead of an id.
MATCH (:Incident {id: $incident_id})-[:HAS_UPDATE]->(:Message)-[:CITES]->(n)
RETURN n.id AS id, labels(n)[0] AS kind,
       coalesce(n.title, n.summary, n.name, n.channel) AS title, n.at AS at
ORDER BY kind, at

// name: cause_context
// purpose: Company knowledge behind the cause: current docs that mention the culprit change, then decision records and postmortems about its service, written before the incident. The update cites them so the on-call engineer sees the decision history.
MATCH (:Incident {id: $incident_id})-[:HAS_HYPOTHESIS]->(h:Hypothesis)-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
WHERE h.status IN ['confirmed', 'supported']
MATCH (d:Doc)-[:DECIDES|MENTIONS]->(x)
WHERE (x = c OR x = s) AND d.at <= $at AND NOT ()-[:SUPERSEDES]->(d)
WITH DISTINCT d, max(CASE WHEN x = c THEN 1 ELSE 0 END) AS about_change,
     CASE d.kind WHEN 'decision' THEN 2 WHEN 'postmortem' THEN 1 ELSE 0 END AS weighty
RETURN d.id AS id, d.title AS title, d.kind AS kind, d.at AS at, about_change, weighty
ORDER BY about_change DESC, weighty DESC, at DESC
LIMIT 2
