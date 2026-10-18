# Council transcript: advisors and critiques

## The Contrarian / Red-team skeptic

A wins, but only if you cut most of it. As pitched it is the riskiest idea on the list and it has four ways to fail. (1) Scope: three agents, ~40 services, Slack, tickets, ADRs, vector search, Q&A and memory write-back will not be ready by 11:30. You get a half-wired demo where everything is shallow. (2) A circular synthetic story: the generator plants a bad deploy upstream and the agent "finds" it. A judge will ask "you seeded the answer?" You need noise: several decoy deploys, plus at least one alert where the true answer is "no upstream change, it's capacity", so the agent visibly rules things out. (3) A fake agent: with a scripted mock planner, a skeptic will call it a hardcoded pipeline. Each next step has to branch on what the graph returns. Empty path means the service is cleared. A Tier-1 node in the blast radius means escalate. No deploy in the window means pivot to config changes. Show that branching in the trace. (4) Decorative graph pieces: PageRank on 40 nodes is theater, and "similar incidents via vector search" without an embedding model is fake. Replace it with graph-pattern similarity: same upstream service, same change type, same failure mode. That needs no model and is something only a graph can do. The "a recursive CTE could do this" attack needs an answer too: temporal edges (what was live at alert time), multi-hop suspect ranking and the incident-to-incident memory chain together make SQL look painful. For the 11:30 cut, drop the Comms agent and company Q&A (Track 03 can come back later). The 2-minute money shot is incident #2 recalling how incident #1 was resolved and skipping straight to the runbook that worked. Runner-up: C. It is derivative, but it is the only other idea where the graph is clearly load-bearing. B is code-graph, D is Mem0/Graphiti with nothing visible to demo, and E is Drift with mock-LLM extraction that will look faked.

**Proposed F:** F = A cut down to an "Incident Hypothesis Board". When an alert fires, Triage and Investigator agents write Hypothesis nodes with EVIDENCE/REFUTED_BY edges, each tied to a Cypher path, into a per-incident subgraph. Each one is confirmed or ruled out by temporal traversal (deploys and configs live at alert time, plus decoy changes), and "no path found" counts as a refutation. When an incident is resolved it becomes procedural memory, and the next alert recalls it through graph-pattern similarity rather than vectors. Comms, Q&A and PageRank are dropped until after 11:30.

| Idea | Ind | Demo | Feas | Tracks | Orig | Expl | Reason |
|---|---|---|---|---|---|---|---|
| A | 7 | 8 | 4 | 9 | 6 | 8 | Strongest concept, but the scope is huge for 4h20m, PageRank and vectors are decoration, Hopper and the X-Ray blog overlap, and the seeded answer looks circular unless decoys are added |
| B | 8 | 5 | 5 | 5 | 2 | 7 | FalkorDB already ships code-graph with git history, chat and MCP, so judges will see a clone immediately; ingesting a real repo's issues is slow too |
| C | 8 | 7 | 8 | 3 | 2 | 8 | WCC and label propagation are truly load-bearing and the lit-up rings demo well, but it is FalkorDB's own tutorial and covers only Track 01 |
| D | 3 | 3 | 6 | 5 | 2 | 4 | Memory fits in Postgres or Redis, so it fails the remove-FalkorDB test; nothing to see on screen, and with a mock LLM the research is fake; Graphiti, Mem0 and Atrium already own this |
| E | 5 | 4 | 6 | 4 | 2 | 7 | A Drift rerun; a mock LLM cannot extract decisions, so pre-structured synthetic data makes the core claim look faked |

**Critique round.** Strongest: Response 2. It is the only one that questions whether the demo is believable, not just how big it is. A seeded answer looks circular, so it adds decoy deploys and an incident caused by capacity rather than a change. A scripted planner looks hardcoded unless each step visibly depends on the previous query result. PageRank on 40 nodes and vectors with no embedding model are for show. Response 4 is a close second: it frames the choice around the removal test and adds GRAPH.RO_QUERY guards.

Biggest blind spot: Response 5. It says the mock planner hides the scope risk because it just calls the graph tools in order. A fixed sequence like that is exactly what judges will call a fake agent. It also keeps PageRank, puts MCP and multi-tenancy into the 11:30 slice, and picks E as runner-up even though Drift already did it. The "pull the plug" toggle in Responses 1 and 5 also proves nothing. Any app fails when its database is unplugged, so it does not show the graph beats Postgres.

