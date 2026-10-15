---
name: ask
description: Ask the company brain a free-form question with On-call Brain, such as "why was legacy-billing retired from the checkout path", "how do I roll back a bad deploy on cart" or "what happened to auth last month". Use when the answer lives in the company's docs, tickets, chat, changes or incidents.
argument-hint: <question> [--tenant <tenant>]
---

Answer the question in `$ARGUMENTS` from the company graph with the On-call Brain MCP tools (server
`oncall-brain`). The tenant is `acme` unless `--tenant <name>` is given.

1. Call `ask` with the tenant and the question. It runs a FalkorDB full-text search over docs, tickets and chat,
   expands around the hits in the graph, and returns an answer with every source cited.
2. If the question is about a specific change (why it was made, which ticket, who made it), call `change_story`
   with the change id as well. If it is about who knows a service, `who_knows` adds the ranking. If it is about
   what depends on what, `dependency_path` or `blast_radius` answer it from the live dependency edges.
3. Lead with a one- or two-sentence answer, then the sources (kind and title), newest or current ones first; say
   when a source was superseded by a newer one. Use ids exactly as returned.
