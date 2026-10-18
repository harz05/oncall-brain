# AI usage

I designed, directed and shipped On-call Brain. I built it with AI coding agents (Claude Code), which wrote most of the code, tests and docs to my specifications. I reviewed, tested and deployed it. The rules ask for AI assistance to be disclosed, so here is how the work was split.

## What I did

- **Defined the problem and the product.** On-call Brain is an on-call copilot whose decisions come from a FalkorDB company graph. You can use it from Claude Code over MCP, from Slack, from an alert webhook and from the web.
- **Set the engineering rules the code follows.** Cypher lives in named, parameterised files. Every tool is defined once and served to the agents, over MCP and over HTTP. The graph has to change the decision, and everything works without an LLM key.
- **Directed the build in rounds and made the product calls.** These included making MCP and the plugin the main surface, the UI direction and its design rules, the security limits for a public demo, and two-way Slack.
- **Reviewed and approved the architecture,** the graph model and the trade-offs recorded in `docs/decisions/`.
- **Deployed it.** I chose the AWS architecture (one ARM box, no SSH, secrets in SSM, HTTPS), approved the cost, and set up the keys and the Slack app.
- **Tested it end to end** on the web, in Slack and in Claude Code, and recorded the demo.

## Where AI was used

- **Claude Code (Anthropic)** was the coding agent. It wrote the implementation, tests and docs, and ran separate reviewer agents for code, security and design whose findings it then fixed.
- **At runtime,** Claude Opus 5.5 chooses each agent step when an API key is set. Without one, a deterministic rules planner does the same job, and it is also what the tests use.

## How it was checked

- 284 automated tests against a real FalkorDB.
- `make demo`, which fails if the story breaks.
- A 200-incident eval: 186/200, against 0/200 for a plain change log (`docs/EVAL.md`).
- Two security scans, with all 9 verified findings fixed (`docs/SECURITY.md`).
- A live deployment, checked end to end.

All data is synthetic: a seeded generator with fake names.