What all missed: (a) With about 40 services, the real alternative is an in-memory networkx graph, not SQL. Traversal alone does not make FalkorDB necessary. The case has to rest on persistent incident state and memory that several agents read and write at once. (b) A seeded eval: about 30 generated incidents with decoys, comparing hit rate with the graph against a baseline without it. That is the numbers proof of rule 2, and judges praised an eval set before. (c) FalkorDB's X-Ray blog already demos blast radius and triage, so the demo should lead with learned memory, not blast radius.

## The First Principles Thinker / FalkorDB engineer judging the event

Pick A, cut down to its core. Runner-up: C. The council is asking "which idea," but the useful question is "which query stops working if FalkorDB is removed?" For B through E the honest answer is that not much breaks. D's memory works as a key-value or vector store; Mem0 runs without a graph. E's decision tracing is two or three foreign-key hops that SQL handles fine. B is real graph work, but it is FalkorDB's own code-graph. C has real graph work (WCC and labelPropagation find rings), but it is the textbook fraud demo FalkorDB already publishes, and it only fits one track.

A is the only option where the graph decides what the agent does next. The traversal is alert service <-[:DEPENDS_ON*1..4]- upstream service <-[:DEPLOYED_TO]- deploy, filtered to deploys live in the window before the alert, joined to the PR, its author, the author's team and who is on call. That is one Cypher pattern across 6 node types. In SQL it would need recursive CTEs, and nobody would want to explain them in a demo.

A also has weak spots I would cut or redo:
- PageRank on 40 services is decoration. Rank suspects by path length, change recency and betweenness on the dependency graph instead.
- Vector-only "similar incidents" is a vector-store feature. Make similarity structural: same upstream service failed, same change type. Use embeddings only as a tie-breaker.
- maxFlow for blast radius is a gimmick; skip it.
- The company-brain Q&A can be a thin read-only tool, not a pillar.

Guard every agent query with GRAPH.RO_QUERY. Remember shortestPath only works in WITH/RETURN.

The 2-minute demo: an alert fires and the graph path lights up, showing the deploy that caused it. The fix is written back as a Resolution and a learned Runbook. A second alert with the same shape is then resolved in one hop through memory. That shows the graph learning, which none of the other options can show.

**Proposed F:** F = A sharpened into a Hypothesis Graph. Each upstream deploy or config change found by traversal becomes a Hypothesis node. Investigator agents attach Evidence with SUPPORTS or REFUTES edges, and the deterministic planner picks its next tool by querying for open hypotheses with no evidence, so the agent's plan lives in the graph. A confirmed root cause is written back as Resolution plus Runbook (procedural memory). A second alert with the same structural shape (same upstream service and change type) is solved in one hop, which is the removal-test proof shown on camera.

| Idea | Ind | Demo | Feas | Tracks | Orig | Expl | Reason |
|---|---|---|---|---|---|---|---|
| A | 9 | 9 | 6 | 9 | 7 | 9 | Upstream deploy traversal across 6 node types drives the agent; risk is sprawl, so cut Q&A, PageRank and maxFlow to make 11:30. |
| B | 8 | 6 | 5 | 6 | 2 | 7 | Real graph work, but it is FalkorDB's code-graph, and AST plus git plus issue ingest is risky in 4h. |
| C | 8 | 7 | 9 | 3 | 2 | 7 | WCC and labelPropagation do genuine work and the rings look good, but it is FalkorDB's own textbook demo and fits one track. |
| D | 4 | 4 | 7 | 4 | 2 | 5 | Memory works without a graph (Mem0 proves it), concurrency is invisible on video, and Graphiti, Cognee and Atrium already cover it. |
| E | 5 | 5 | 8 | 4 | 2 | 7 | Decision tracing is shallow FK hops that SQL handles, and Drift already did contradiction and supersede detection. |

**Critique round.** Strongest: Response 4 is the strongest. It asks the right question: which query breaks if FalkorDB is removed? It writes out the actual traversal across six node types. It drops PageRank and maxFlow as decoration, and it flags GRAPH.RO_QUERY and the rule that shortestPath only works in WITH/RETURN. Its Hypothesis Graph stores the planner's state in the graph: the next tool is picked by querying for open hypotheses. That answers the 'scripted pipeline' charge. Response 2 adds what 4 is missing: decoy deploys and a capacity case with no upstream change, so the agent visibly rules suspects out.

Biggest blind spot: Response 5 has the biggest blind spot. It says the scripted plan 'just calls the tools in order', which is exactly the hardcoded-pipeline attack. It also keeps PageRank weighting, MCP and multi-tenancy in the 11:30 cut, and it picks E as runner-up even though E repeats Drift and needs an LLM to extract decisions. Responses 1 and 5 both rely on a 'pull the plug' toggle, but that proves nothing: any app breaks when its database is removed.

