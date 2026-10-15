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
- **Tests:** unit tests (verdict rules, planner, query catalogue, generator, eval scenarios, LLM adapters) and integration tests against a real FalkorDB (the three acts, idempotent ingest, read-only guard, step persistence, tenant isolation, concurrent responders, live events, API and MCP hardening).
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

- **Automated tests** (`make test`): unit tests for the pure logic, and integration tests that run the real story against a real FalkorDB. They check that each decoy is refuted for the right reason, that the flat baseline is wrong, that memory makes act 2 shorter, that act 3 is solved only with alert correlation, that read tools cannot write, that tenants are isolated, and that concurrent responders do not duplicate edges.
- **End-to-end demo as a check:** `make demo` runs act 1, the human resolve, act 2, a memory ablation, act 3 and a correlation ablation, and exits non-zero if any claim in the story stops holding.
- **Eval beyond the planted story:** `make eval` runs the agent on 200 randomised incidents with their own decoys and compares it with three baselines that do not use the graph (`docs/EVAL.md`).
- **Independent run:** the cloud reviewer ran snapshots on a different machine and filed findings and patches. Each was applied or rejected with a reason.
- **Measured, not assumed:** the latency numbers in `docs/ARCHITECTURE.md` come from running the demo on the dev machine. The redis-cli commands in `docs/WALKTHROUGH.md` were run against the seeded graph before being written down.
- **Lint:** `ruff` over the code.

## The product at runtime

The product does **not** need an LLM. The default planner is deterministic (`adapters/llm/mock.py` calling `domain/planner.py`): it reads the incident board from the graph and picks the next tool by fixed rules, and the UI labels it as such. An LLM (any OpenAI-compatible endpoint, with presets for OpenAI, Gemini, Groq, OpenRouter and Ollama, or Anthropic) can be plugged in through the `LLMProvider` port. It sees the same board and tools, and falls back to the deterministic planner if its answer is invalid. No LLM key was used to build the demo.

## Data

All data is synthetic, generated by `src/oncall_brain/datagen.py` from a fixed seed. People's names are random combinations of first and last names from fixed lists. No private, scraped or personal data is used.
