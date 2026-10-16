---
name: ask
description: Ask the company brain a free-form question with On-call Brain, such as "why was legacy-billing retired from the checkout path", "how do I roll back a bad deploy on cart", "what happened to auth last month", "what is the Q4 cost review changing and who is on it" or, as a follow-up, "and who is on call for it". Use when the answer lives in the company's docs, tickets, chat, changes or incidents, or when the person wants to recall what they asked before.
argument-hint: <question> [--tenant <tenant>] [--as <person id>]
---

Answer the question in `$ARGUMENTS` from the company graph with the On-call Brain MCP tools (server
`oncall-brain`). The tenant is `acme` unless `--tenant <name>` is given.

1. Call `ask` with the tenant and the question. It runs a FalkorDB full-text search over docs, tickets and chat,
   expands around the hits in the graph, and returns an answer with every source cited.
2. If `--as person:<name>` is given, or the person has said who they are, pass that as `user` and
   `session: "claude-code"` on every `ask` in this conversation. The question is then remembered in that person's
   session in the graph: a follow-up can say "it" or "them" (the answer says what it took them to mean), and
   "what did I ask about payments-gw" lists their earlier questions with their sources (`my_questions` does the
   same with a structured result). Without a user nothing is recorded.
3. If the question is about a specific change (why it was made, which ticket, who made it), call `change_story`
   with the change id as well. If it is about who knows a service, `who_knows` adds the ranking. If it is about
   what depends on what, `dependency_path` or `blast_radius` answer it from the live dependency edges.
4. Lead with a one- or two-sentence answer, then the sources (kind and title), newest or current ones first; say
   when a source was superseded by a newer one. Use ids exactly as returned.
