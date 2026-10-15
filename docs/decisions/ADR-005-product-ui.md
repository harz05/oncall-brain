# ADR-005: Product phase: an inbox-first, answer-first UI; Claude decides by default

Status: accepted, 2026-10-16. Supersedes the demo-rig UI of ADR-003's M4 (act buttons + graph + trace).

## Context

Functionality was complete on Oct 15 (three acts, 167 tests, eval 186/200, Claude driving all acts with 0
fallbacks), but the UI was a debugger: four act buttons, a full dependency graph and an 18-card trace. Harsh's
feedback: "it doesn't feel like a product; what is it, who uses it, how would anyone understand it". The cloud
reviewer's screenshots also showed the CDN blocked on their machine (no graph at all) and a broken 390px layout. The
hackathon rules reward a product a judge understands in the first minute of the video, with FalkorDB visibly doing
the work.

## Decision

1. **Positioning first.** One line at the top: an AI on-call teammate that tells you what broke, why and who to
   page, with the proof from your service graph. Audience: on-call engineers at 20-200 person software companies.
2. **Inbox first, answer first.** The first screen is an incidents inbox (PagerDuty / Linear queue pattern: list on
   the left, the focused incident on the right). The incident view leads with the answer: root cause, a confidence
   label, impact, who is paged, the next action, and Confirm / Wrong cause. The comms agent's update is shown as it
   lands in Slack. Everything that explains the answer sits behind **Show me why**: the incident subgraph (cause path
   plus one hop, whole graph on demand), the ruled-out suspects with their reasons, a three-step agent timeline
   (Triage, Investigator, Comms, each expandable into its tool calls) and the Cypher of every call.
3. **The memory moment is called out**, not buried: "Seen this before: inc:0911, solved in 3 steps instead of 6",
   with the same-incident replay on the pristine graph as the comparison (`?compare=memory`).
4. **Confidence in words, from graph facts** (`domain/verdict.py::confidence`): Confirmed (a human said so), Very
   likely (complete anomaly chain along the live path, explains every alerting service, no co-cause), Likely (a
   monitoring gap, a partial storm, or a co-cause; the reason is stated), No cause found (a human should look). The
   ladder follows how incident.io and Rootly present AI findings: a label plus the evidence, never a bare score.
5. **Demo controls become "Simulate an incident"**: the three scripted alerts live in one menu, named by what the
   on-call engineer would see, not "Act 1".
6. **Ask the company brain is a chat** with the answer first and source chips (doc, ticket, chat, person, change).
7. **Claude decides by default when a key is present** (`LLM_PROVIDER=anthropic`); the UI shows the model on each
   step with the model's own one-line reason; steps the rules decided (fallbacks, the token cap) are badged "rules".
   Each incident run is capped at `LLM_RUN_TOKEN_CAP` tokens (default 300k; a run is ~60-90k); past the cap the
   deterministic planner finishes the incident and the trace says so. Tests, CI and no-key runs use the planner.
8. **No CDN.** The graph libraries are vendored in `web/vendor/` (cytoscape 3.30.4, dagre 0.8.5, cytoscape-dagre
   2.5.0) so the UI works offline and on locked-down machines.
9. **Single column under 900px.** The inbox is a list page, the incident stacks answer -> why; nothing overlaps.
10. **Accessibility is not optional**: WCAG AA contrast for text and control borders, one global `:focus-visible`
    rule, a single polite live region for the stream, `role="img"` on the graph canvas, tabs with `aria-controls`.

## Consequences

- The backend grew three small, graph-backed pieces to serve the product view: `POST .../respond/stream` (NDJSON,
  one line per recorded step), `POST .../alerts` (an alert webhook), `GET .../incidents/{id}` (an incident as the graph
  has it, for an inbox that survives reloads), plus `by` on every `AgentStep` (who decided) and an optional Slack
  post of each update (`SLACK_WEBHOOK_URL`). FalkorDB stays indispensable: every card is a query result.
- The static replay on GitHub Pages reads the same run JSON (`web/fixtures/`), so it keeps working once the fixtures
  are regenerated after each UI change.
- Rejected: a build step (React/Tailwind). The no-build ES-module page stays; it is one HTML, one CSS and two JS
  files any judge can read.
- Rejected: hiding the Cypher entirely. It moves behind "Show me why" but stays one click away; it is the proof that
  the graph did the work (rule 2) and what the judges asked for.
