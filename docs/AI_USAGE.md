# AI usage

On-call Brain is my project. I came up with the product, made the calls on architecture and the FalkorDB design, ran
the build, tested every surface myself, deployed it and recorded the demo. I used Claude Code as my coding assistant,
and it wrote most of the code, tests and docs to my specs. The rules ask for that to be disclosed, so here is the
split.

## What I did

- **The product.** An on-call copilot whose decisions come from a FalkorDB graph of the company, used from Claude Code
  over MCP, from Slack, from an alert webhook and from the web. I picked the idea over four others and decided who it
  is for: the engineer on call at 3 am, who needs the cause, the proof and who to page.
- **The engineering rules.** Cypher lives in named, parameterised files. Every tool is defined once and served to the
  agents, over MCP and over HTTP. The graph has to change the decision. Everything works without an LLM key.
- **The architecture and the FalkorDB design.** FalkorDB is the only data store and does the reasoning work:
  traversals, algorithms, constraints and functions that run inside the database. I went through FalkorDB's docs,
  issues and release notes for what to use, and chose what to adopt: user-defined functions, the FLEX library,
  relationship constraints, `algo.maxFlow`, `GRAPH.PROFILE`, and a coordination graph in place of Redis locks. I
  reviewed and approved the graph model, the design and every trade-off in `docs/ARCHITECTURE.md`.
- **The product calls along the way.** MCP and the Claude Code plugin as the main surface, the UI direction and its
  rules, two-way Slack, and the limits a public demo needs.
- **Running it.** I chose the AWS setup (one ARM box, no SSH, secrets in SSM, HTTPS), created and configured the
  FalkorDB Cloud instance, set up the keys and the Slack app, and moved the live site's graphs to Cloud.
- **Checking it.** I tested it end to end on the web, in Slack and in Claude Code, and recorded the demo.

## Where AI was used

- **Claude Code (Anthropic)** was my coding assistant. It wrote the implementation, tests and docs from my direction,
  researched FalkorDB's docs and issues when I asked, and ran code, security and design reviews whose findings it
  fixed.
- **At runtime,** a Claude model chooses each agent step when an API key is set (Claude Opus 5.5 on the live site).
  Without one, a deterministic rules planner does the same job, and it is also what the tests use.

## How it was checked

- 321 automated tests against a real FalkorDB, and the integration suite run against FalkorDB Cloud.
- `make demo`, which fails if the story breaks.
- A 200-incident eval: 186/200, against 0/200 for a plain change log (`docs/EVAL.md`).
- Security scans, with every verified finding fixed (`docs/SECURITY.md`).
- The live deployment, checked end to end on every surface.

All data is synthetic: a seeded generator with fake names.
