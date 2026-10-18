# AI usage disclosure

The hackathon rules require AI coding assistants to be disclosed. This page says plainly what an AI did, what Harsh did, and how the output was checked. Lines marked **TODO(Harsh)** are for Harsh to fill in or confirm in his own words. Nobody else should fill them in.

## Tools used

- **Claude Code** (Anthropic's coding agent), model **Claude Opus 5.5**, run in autonomous mode from a written brief by Harsh. It ran on Harsh's laptop and used the skills `llm-council` (idea decision), `engineering:system-design` (design docs) and `ponytail` (a "least code that works" discipline).
- The lead Claude Code session split later work across parallel Claude subagents. Each owned a fixed set of files (for example the HTTP API, the MCP server, the web UI, the LLM adapters, the eval harness, these docs). The lead session integrated their work, ran the tests and made every commit.
- A **second Claude session ("cloud reviewer")** on a separate machine pulled snapshots of the repo, ran the code and tests independently, and sent findings and patches through a shared folder. Applied patches are recorded in the git history (for example commit `5be8d67`, "persist on stop (patch 001)").
- A third, separate Claude session built a competing prototype of the council's runner-up idea (fraud rings) in its own folder, as a comparison point. It shares no code with this repo.
- Every commit so far was made by the lead Claude Code session, not typed by hand. Some carry a `Co-Authored-By: Claude` trailer. Treat the whole history as AI-authored unless a TODO(Harsh) line below says otherwise.

## What the AI did

- **Exploration:** read the hackathon pages, FalkorDB's docs and repos, GraphRAG-SDK and the community-projects page, to avoid cloning an existing showcase (summary in `docs/decisions/ADR-001-idea.md`).
- **Idea decision:** ran an LLM council: five independent advisor personas scored Harsh's five-idea shortlist on Harsh's weighted rubric, critiqued each other anonymously, and a chairman synthesised a verdict. The full transcript is in `docs/decisions/council/`.
- **Design:** the architecture and the ADRs (`docs/ARCHITECTURE.md`, `docs/decisions/ADR-00*.md`), the graph data model and the demo story (three acts) with its decoys.
- **Code:** the Python package (`src/oncall_brain/`), the Cypher queries, the synthetic data generator and the eval scenarios, the scripts, the Makefile, the Dockerfile, docker-compose and `render.yaml`, the API, the MCP server, the LLM adapters and the web UI.
- **Tests:** unit tests (verdict rules, planner, query catalogue, generator and its docs corpus, eval scenarios and perturbations, LLM adapters against canned HTTP replies) and integration tests against a real FalkorDB (the three acts, idempotent ingest, read-only guard, step persistence, tenant isolation, concurrent responders, live events, alert storms, cascade victim and monitoring gap, the company-brain `ask` tool, API and MCP hardening).
- **Docs:** README, architecture, data model, queries, eval, MCP, deploy, walkthrough, demo script, blog draft and this file.
- **Environment work:** finding that `falkordblite` cannot install on this machine's glibc 2.35, and replacing it with FalkorDB's official rhel8 module on a self-built redis (both sha256-pinned in `scripts/falkordb_bin.sh`).

## What Harsh did

- Wrote the build brief that drove the whole run: the goal and tracks, the five-idea shortlist (A to E), the scoring rubric and weights, the default stack, the engineering standards (ports and adapters, Cypher in named files, one tool definition for three surfaces, a deterministic planner that works without keys), the machine constraints (everything on the external drive, no Docker pulls, no sudo) and the review protocol with the second Claude.
- Chose to run the build with the council, system-design and ponytail skills, and to have a second Claude review independently.
- **TODO(Harsh):** what you reviewed, and when (which files, which decisions you agreed with or changed).
- **TODO(Harsh):** what you verified yourself (for example: ran `make setup db seed demo test` on a clean checkout, ran the walkthrough exercises, clicked through the UI).
- **TODO(Harsh):** any change you made or asked for after reviewing (code, wording, scope).
- **TODO(Harsh):** recorded the demo video (link).
- **TODO(Harsh):** created the public GitHub repo, pushed, and set up the deployment (if any).

## How the output was verified

- **Automated tests** (`make test`): unit tests for the pure logic, and integration tests that run the real story against a real FalkorDB. They check that each decoy is refuted for the right reason, that the flat baseline is wrong, that memory makes act 2 shorter, that act 3 is solved only with alert correlation, that an unrelated alert is not folded into a storm, that a storm with two independent causes keeps both (a co-cause, not a ruled-out suspect), that a human's confirmation overrides the agents' pick, that agents are never offered `resolve_incident` or the event tools, that read tools cannot write, that tenants are isolated, and that concurrent responders do not duplicate edges.
- **End-to-end demo as a check:** `make demo` runs act 1, the human resolve, act 2, a memory ablation, act 3 and a correlation ablation, and exits non-zero if any claim in the story stops holding.
- **Eval beyond the planted story:** `make eval` runs the agent on 200 randomised incidents with their own decoys and perturbations (noise, telemetry gaps, cascade victims) and compares it with three baselines that do not use the graph (`docs/EVAL.md`: 186/200 for the agent; every miss listed).
- **Independent run:** the cloud reviewer ran snapshots on a different machine and filed findings and patches. Each was applied or rejected with a reason.
- **Review rounds:** three rounds of review findings were fixed in commits `5ec24e8`, `5792df5` and `b906dcd` (the third: 14 findings on alert storms, co-causes, human override and graph-backed outcomes; its scenarios became `tests/integration/test_storms.py`). One claim was withdrawn as a result: act 3 first ranked the storm's shared upstream with FalkorDB's `algo.betweenness`, but its scores are sampled (they change with `samplingSeed`) and it cannot ignore retired dependencies, so it was replaced with an exact ranking by hop count.
- **Mock judging round:** three simulated judges (AI reviewers, not the hackathon's panel), one per track, scored the project (Track 01: 7-8/10, Track 02: 6-7, Track 03: 4) and listed overclaims. The fixes are in commits `e3a3bdd`, `00d4494` and `c3ad042`:
  - the eval scored 200/200 on scenarios with one decoy per rule and nothing else in the window; it now adds noise anomalies, silent middle hops and cascade-victim deploys, and reports 186/200 (after the victim-aware cascade rule) with a per-perturbation table and every miss (`docs/EVAL.md`). The same people changed the agent's ranking in the same round, knowing the perturbations, and EVAL.md says it is not a blind test;
  - two causal probes a judge ran with the event tools (a deploy on a cascade victim got blamed; a silent middle hop made the cause "inconclusive") became the cascade rule, gaps as weak support and `tests/integration/test_causality.py`;
  - the UI's memory card compared act 2 with act 1, two different incidents; it now compares the same incident with and without memory (`?compare=memory`);
  - Track 03 had little to search; the generator now writes 34 docs, 41 chat messages and 21 tickets, and the `ask` tool answers questions over them with sources;
  - wording: the planner badge, the offline "recorded replay" chip, "stored on the incident" instead of "posted", the per-tenant lock described as serialising runs, and plain statements that one deterministic planner plays all three roles and that no live LLM was run.
- **Measured, not assumed:** the latency numbers in `docs/ARCHITECTURE.md` come from running the demo on the dev machine. The redis-cli commands in `docs/WALKTHROUGH.md` were run against the seeded graph before being written down.
- **Lint:** `ruff` over the code.

## The product at runtime

The product does **not** need an LLM. The default planner is deterministic (`adapters/llm/mock.py` calling `domain/planner.py`): it reads the incident board from the graph and picks the next tool by fixed rules, and the UI labels it as such. An LLM (any OpenAI-compatible endpoint, with presets for OpenAI, Gemini, Groq, OpenRouter and Ollama, or Anthropic) can be plugged in through the `LLMProvider` port. It sees the same board and tools, and falls back to the deterministic planner if its answer is invalid. Since Oct 16 an Anthropic key is in Harsh's `.env` and Claude is the default planner when it is present: Claude Opus 5.5 and Sonnet 5.5 each drove all three demo acts with 0 fallbacks (`docs/LLM_RUN.md`, transcripts in `docs/llm_runs/`), and given only the MCP tool list Claude picked the right tool for 14 of 14 plain requests (`docs/MCP_PICK.md`). Each run is capped in tokens (`LLM_RUN_TOKEN_CAP`); tests and CI use the deterministic planner. The company-brain `ask` tool uses no LLM; its answers are assembled from graph facts and quoted sentences.

## The product phase (Oct 16)

After the functional build, the lead Claude Code session rebuilt the UI as a product and made the MCP server the primary interface, following Harsh's direction ("the MCP server is the product; the web UI is one window onto it"). The method: screenshots of every screen at 1440px and 390px (Playwright), reviews by separate reviewer subagents with fresh eyes (a "first-time on-call engineer" critic, a simulated hackathon judge, a WCAG pass), a design brief synthesised from five subagents' research of incident.io, Rootly, PagerDuty, FireHydrant and Linear (layout and interaction patterns only; no branding, copy or assets), then fixes and a second round. Before/after screenshots and the reviews are in `docs/screenshots/`. The cloud helper (the second Claude session) contributed `docs/SCORECARD.md` and findings V1-V6 (`collab/RIVAL_REVIEW.md` in the workspace); its plugin packaging is applied as patches when it lands.

## The last day (Oct 18)

All of it was done by Claude Code sessions (Fable 5.1, then Opus 5.5) working with agent teams. For each change, one agent built it, independent reviewer agents checked it, and the builder fixed what they found. Harsh directed the work: what to build, the UI playbook, the AWS rules and the go-ahead to provision. He did not write the code. In order:

- **Patches applied:** eleven patches from the cloud helper and the guider (conversation memory, ownership history, the WCC storm split, initiatives, plugin remote mode, the one-process deployment), checked on this machine.
- **Hardening:** a code reviewer and a silent-failure reviewer read those patches and reproduced their findings on scratch tenants. The 22 issues were fixed in f66b01f, with 20 regression tests. Each test fails with the pre-fix file swapped in.
- **Security and AWS:** the security limits and the AWS one-box kit (6da2baa) were built in separate worktrees. An attacker agent tested the throttles on live servers. A system-design and architecture review used the engineering plugin's skills: 36 findings, 19 verified real.
- **Two-way Slack (b7b3746):** built and then reviewed by a security reviewer and a Slack platform QA reviewer.
- **Security scans:** the Claude Security plugin's pipeline scanned the backend, then the Slack commit. Its three-voter panel kept 9 findings (1 medium, 8 low), and all 9 are fixed with tests (240a06f, e2b6cf0). docs/SECURITY.md lists them.
- **Web UI rebuild (ac266cb):** built to a written rulebook (docs/design/RULEBOOK.md). Three direction mocks came first, then a builder and four reviewers (design, QA in a browser, code and accessibility, a first-time-user critic) over two rounds, then a simulated judge.
- **Live deployment:** one AWS t4g.small, provisioned and deployed from the CLI with deploy/aws/*.sh after Harsh approved the cost (about $14 a month on his credits).

## Data

All data is synthetic, generated by `src/oncall_brain/datagen.py` from a fixed seed. People's names are random combinations of first and last names from fixed lists. No private, scraped or personal data is used.
