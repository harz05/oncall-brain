## Where the Council Agrees

- **A is the winner.** All five advisors chose it, for the same reasons. It is the only idea where the graph decides what the agent does next. It is the only one that plausibly covers all three tracks. No FalkorDB showcase or past hackathon project does incident or on-call work.
- **A only works if it is cut hard.** Three agents, Slack, ADRs, Q&A, vectors and comms will not be ready by 11:30. Everyone converged on the same slice: triage, then investigate, then write back the resolution, then recall it on a second incident.
- **The money shot is memory, not blast radius.** Incident #1 is solved by multi-hop traversal and written back as a Resolution and a Runbook. Incident #2 has the same structural shape and is solved in one hop by recalling #1. All five landed on this two-act story in some form.
- **Similarity must be structural, not vector.** "Same upstream service, same change type, same failure mode" needs no model, is truly graph-native and fills a gap nobody else has claimed. Embeddings are at most a tie-breaker later.
- **PageRank on about 40 nodes and maxFlow for blast radius are decoration.** Cut them.
- **The deterministic planner must visibly branch on what each query returns.** An empty path clears a suspect. No deploy in the window means pivoting to config changes. A matching past incident means trying its runbook first.
- **Runner-up: four of five chose C.** It is unoriginal, but the graph is clearly load-bearing and it is the safest thing for the rival team to ship.

## Where the Council Clashes

- **The "pull the plug" toggle** (Outsider and Expansionist) **versus measured ablation** (Contrarian and First Principles in review). **Ruling: drop the toggle.** Every app fails when its database is removed, so the toggle proves nothing. Replace it with a comparison against a flat baseline: "most recent deploy anywhere" or keyword match on past incidents. On screen this is one scenario where the baseline picks the decoy and the graph picks the deploy on the dependency path. In the README it is an eval table over N seeded scenarios.
- **What goes in the 11:30 slice** (MCP, tenants, PageRank weighting, NEXT_STEP runbooks with stats). The Expansionist wanted these in; everyone else wanted them out. **Ruling: out.** The tools are pure functions, so MCP can wrap them in about 30 minutes after 11:30. Tenant-swap is a strong demo beat for day 2, not hour 3.
- **Runner-up: E** (Expansionist) **versus C** (the other four). **Ruling: C.** E repeats Drift and needs LLM extraction to look real. With a mock LLM it looks faked.
- **Whether to lead with blast radius.** The Contrarian notes FalkorDB's X-Ray blog already demos blast radius and triage. **Ruling:** act 1 still finds the culprit by traversal, but the headline frame and the closing number belong to act 2 (memory) and the eval.

## Blind Spots the Council Caught

1. **The seeded answer looks circular.** The generator has to plant decoys:
   - a more recent deploy that is not on the dependency path;
   - an upstream deploy that was rolled back before the alert;
   - eventually, a "no change, it's capacity" scenario.

   The agent has to visibly rule suspects out.
2. **"networkx could do this."** Traversal alone does not justify FalkorDB. The case rests on three things together:
   - persistent incident and hypothesis state that several agents read and write;
   - temporal edges ("what was live at alert time");
   - an incident-to-incident memory chain that outlives the process.
3. **An eval with numbers beats a staged moment.** Use N seeded scenarios with known root causes and decoys, and report hit rate for the graph versus the flat baseline. This echoes the 30/30 eval that judges praised in Board of SuperVision.
4. **Demo repeatability.** Act 2 depends on act 1's write-back. That needs:
   - a pinned demo clock, with timestamps stored as epoch ints relative to it;
   - a `/reset` that restores a pristine seed via `GRAPH.COPY`;
   - the planted story hand-written as a fixture, with only the noise randomized;
   - a recorded fallback take.
5. **On-screen readability.**
   - A 40-node Cytoscape hairball is unreadable, so render the lit path plus one hop of context.
   - Use plain-English captions.
   - Show one counter: "steps to culprit: 7, then 2".
   - Label the planner honestly: "deterministic planner, graph picks each branch".
6. **Later ideas for Track 02 and indispensability:**
   - An alert storm, where the root cause is the shared upstream node whose blast radius covers all five alerts, computed on versioned `DEPENDS_ON` edges.
   - A tenant swap, where the same alert in a different tenant graph leads to a different action.
   - Runbook confidence that drops when a recalled fix is refuted.

## The Recommendation

**Winner: A, On-call Brain, built as the "Incident Hypothesis Board" two-act story.** I agree with the weighted ranking (A 8.22, C 6.36). A's feasibility score of 6.2 only holds under the cut scope below.

Fold in the proposed F variants as follows:
- **From First Principles (the plan lives in the graph).**
  - Each suspect found by traversal becomes a `(:Hypothesis)` node attached to the `(:Incident)`.
  - Checks attach `(:Evidence)` with `SUPPORTS` or `REFUTES` edges.
  - The planner's next action is chosen by querying `MATCH (i)-[:HAS_HYPOTHESIS]->(h {status:'open'}) WHERE NOT (h)<-[:SUPPORTS|REFUTES]-() ...`. Agent state and handoffs are shared graph state, which counts toward Track 02 as well as Track 01.
