---
name: incident
description: Work an alert end to end with On-call Brain. Use when an alert fired, when someone pastes an alert id such as alert:checkout-latency, or asks why a service is slow or failing right now. Runs the triage, investigator and comms agents over the company graph and reports the cause, who is paged, the fix, what was ruled out and the status update.
argument-hint: <alert_id> [tenant]
---

Work the alert given in `$ARGUMENTS` with the On-call Brain MCP tools (server `oncall-brain`, or `oncall-brain-remote` when the plugin points at a deployed instance). The first word is
the alert id (like `alert:checkout-latency`); the second, if present, is the tenant (the company graph), default
`acme`. If no alert id was given, call `service_map` for the tenant, list the alerts it knows about, and ask which
one.

1. Call `respond_to_alert` with that tenant and alert id. If it says the tenant has no graph, call `reset_tenant`
   for it first (that seeds the demo company) and try again.
2. Report in plain words, in this order:
   1. the likely cause: the change, the service it touched, who made it, and the confidence label with its reason;
   2. who is paged, and who got a heads-up;
   3. the fix (runbook) if there is one, with how often it worked;
   4. what was ruled out and why, one line each;
   5. the status update text as written.
   Use ids exactly as the tools returned them. Every tool result carries the Cypher it ran; mention it only if asked.
3. End by asking whether the cause is right. If the answer is yes, call `resolve_incident` with the incident id and
   the change id, so the fix becomes memory for the next incident, and say what was learned.
