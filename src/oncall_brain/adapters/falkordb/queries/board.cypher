// name: incident_board
// purpose: Everything the planner looks at, read fresh from the graph before every decision: steps already taken, hypotheses and their status, recalled memory.
MATCH (i:Incident {id: $incident_id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(o:Service)
OPTIONAL MATCH (i)-[:LOGGED]->(st:AgentStep)
WITH i, a, o, collect({tool: st.tool, target: st.target, role: st.role}) AS steps
OPTIONAL MATCH (i)-[:HAS_HYPOTHESIS]->(h:Hypothesis)-[:SUSPECTS]->(c:Change)-[:CHANGED]->(s:Service)
WITH i, a, o, steps,
     collect({id: h.id, change_id: c.id, service: s.id, status: h.status, source: h.source, hops: h.hops,
              at: c.at, explained: h.explained, onset: h.onset, gaps: h.gaps}) AS hypotheses
OPTIONAL MATCH (i)-[x:RECALLS]->(past:Incident)
WITH i, a, o, steps, hypotheses,
     collect({incident: past.id, score: x.score, cause_service: x.cause_service}) AS recalls
OPTIONAL MATCH (other:Alert)
WHERE other.id <> a.id AND other.at >= a.at - $storm_window AND other.at <= a.at
WITH i, a, o, steps, hypotheses, recalls, count(other) AS storm
OPTIONAL MATCH (i)-[:CORRELATED_WITH]->(:Alert)-[:FIRED_ON]->(cs:Service)
WITH i, a, o, steps, hypotheses, recalls, storm, collect(DISTINCT cs.id) AS correlated
OPTIONAL MATCH (i)-[su:SHARED_UPSTREAM]->(u:Service)
WITH i, a, o, steps, hypotheses, recalls, storm, correlated, u, su
ORDER BY su.rank
RETURN i.id AS id, i.status AS status, o.id AS service, a.id AS alert, a.at AS at, a.symptom AS symptom,
       steps, hypotheses, recalls, storm, correlated, collect(u.id) AS shared_upstream

// name: log_step
// purpose: Persist each agent step on the incident (queryable agent history; handoffs between roles are steps too).
MATCH (i:Incident {id: $incident_id})
OPTIONAL MATCH (i)-[:LOGGED]->(prev:AgentStep)
WITH i, count(prev) AS n
CREATE (st:AgentStep {id: $incident_id + '#' + toString(n + 1), seq: n + 1, role: $role, tool: $tool,
                      target: $target, reason: $reason, summary: $summary, rows: $rows, ms: $ms,
                      writes: $writes})
CREATE (i)-[:LOGGED]->(st)
RETURN st.seq AS seq

// name: incident_steps
// purpose: Replay an incident's persisted agent history in order.
MATCH (i:Incident {id: $incident_id})-[:LOGGED]->(st:AgentStep)
RETURN st.seq AS seq, st.role AS role, st.tool AS tool, st.target AS target, st.reason AS reason,
       st.summary AS summary
ORDER BY seq
