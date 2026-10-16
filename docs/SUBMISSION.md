# Submission draft: On-call Brain

*A draft for Harsh to edit before submitting (written 2026-10-16). Everything here is true of the repository as it
is; the angle-bracket placeholders in the links section are the only blanks.*

## Project name

On-call Brain

## One line

An AI on-call teammate: an alert fires, it tells you what broke, why, who is paged and the fix, with the proof from
your company's graph, and it remembers what you confirmed.

## What it is

When checkout slows down at 3 AM, the newest deploy is rarely the cause. The cause sits somewhere on the dependency
path, and whether a dependency was even live at the time matters. On-call Brain keeps the whole company in one FalkorDB
graph per tenant: services and their dependencies with validity windows, changes, anomalies, people, teams, on-call
rotations, docs, tickets, chat, initiatives, incidents and what fixed them. Three agent roles work an incident over
that graph: triage, an investigator and comms. They hand work to each other through the graph itself, so an agent can
be restarted or replaced mid-incident without losing anything. Every hypothesis is checked against the dependency path
that was live at alert time and the anomalies on it, every refutation says why, and every answer carries the Cypher
that produced it. When a human confirms the cause, the graph remembers the fix, and the next similar incident is solved
in half the steps.

It is an MCP server first: 28 tools generated from one registry, a Claude Code plugin with three skills that works
from a checkout or against a deployed instance, a webhook-in and Slack-out headless flow, and a web inbox that is one
window onto the same brain. A deterministic planner runs everything without an LLM key. With Claude choosing every step
instead, the full three-act story finds the right cause with zero fallbacks.

## Tracks

**Track 01, agents that act on connected data.** Suspects come from multi-hop `DEPENDS_ON` traversals filtered by when
each edge was live, and a refutation is a `shortestPath` that shows the suspect could not reach the symptom. Alert
storms are split by `algo.WCC` over a projection of the alerting services and their red upstreams, so a chain is one
incident and unrelated alerts are separate storms. Blast radius ranks impact with PageRank over the dependency graph as
it was at alert time, and comms warns the top-ranked teams nobody paged.

**Track 02, agent memory and coordination.** Three roles share one `Incident` board in the graph and hand off through
it. Memory is episodic (incidents and what fixed them), semantic (ownership with `valid_from` and `valid_to`, superseded
decisions flagged), procedural (runbooks learned from confirmed fixes) and conversational (per-engineer sessions where
a follow-up can say "it"). One graph per tenant, a per-tenant lock for concurrent responders, and a measured ablation:
with memory, act 2 takes 3 investigator calls instead of 6.

**Track 03, company brain.** Docs, tickets, chat, initiatives, people and services live in the same graph as the
incidents. `ask` answers who owns or knows a service, why a decision was made and what superseded it, what an
initiative is changing and who is on it, with the sources and the Cypher behind each answer. A new decision record or
an ownership transfer flips the answer at once, and "who owned it at the time of the incident" stays correct.

## Would it work without FalkorDB?

No. Suspects, refutations, blast radius, storm splitting, memory recall, ownership at a point in time and every `ask`
answer are Cypher queries or graph algorithms (101 named statements in `.cypher` files, listed in `docs/QUERIES.md`),
and the agents keep no state outside the graph.

## Try it

- From the repository: `make setup && make db && make seed`, then `make demo` (the three-act story, ends with
  `DEMO OK`) or `make dev` for the web inbox at http://localhost:8000.
- From Claude Code: `claude --plugin-dir ./plugin`, then `/oncall-brain:incident alert:checkout-latency` and
  `/oncall-brain:who-owns kafka`.
- With nothing local: `ONCALL_BRAIN_URL=<deployment> ONCALL_BRAIN_TOKEN=<its token> claude --plugin-dir ./plugin`.

## Links

- Repository: <GITHUB_REPO_URL>
- Live deployment: <DEPLOY_URL> (the UI at `/`, MCP at `/mcp`, health at `/health`)
- Demo video: <VIDEO_URL>
- For judges: `docs/WALKTHROUGH.md` (a 45-minute reading order), `docs/SCORECARD.md` (every item of the brief with its
  evidence), `docs/AI_USAGE.md` (how AI tools were used to build it)

## Team

<YOUR NAME> (<GITHUB_HANDLE>)