What all missed: Everyone missed the right ablation, which is graph versus a vector or flat-table baseline, not graph versus nothing. Run both on N seeded incidents with known answers and show an eval table where the baseline picks the decoy. They also missed the most graph-native moment: an alert storm. Five alerts fire, and the root cause is the shared upstream node whose blast radius covers all five. It should be computed on the topology as it was at alert time, using versioned DEPENDS_ON edges. That is one Cypher query, and SQL or vectors cannot do it cleanly.

## The Expansionist / Agent-systems architect

A is the only idea that can win all three track prizes and still have a life after the hackathon. Everything else is one track and already a FalkorDB showcase. A is also the idea where the graph does the most work. Blast radius is a traversal. Suspect ranking uses shortestPath from the alerting service to recent Deploy and ConfigChange nodes, weighted by PageRank. Ownership and on-call are 2-hop lookups. The agents hand off by writing to an Incident subgraph. Take FalkorDB out and nothing works, which is exactly what rule 2 asks for.

The bigger upside is memory that improves the agent over time. Build the demo around two incidents. Incident 1 is solved by triage, investigation and a human-confirmed fix. The resolution path is then turned into a procedural Runbook node: a NEXT_STEP chain of steps with success counts, linked to the services it fixed. Incident 2 fires on a nearby service. The agent recalls episode 1 using graph-pattern similarity (same dependency neighbourhood, same change type), not vectors alone, then runs the learned runbook and cites it. That is episodic, semantic and procedural memory, with a payoff on screen inside 2 minutes.

Add one graph per tenant (two companies, isolated). Also expose the same tools over an MCP server so Claude Desktop can call blast_radius, find_suspects and recall_similar. That covers Track 01 tool selection with almost no extra code. A good blog title would be "Teaching an on-call agent to remember."

Scope risk is real, but the mock planner hides it. The scripted plan just calls the graph tools in order, and the graph does the reasoning. Ship the triage, investigation, write-back and recall slice by 11:30. Add Q&A and comms later.

Runner-up: E, sharpened with temporal validity (valid_from/valid_to, SUPERSEDED_BY) so it isn't just Drift. It can also reuse the synthetic-company generator idea.

**Proposed F:** F, a sharper version of A: an on-call brain that learns. Agents post Hypothesis nodes onto the shared Incident subgraph with EVIDENCED_BY edges to deploys, config changes and messages, then mark each one CONFIRMED or REFUTED. When an incident is resolved, the confirmed path becomes a procedural Runbook (a NEXT_STEP chain with success stats). The next nearby incident recalls it through graph-pattern similarity, and a 'graph off' ablation toggle plus an MCP server prove the graph is load-bearing.

| Idea | Ind | Demo | Feas | Tracks | Orig | Expl | Reason |
|---|---|---|---|---|---|---|---|
| A | 9 | 9 | 6 | 10 | 8 | 9 | Traversal, paths, centrality, a shared incident subgraph and learned runbooks are the product. It covers all 3 tracks; scope is the only risk, and the mock planner plus a thin slice handles it. |
| B | 8 | 7 | 4 | 6 | 2 | 7 | Real graph value, but it is code-graph (git-history switching plus MCP already ship), and real-repo AST ingestion is a time sink. |
| C | 8 | 7 | 8 | 3 | 2 | 8 | Community detection does real work, but it is the textbook FalkorDB demo, Track 01 only, and has no memory or coordination story. |
| D | 5 | 4 | 7 | 5 | 2 | 5 | A memory desk can be built on a KV or vector store, so the graph risks being decoration; it also overlaps Graphiti, Cognee, Mem0 and Atrium. |
| E | 7 | 6 | 7 | 4 | 3 | 8 | Source tracing is good for Track 03 but overlaps Drift; it only stands out with temporal supersession, and the demo is text-heavy. |

**Critique round.** Strongest: Response 4 is the strongest. It asks the question rule 2 is about: which query stops working without FalkorDB? It answers with one concrete 6-node-type traversal and cuts the decorative parts (PageRank, maxFlow, vector-only similarity). Its Hypothesis Graph has the planner pick its next step by querying for open hypotheses. That keeps the plan itself in shared graph state, which counts toward Track 01 and Track 02 at once. It should be combined with Response 2's decoys and "it's capacity" negative case, so the seeded answer doesn't look circular.

Biggest blind spot: Response 5 has the biggest blind spot. It says the mock planner "just calls the graph tools in order." A planner that does that is the hardcoded pipeline Response 2 warns about, and in it the graph shapes nothing. It also keeps PageRank weighting and loads MCP, tenants and NEXT_STEP runbooks into the 11:30 slice. Its runner-up, E, is the Drift rerun that Responses 2 and 4 take apart.

