// name: session_context
// purpose: Conversation memory for pronouns: the entities (ABOUT) of the latest question in the session that was about something, so a follow-up's "it" or "them" can be read as them, with that question's text and position so the answer can say where "it" came from.
MATCH (s:Session {id: $session_id})-[:ASKED]->(q:Question)-[ab:ABOUT]->(x)
WITH q, ab, x
ORDER BY q.seq DESC, ab.carried, x.id
WITH q, collect({id: x.id, kind: toLower(labels(x)[0]), name: coalesce(x.name, x.title, x.summary),
                 carried: ab.carried}) AS entities
ORDER BY q.seq DESC
LIMIT 1
RETURN q.id AS question, q.seq AS seq, q.text AS text, entities

// name: record_question
// purpose: Conversation memory: append a question to the asker's session (created on first use and OPENED by the Person when the user is one) as a Question node with its position in the session (seq), the question before it (FOLLOWS), the entities it was about (ABOUT; carried = true when the entity came from a pronoun read against the previous question) and the sources the answer cited (ANSWERED_WITH, in rank order). Run under the session's lock: seq is the session's question count + 1, and the unique constraint on Question.id refuses a duplicate if a writer ever skips the lock.
MERGE (s:Session {id: $session_id})
ON CREATE SET s.user = $user, s.key = $key, s.started_at = $at
SET s.last_at = $at
WITH s
OPTIONAL MATCH (p:Person)
WHERE p.id = $user OR p.handle = $user
FOREACH (x IN CASE WHEN p IS NULL THEN [] ELSE [p] END | MERGE (x)-[:OPENED]->(s))
WITH DISTINCT s
OPTIONAL MATCH (s)-[:ASKED]->(prev:Question)
WITH s, prev
ORDER BY prev.seq DESC
WITH s, collect(prev) AS prevs
CREATE (q:Question {id: s.id + '#' + toString(size(prevs) + 1), seq: size(prevs) + 1, text: $text,
                    resolved: $resolved, intent: $intent, at: $at, summary: $summary, answer: $answer})
CREATE (s)-[:ASKED]->(q)
FOREACH (last IN CASE WHEN size(prevs) = 0 THEN [] ELSE [prevs[0]] END | CREATE (q)-[:FOLLOWS]->(last))
WITH q
// Lookups per label so the id indexes are used; the empty-id sentinel keeps the row alive when a list is empty.
UNWIND $about + [{id: '', matched: '', carried: false}] AS e
OPTIONAL MATCH (es:Service {id: e.id})
OPTIONAL MATCH (et:Team {id: e.id})
OPTIONAL MATCH (ep:Person {id: e.id})
OPTIONAL MATCH (ec:Change {id: e.id})
OPTIONAL MATCH (ek:Ticket {id: e.id})
OPTIONAL MATCH (ei:Incident {id: e.id})
OPTIONAL MATCH (en:Initiative {id: e.id})
WITH q, e, coalesce(es, et, ep, ec, ek, ei, en) AS x
FOREACH (_ IN CASE WHEN x IS NULL THEN [] ELSE [1] END |
  MERGE (q)-[:ABOUT {matched: e.matched, carried: e.carried}]->(x))
WITH DISTINCT q
UNWIND $sources + [{id: '', rank: 0}] AS r
OPTIONAL MATCH (sd:Doc {id: r.id})
OPTIONAL MATCH (st:Ticket {id: r.id})
OPTIONAL MATCH (sm:Message {id: r.id})
OPTIONAL MATCH (sr:Runbook {id: r.id})
OPTIONAL MATCH (si:Incident {id: r.id})
WITH q, r, coalesce(sd, st, sm, sr, si) AS y
FOREACH (_ IN CASE WHEN y IS NULL THEN [] ELSE [1] END | MERGE (q)-[:ANSWERED_WITH {rank: r.rank}]->(y))
WITH DISTINCT q
RETURN q.id AS question, q.seq AS seq

// name: user_questions
// purpose: What an engineer asked before ("what did I ask about payments-gw"): their questions across every session, or in one ($session), newest first, each with the entities it was about (ABOUT) and the sources its answer cited (ANSWERED_WITH); only questions about one of $ids, or whose text contains $text, when either is given.
MATCH (s:Session)-[:ASKED]->(q:Question)
WHERE s.user IN [$user, 'person:' + $user, '@' + $user] AND ($session IS NULL OR s.key = $session)
OPTIONAL MATCH (q)-[ab:ABOUT]->(x)
WITH s, q, collect(CASE WHEN x IS NULL THEN null ELSE {id: x.id, kind: toLower(labels(x)[0]),
                   name: coalesce(x.name, x.title, x.summary), carried: ab.carried} END) AS about
WHERE (size($ids) = 0 AND $text IS NULL)
   OR any(e IN about WHERE e.id IN $ids)
   OR ($text IS NOT NULL AND toLower(q.text) CONTAINS $text)
OPTIONAL MATCH (q)-[aw:ANSWERED_WITH]->(src)
WITH s, q, about, aw, src
ORDER BY aw.rank
WITH s, q, about, collect(CASE WHEN src IS NULL THEN null ELSE {id: src.id, kind: labels(src)[0],
                          title: coalesce(src.title, src.channel), rank: aw.rank} END) AS sources
RETURN s.id AS session, s.key AS key, q.id AS id, q.seq AS seq, q.at AS at, q.text AS text, q.resolved AS resolved,
       q.intent AS intent, q.summary AS summary, q.answer AS answer, about, sources
ORDER BY q.at DESC, q.seq DESC
LIMIT $limit
