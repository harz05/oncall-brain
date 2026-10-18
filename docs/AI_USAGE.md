# AI usage disclosure

The rules ask for AI coding assistants to be disclosed. This page says plainly what Harsh did and what AI did.

## What Harsh did

- **Set the goal and the rules:** the hackathon brief and constraints, the engineering rules the code had to follow (Cypher in named files, one tool registry, the graph must change decisions), and the machine limits.
- **Made the product calls:**
  - He pushed it from a demo rig to a product.
  - He made the MCP server and plugin the main surface, with the web UI as one window onto it.
  - He set the UI standard from his earlier project.
  - He asked for the security review and the throttles.
- **Reviewed and approved the architecture** the AI proposed, and the trade-offs logged in `docs/decisions/`.
- **Owned the deployment:**
  - He chose AWS over Render, and supplied the account and the deployment pattern (one ARM box, no SSH, secrets in SSM).
  - He approved the cost before anything was created.
  - He set up the Slack app and the API keys.
- **Tested it himself** end to end, on the web, in Slack and in Claude Code, and recorded the demo video.

## What AI did

- **Claude Code** (Claude Opus 5.5 and Fable 5.1) wrote most of the code, tests and docs, under Harsh's direction. It proposed the architecture, the data model and the agent design. It wrote the deploy scripts, and it ran teams of agents: one builds, separate reviewers check code, security, design and UX, then the builder fixes what they found.
- **A second Claude session** acted as a cloud reviewer, running snapshots on another machine and sending patches. Each patch was applied or rejected with a reason.
- **At runtime,** Claude Opus 5.5 chooses each agent step when a key is set. A deterministic rules planner runs the tests and key-less demos, so the product does not need an LLM.

## How it was checked

- 284 automated tests against a real FalkorDB.
- `make demo`, which fails if the story breaks.
- A 200-incident eval: 186/200 against 0/200 for a plain change log, with every miss listed in `docs/EVAL.md`.
- Independent review rounds and two Claude Security scans: 9 verified findings, all fixed (`docs/SECURITY.md`).
- A live deployment checked end to end.

All data is synthetic: a seeded generator with fake names.