What all missed: Every response treats the removal test as a staged moment, either a toggle or a second run. None of them makes it something you can measure. The seeded generator can produce N scenarios, each with a known root cause and decoys. Accuracy with the graph on versus off then becomes a number for the README, much like Board of SuperVision's 30/30. A tenant-swap test belongs in the same evaluation: the same alert in a second tenant graph, with a different topology and memory, should lead to a different action. That shows the graph decides behaviour, and it puts per-tenant isolation on screen. The evaluation should also include wrong memory: a recalled runbook that gets refuted should lose its standing. Otherwise procedural memory only ever grows.

## The Outsider / Demo storyteller

I'm judging this from the viewer's seat. I have 2 minutes of video, I know nothing about the domain, and I need a reason to care in the first 20 seconds. A is the only idea on the list with stakes a non-expert feels straight away: "Checkout is broken, customers can't pay. Who broke it, who do we wake up, and what fixed it last time?" Everyone has seen a site go down. The best moment would be the graph lighting up a red path from the alert, three hops upstream, to a config change another team shipped 40 minutes ago, with the agent naming the on-call person and the runbook that fixed this before. Then a second, similar incident comes in, and the agent jumps straight to the answer and cites the first one. That replay shows memory working without anyone having to explain it.

A's danger is the curse of knowledge. "p99", "blast radius", "PageRank", "ADR" and "episodic/procedural memory" mean nothing to a viewer. Say them in plain words in the video and leave the jargon for the README and the blog. The other danger is a feature tour. Six agents and company Q&A will not fit in 2 minutes. Tell one story (alert, culprit, fix, remembered) and give Q&A a 10-second coda at most.

C is the most visual (fraud rings that light up), but judges have seen it many times and it covers only one track. B is FalkorDB's own code-graph product, so it would look like a copy. D can't be seen: you can't film memory being shared, and it would work just as well on a key-value store. E is mostly reading text, and Drift has already done it.

Make rule 2 visible: add a "pull the plug" toggle. With the graph switched off, the agent says it doesn't know what changed or who to page. Judges will remember that moment.

**Proposed F:** Sharpen A into a two-act "Second Page" story. In act 1 the agents find the culprit for a checkout outage through a highlighted multi-hop path and write the fix back to the graph. In act 2 a similar outage a week later is solved in seconds, matched by graph pattern and citing act 1. Add a live "pull the plug" toggle where the agent, with FalkorDB disconnected, admits it can't say what changed or who to page. That makes graph indispensability the climax of the demo.

| Idea | Ind | Demo | Feas | Tracks | Orig | Expl | Reason |
|---|---|---|---|---|---|---|---|
| A | 9 | 9 | 6 | 10 | 7 | 9 | Stakes anyone feels and a red path from alert to culprit deploy; the risk is scope creep and jargon, so cut it to one story arc. |
| B | 8 | 5 | 5 | 6 | 2 | 7 | Only developers care, ingesting a real repo is slow, and FalkorDB judges will see a copy of their own code-graph. |
| C | 8 | 8 | 9 | 3 | 2 | 7 | Rings lighting up land instantly, but it's the classic graph demo and covers one track only. |
| D | 4 | 3 | 7 | 5 | 2 | 4 | Shared memory can't be seen on video, and the product still works without the graph (Graphiti/Mem0 already exist). |
| E | 6 | 5 | 8 | 5 | 3 | 8 | "Why did we pick Kafka" is relatable but text-heavy and lacks drama, and Drift already did it. |

**Critique round.** Strongest: Response 2. It is the only one that watches the demo the way a skeptical judge would. It asks "you seeded the answer?" and fixes that with decoy deploys and a "no change, it's capacity" case. It wants every planner branch to depend on what the graph returns, so the agent doesn't look hardcoded. It also says PageRank on 40 nodes and vectors without a model are theater. Response 4 is close behind, because its "plan lives in the graph" hypothesis loop is the sharpest version of rule 2.

Biggest blind spot: Response 5. It says the mock planner "hides" scope risk, then adds MCP, multi-tenant graphs, PageRank weighting and all three tracks. On video that becomes a jargon-heavy feature tour with no single story. Its runner-up, E, is a text-heavy Drift rerun.

What all missed: Nobody planned for what actually shows on screen, and all four points below need to be designed in.
1. A 40-node Cytoscape graph at 1080p is an unreadable hairball. Render only the lit path, with large labels and plain-English captions.
2. Judges remember one number. Show a before/after counter such as "steps to culprit: 7, then 1 on the second incident".
3. Label the scripted planner honestly on screen ("deterministic planner, graph picks each branch") so it isn't mistaken for a faked LLM.
4. The runner-up needs to be different enough from A that the runner-up is not wasted.

