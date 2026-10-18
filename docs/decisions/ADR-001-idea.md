# ADR-001: Which idea we build

Winner: A On-call Brain (Incident Hypothesis Board)
Runner-up: C Fraud Ring Investigator

- Status: accepted, 2026-10-15 07:08 IST
- Deciders: autonomous build agent (Claude Code, Opus) via an LLM council; reviewed by Harsh
- Method: `llm-council` skill (Karpathy-style). 5 independent advisors, each pairing a council thinking style with one judging persona from the brief, scored ideas A-E on the weighted rubric; each advisor then critiqued the other four anonymised responses and revised scores; a chairman synthesised. Weighted totals are computed in code from the revised scores, not by the chairman.

## Context
Graph Hacks (WeMakeDevs x FalkorDB): build an agent with FalkorDB as its context layer; "if the product still works once FalkorDB is taken out, the graph is decoration". Three tracks: 01 agents acting on connected data, 02 agent memory & coordination, 03 company brain. A demo-able prototype is due 11:30 IST today; no LLM key is available, so the demo must run on a deterministic planner.

Exploration of FalkorDB's showcases, community projects and past hackathon entries found:
- B (repo archaeologist) is FalkorDB's own code-graph (it even has git-history switching).
- C (fraud rings) is covered by FalkorDB's fraud guides and is a classic demo.
- D (shared-memory desk) overlaps Graphiti / Cognee / Mem0 and past winner Atrium.
- E (decision tracer) overlaps past entry Drift.
- A (on-call brain): no incident/on-call showcase exists; partial overlap only with Hopper (security blast radius) and FalkorDB's "X-Ray vision into data pipelines" blog.

## Scores (average of 5 advisors' revised scores, 1-10)

| Idea | Indispensable 25% | Demo 20% | Feasible 15% | Tracks 15% | Original 15% | Explainable 10% | **Weighted** |
|---|---|---|---|---|---|---|---|
| **A On-call Brain** | 8.8 | 8.8 | 6.2 | 9.2 | 7.0 | 9.0 | **8.22** |
| C Fraud rings | 8.4 | 7.0 | 9.0 | 3.0 | 2.0 | 7.6 | 6.36 |
| B Repo archaeologist | 8.0 | 5.2 | 5.0 | 6.0 | 2.0 | 7.0 | 5.69 |
| E Decision tracer | 5.2 | 4.6 | 7.0 | 4.2 | 2.8 | 7.0 | 5.02 |
| D Research desk | 3.4 | 3.0 | 6.2 | 5.0 | 2.0 | 4.0 | 3.83 |

All five advisors picked A. Four of five picked C as runner-up (one picked E; overruled because E repeats Drift and needs LLM extraction to look real).

## Decision: what "A" means concretely
A is built as an **Incident Hypothesis Board** told in **two acts**:

1. **Act 1 (reasoning).** Alert "checkout is slow". Triage finds blast radius and who is on call. Investigator traverses upstream `DEPENDS_ON` paths to changes (deploys / config changes) that were live in the window before the alert; each becomes a `(:Hypothesis)` on the `(:Incident)`. Checks attach `(:Evidence)` via `SUPPORTS` / `REFUTES`. Two planted decoys are refuted on screen (one is off the dependency path, one was rolled back before the alert). The planted cause is confirmed. A human confirms; the resolution and a learned `(:Runbook)` are written back.
2. **Act 2 (memory).** Alert "refunds is slow" (same upstream). The agent recalls act 1 by **structural** similarity (same upstream service, same change type), tries its runbook first and confirms in ~2 steps instead of ~7. The INC-2 -> INC-1 -> Runbook path lights up.

Folded-in council refinements:
- **The plan lives in the graph.** The planner chooses its next action by querying open hypotheses without evidence, so handoffs between agent roles are shared graph state (Track 02), not Python variables.
- **Similarity is structural, not vector**: graph-native and model-free, so it works without keys.
- **Decoys and refutation**: "no path found" is shown as a refutation, with the Cypher that refuted it.
- **Baseline ablation instead of a "pull the plug" toggle**: a flat baseline ("most recent change anywhere") picks the decoy, the graph picks the real cause. Later this becomes an eval table over N seeded scenarios.
- **Repeatable demo**: pinned demo clock, epoch-int timestamps, `/reset` via `GRAPH.COPY` from a pristine seed graph.
- **Readable UI**: render the lit path plus one hop, plain-English captions, a "steps to culprit" counter, and an honest "deterministic planner, the graph picks each branch" label.
- **Cut**: PageRank and maxFlow on ~25 nodes (decoration), vector search, and a Slack/ticket/ADR sprawl beyond one sourced chain.

Return order after 11:30: eval harness (graph vs baseline), "no change, it's capacity" scenario, MCP server, tenant swap, alert storm (common upstream root cause), thin Track 03 Q&A (who owns/knows X, why we chose Y, with sources), template comms agent, runbook confidence decay, real-LLM planner.

Deviation from the council, logged here: the brief's milestone M5 (11:00) asks for a runnable MCP server. Because every tool is defined once in a registry, the MCP surface is a thin wrapper, so we keep it in M5 if on schedule and make it the first cut otherwise.

## Runner-up: C Fraud Ring Investigator
Synthetic accounts, devices, IPs, cards, merchants and transactions. The agent:
- surfaces rings with `algo.WCC` / `algo.labelPropagation` over shared-device / shared-IP edges;
- follows the money trail from victim accounts to cash-out nodes with `algo.maxFlow` (a place where maxFlow is meaningful);
- explains each ring by its shared device / IP paths;
- proposes concrete actions (freeze, step-up auth, hold), each justified by the path that triggered it.
Mainly Track 01.

## Top 3 risks of the winner and mitigations
1. **"Hardcoded pipeline answering a question you seeded."** The planner branches on query results (open hypotheses, empty paths); two decoys are refuted on screen with their Cypher; noise is randomized per seed; an eval over N seeds shows it is not one lucky fixture; the UI labels the planner honestly as deterministic.
2. **Scope blowout misses 11:30.** Walking skeleton first (one query, then API, then UI). The planted story is a hand-written fixture and the generator only adds noise. Six tools, hard cut list. Gate at 10:30: if act 2 does not work through the API, freeze UI polish and finish write-back + recall.
3. **"networkx / SQL could do it."** The case rests on temporal validity at alert time, the persistent shared Hypothesis/Incident subgraph several agents read and write, and an incident-to-incident memory chain that outlives the process. README lists each Cypher query and what fails without it; every read tool uses `GRAPH.RO_QUERY`, writes go through explicit narrow write tools.

## Consequences
- Tracks entered: 01 (multi-hop traversal, graph-driven branching, tools via MCP, explainable traces), 02 (episodic + procedural memory, shared hypothesis state and handoffs, per-tenant graphs), 03 (owners / on-call / sources for each claim; thin Q&A after 11:30).
- Full council transcript (advisors, critiques, chairman) is in `docs/decisions/council/`.
