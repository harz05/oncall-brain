# AI usage

I designed, directed and shipped On-call Brain. I built it with AI coding agents (Claude Code), which wrote most of the code, tests and docs to my specifications. I reviewed, tested and deployed it. The rules ask for AI assistance to be disclosed, so here is how the work was split.

## What I did

- **Defined the problem and the product.** On-call Brain is an on-call copilot whose decisions come from a FalkorDB company graph. You can use it from Claude Code over MCP, from Slack, from an alert webhook and from the web.
- **Set the engineering rules the code follows.** Cypher lives in named, parameterised files. Every tool is defined once and served to the agents, over MCP and over HTTP. The graph has to change the decision, and everything works without an LLM key.
- **Directed the build in rounds and made the product calls.** These included making MCP and the plugin the main surface, the UI direction and its design rules, the security limits for a public demo, and two-way Slack.
- **Directed the architecture and the FalkorDB design.** FalkorDB is the only data store and does the reasoning work
  (traversals, algorithms, constraints, UDFs), and the whole stack runs on FalkorDB's own infrastructure. I had
  FalkorDB's documentation, issues and release notes mined for what to use, chose which FalkorDB features to adopt
  (user-defined functions, the FLEX library, relationship constraints, `algo.maxFlow`, `GRAPH.PROFILE`), and reviewed
  and approved the architecture, the low-level design Claude Code proposed and implemented, the graph model and the
  trade-offs recorded in `docs/decisions/`.
- **Deployed it.** I chose the AWS architecture (one ARM box, no SSH, secrets in SSM, HTTPS), approved the cost, and set up the keys and the Slack app.
- **Tested it end to end** on the web, in Slack and in Claude Code, and recorded the demo.
- **Moved it onto FalkorDB Cloud (Oct 19).** I decided to run the live site's graphs on FalkorDB Cloud, created and
  configured the Cloud instance, and approved the switch and what shipped with it.

## Where AI was used

- **Claude Code (Anthropic)** was the coding agent. It wrote the implementation, tests and docs, and ran separate reviewer agents for code, security and design whose findings it then fixed.
- **The FalkorDB Cloud move (Oct 19)** was done the same way, at my direction: Claude Code ran research agents over
  FalkorDB's docs, issues and release notes, rebuilt the locks and limits as graph nodes, wrote the UDFs and the
  other FalkorDB features listed in docs/FALKORDB_NOTES.md, and ran two adversarial review passes whose verified
  findings it fixed and tested.
- **At runtime,** Claude Opus 5.5 chooses each agent step when an API key is set. Without one, a deterministic rules planner does the same job, and it is also what the tests use.

## How it was checked

- 316 automated tests against a real FalkorDB, and the integration suite (144 tests) run against FalkorDB Cloud.
- `make demo`, which fails if the story breaks.
- A 200-incident eval: 186/200, against 0/200 for a plain change log (`docs/EVAL.md`).
- Two security scans, with all 9 verified findings fixed (`docs/SECURITY.md`).
- A live deployment, checked end to end.

All data is synthetic: a seeded generator with fake names.