## The Executor / Pragmatic shipper

Build A, but only as a narrow vertical slice by 11:30. Everything else gets added afterwards. A is the only idea that scores well on everything except feasibility, and its feasibility problem is scope, not the hard parts. Every core step is plain Cypher on data we plant ourselves: blast radius uses variable-length paths, criticality uses algo.pageRank, the on-call lookup is a 2-hop match, and suspect deploys come from shortestPath from the alert to a Deploy node filtered by time.

Without an LLM key, the scripted planner is actually a strength. It can branch on query results (no upstream deploy found, so check config changes; a matching past incident found, so try its runbook first). That makes "the graph decides what the agent does" literally true and easy to show.

First hour: start FalkorDB on the HDD. Then write a seeded generator with about 25 services, 6 teams, 20 people, rotations, 30 deploys and 8 past incidents, all random except one planted story: checkout p99 is slow because payments-gw shipped a deploy 2h ago, and INC-142 was fixed by runbook RB-7.
Hour 2: 6 Cypher tool functions, each with a smoke test.
Hour 3: planner state machine, FastAPI and a step log.
Hour 4: a Cytoscape page that highlights the path and shows the Cypher.

Cut by 11:30: vector search (use graph-pattern similarity on shared services and symptoms instead, which is the gap nobody has claimed), the Slack/ticket/ADR spread beyond one "why Kafka" chain, the MCP server, per-tenant graphs, and concurrency. The comms agent fills a template.

Runner-up: C. It has the least data work, one algorithm, and indispensability you can't argue with. It is unoriginal, but it is safe to ship. B, D and E either depend on an LLM to look smart (D, E) or duplicate code-graph (B).

**Proposed F:** A, sharpened into a two-run demo. Run 1: the alert fires, the planner traverses the graph, the human confirms the planted deploy as root cause, and the resolution is written back as an (:Incident)-[:RESOLVED_BY]->(:Runbook) memory. Run 2: a similar alert on a different service matches the past incident by shared-subgraph pattern and goes straight to that runbook, with the reason shown as a highlighted path. This gives the strongest 2-minute "remove FalkorDB and it breaks" story.

| Idea | Ind | Demo | Feas | Tracks | Orig | Expl | Reason |
|---|---|---|---|---|---|---|---|
| A | 9 | 9 | 7 | 9 | 8 | 9 | Path, centrality and on-call queries drive every planner branch. Feasible only if the 11:30 cut is one planted incident, 6 tools and no vectors. |
| B | 8 | 6 | 6 | 6 | 2 | 7 | Real data saves generation, but AST, git and issues ingest is fiddly, 'why does this exist' needs an LLM, and it is code-graph again. |
| C | 9 | 7 | 9 | 3 | 2 | 8 | Fastest build (a generator plus WCC/labelPropagation and one path query), but it covers one track and is FalkorDB's own blog demo. |
| D | 4 | 4 | 6 | 5 | 2 | 5 | Memory could live in a KV store, so the graph looks like decoration. A scripted planner doing 'research' looks hollow, and Graphiti/Mem0 already own this. |
| E | 6 | 5 | 8 | 5 | 3 | 8 | Easy to seed, but without LLM extraction it is a lookup over pre-structured links, and Drift already did it. |

**Critique round.** Strongest: Response 3 is the only plan you can actually run. It sizes the data (25 services, 30 deploys, 8 past incidents, one planted story), lays out hour by hour what gets built, says what to cut by 11:30, and turns the mock planner into a strength by making it branch on what queries return. Response 2 comes close. Its decoy deploys and its "capacity, no upstream change" case answer the "you seeded the answer" attack.

Biggest blind spot: Response 5 says "the mock planner hides scope risk," but it doesn't. Most of the time goes into the generator, the tools and the UI. It also puts per-tenant graphs, an MCP server, PageRank weighting and NEXT_STEP runbooks with success stats into the 11:30 slice. Its runner-up (E) is also weak, because without an LLM to extract the data it looks faked.

What all missed: Making the demo repeatable. Act 2's recall depends on act 1 writing to the graph, so every take changes the state. That needs a pinned demo clock, timestamps stored as epoch ints relative to that clock, a /reset that reloads a pristine seed (GRAPH.COPY), and the planted story hand-written as a fixture with only the noise randomized. Build a walking skeleton first (one query, then the API, then Cytoscape), and record a fallback run in case the live demo fails.
