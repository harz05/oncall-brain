// name: topology_at
// purpose: The dependency graph as it was at $at: every DEPENDS_ON edge live at that time. FalkorDB's algorithms walk every edge of a graph and the tenant graph keeps retired and not-yet-live dependencies as history, so this is what gets projected into a scratch graph for an algorithm to run on.
MATCH (a:Service)-[r:DEPENDS_ON]->(b:Service)
WHERE r.valid_from <= $at AND (r.valid_to IS NULL OR r.valid_to > $at)
RETURN a.id AS caller, b.id AS callee
ORDER BY caller, callee

// name: project_topology
// purpose: Build the point-in-time projection: runs on the scratch graph scratch_<tenant>_topology_<nonce>, which then holds only the edges live at the time in question.
UNWIND $edges AS e
MERGE (a:Service {id: e.caller})
MERGE (b:Service {id: e.callee})
MERGE (a)-[:DEPENDS_ON]->(b)
RETURN count(*) AS edges

// name: criticality
// purpose: Criticality of every service: PageRank over the dependency graph (a service is critical when services that many others rely on rely on it). Runs on the scratch projection, so a retired or not-yet-live dependency never adds rank.
CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node, score
RETURN node.id AS service, score
ORDER BY score DESC, service

// name: record_criticality
// purpose: Write the criticality order onto the incident board: IMPACTS.rank (1 = warn first) and IMPACTS.score (PageRank at alert time) on the impacted services.
UNWIND $rows AS r
MATCH (:Incident {id: $incident_id})-[x:IMPACTS]->(:Service {id: r.service})
SET x.rank = r.rank, x.score = r.score
RETURN count(x) AS ranked

// name: warn_candidates
// purpose: Who to warn: for every impacted service with a criticality rank, the on-call at $at of the team that owns it, best rank first, skipping teams the incident already paged (they know).
MATCH (i:Incident {id: $incident_id})
OPTIONAL MATCH (i)-[:PAGED]->(:Person)-[:MEMBER_OF]->(pt:Team)
WITH i, collect(DISTINCT pt.id) AS paged_teams
MATCH (i)-[x:IMPACTS]->(s:Service)<-[:OWNS]-(t:Team)<-[oc:ON_CALL]-(p:Person)
WHERE x.rank IS NOT NULL AND NOT t.id IN paged_teams AND oc.start <= $at AND oc.end > $at
RETURN t.id AS team, t.name AS team_name, p.id AS person, p.name AS name, p.handle AS handle,
       s.id AS service, s.tier AS tier, x.rank AS rank, x.score AS score
ORDER BY x.rank, s.id

// name: record_warning
// purpose: Record the heads-up sent to an impacted team's on-call (an action taken because of the criticality order), once per person.
UNWIND $rows AS r
MATCH (i:Incident {id: $incident_id}), (p:Person {id: r.person})
MERGE (i)-[w:WARNED]->(p)
ON CREATE SET w.at = $at, w.for_service = r.service, w.rank = r.rank
RETURN count(w) AS warned

// name: incident_warned
// purpose: Who got a heads-up on this incident, most critical service first.
MATCH (i:Incident {id: $incident_id})-[w:WARNED]->(p:Person)-[:MEMBER_OF]->(t:Team)
RETURN p.id AS person, p.name AS name, p.handle AS handle, t.name AS team, w.for_service AS service, w.rank AS rank
ORDER BY w.rank, p.id