- **From the Contrarian.** Add decoys and refutations, and treat "no path found" as a refutation that is shown on screen.
- **From the Executor and the Outsider.** Use the two-act structure. Act 1 ends with the root cause confirmed, then the Resolution is written, then the learned `Runbook` linked by `FIXED_WITH`. Act 2 is a similar alert on a different downstream service. It recalls act 1 through structural overlap (same upstream service and change type) and goes straight to the runbook.
- **From the Expansionist (after 11:30).** Add the MCP server, tenant swap, and a NEXT_STEP runbook chain with success counts.
- **Replace** the "pull the plug" toggle with the baseline ablation and the eval table.

**Runner-up: C, Fraud Ring Investigator.** It is distinct from A: a different domain, no ops or runbook memory, and no shared generator story. It is buildable, and the graph is clearly load-bearing. To lift its originality, the rival should sharpen it this way:
- WCC or labelPropagation to surface rings.
- `algo.maxFlow` from victim accounts to cash-out nodes for a money trail. This is a place where maxFlow is actually meaningful.
- Shared device and IP paths as the explanation.
- The agent proposes concrete actions (freeze, step-up auth, hold) with the path that justifies each one.

C mainly fits Track 01.

## Top 3 Risks of the Winner and Mitigations

1. **"It's a hardcoded pipeline answering a question you seeded."**
   - The planner picks its next step by querying open hypotheses and branches on results.
   - Two decoys per scenario are refuted on screen, each with the Cypher that refuted it.
   - The noise is randomized per seed, and an eval over N seeds shows the result is not one lucky fixture.
   - The UI says honestly that the planner is deterministic.
   - The capacity, no-change case is the first item after 11:30.
2. **Scope blowout misses 11:30.**
   - Build a walking skeleton first: one query, then the API, then the UI.
   - Write the planted story as a fixture, so the generator only adds noise.
   - Keep to six tools and a hard cut list.
   - Gate at 10:30: if act 2 isn't working through the API, freeze the UI polish and make the write-back and recall work end to end, even if it is ugly.
3. **The "graph is decoration" or "networkx/SQL could do it" attack.**
   - Base the case on temporal validity at alert time, the persistent shared Hypothesis and Incident subgraph, and the incident-to-incident memory chain.
   - In the README, list each Cypher query and what fails without it.
   - Show the baseline picking the decoy.
   - Use `GRAPH.RO_QUERY` for every read tool and keep writes to explicit, narrow write tools.
   - Keep the queries few and readable so Harsh can explain every one.

## Scope for the 11:30 prototype

**Must-have demo flow**
1. `/reset` restores the pristine seed with `GRAPH.COPY`, at a pinned demo clock.
2. **Act 1.** The alert "checkout is slow" arrives.
   - **Triage:** the blast radius is shown (downstream dependents), and `on_call_for` names the person to page.
   - **Investigate:** `find_suspects` traverses `(alertSvc)-[:DEPENDS_ON*0..4]->(up)<-[:DEPLOYED_TO|CHANGED]-(change)` filtered to the time window before the alert. Results become Hypothesis nodes.
   - **Refute:** two decoys. One is off the dependency path; flat retrieval would have picked it, and the baseline result is shown beside it. The other was rolled back before alert time.
   - **Confirm:** the payments-gw config change is confirmed by an Evidence query on intermediate services (the error signature appears along the path).
   - **Write back:** a human clicks "confirm", which writes the `Resolution` and the `Runbook` linked by `FIXED_WITH`.
3. **Act 2.** "Refunds is slow" (same upstream payments-gw) arrives.
   - `recall_similar` finds act 1 by structural overlap.
   - The planner tries its runbook first and confirms in about 2 steps instead of 7.
   - The counter shows the drop and the path from INC-2 to INC-1 to the Runbook is lit.
4. **UI:**
   - Cytoscape renders only the lit path plus one hop.
   - A step log shows each step's tool, Cypher, result and branch taken.
   - A "deterministic planner, graph picks each branch" label is shown.

**Data:** about 25 services, 6 teams, 20 people, rotations, 30 deploys and config changes, and 8 past incidents. Timestamps are epoch ints, and `DEPENDS_ON` carries `valid_from`/`valid_to`.

**Tools (6):** `blast_radius`, `on_call_for`, `find_suspects`, `check_hypothesis`, `recall_similar`, `write_resolution`.

**Explicitly cut until after 11:30**, in this order of return:
1. The eval harness (N=30, graph vs baseline).
2. The capacity, no-change scenario.
3. The MCP server.
4. Tenant swap.
5. The alert storm.
6. Thin Track 03 Q&A ("who owns/knows X", "why Kafka", with sources).
7. The template comms agent.
8. Runbook confidence decay.
9. A real-LLM planner.

**Cut entirely:** PageRank, maxFlow, vector search and embeddings, and the Slack/ticket/ADR spread beyond one sourced chain.

## The One Thing to Do First

Do these in order:
1. Start FalkorDB with its data dir on the HDD.
2. Hand-write the act 1 fixture: the alert service, the dependency chain, the planted payments-gw change, and the two decoys.
3. Run the single `find_suspects` Cypher with the time window and temporal-validity filter against it.
4. Confirm that it returns the planted change, excludes the decoy that is off the path, and flags the rolled-back decoy as refuted.

Every other piece hangs off that query.

Winner: A On-call Brain (Incident Hypothesis Board)
Runner-up: C Fraud Ring Investigator