# Demo video script (about 3 minutes)

For Harsh to record on the live deployment, https://13-127-186-74.sslip.io/, with real Claude Opus 5.5 runs. The
organisers asked to see the agent running from start to finish and where its decisions come from in the graph. So
the main take is live: start every run on camera and cut the waits in editing, but never fake them. A live run
takes about 45-60 s, and the steps appear while it runs. Act 2 runs twice: first with memory, then the same alert
with memory switched off, which gives the comparison. Expect about twice the wait there.

Screen: a 1440x900 browser window at 100% zoom, plus a terminal for the Claude Code segment. Say plain words on
camera and leave the jargon (p99, episodic, procedural, Cypher) to the README. Times below are for the edited video.

| Time | Screen (what to click) | Say |
|---|---|---|
| 0:00-0:13 | The landing after the reset: "What broke, why, who is paged and the fix, with the proof from your company graph.", the three numbered rows, and "No incidents yet." in the inbox. | "On-call Brain is a teammate for the engineer on call. When an alert fires, it says what broke, why, who is paged and the fix, with proof from your company's graph in FalkorDB." |
| 0:13-0:21 | Click **Simulate an incident: checkout is slow**. The dark panel says "Investigating", with the agent's current sentence in it. Below that: Triage working, Investigator and Comms waiting. | "This is a made-up company with 25 services, and checkout just got slow. Three agents take the alert: triage, investigator and comms." |
| 0:21-0:41 | The run in progress. Keep about 20 s of it and cut the rest. About 10 s in, click **Show me why**. Under "How the agents got here" the steps arrive one by one, each with a question as its title ("Who depends on checkout?", "Which recent changes could be the cause?", "Test suspect …") and "Chosen by Claude Opus 5.5" with its reason. The graph lights the newest step. Step 1, "Open a shared incident record", says "Chosen by the rules", because opening the record is a fixed first step. | "Claude Opus 5.5 picks every step and says why: who depends on checkout, who is on call, which recent changes could be the cause. Then it tests each suspect against the dependency graph. The agents hand off through one incident record in the graph, and every step reads it fresh." |
| 0:41-1:07 | When **Confirm cause** and **Wrong cause** appear, click **Answer**. Point at them in order: Cause (payments-gw, "Config change by Sana Brandt at 08:50, 40 min before the alert."), the "Very likely" tag with "4 of 5 suspects ruled out", the Where wire (Config change pgw-pool-1, payments-gw, payments, checkout, with times), Who. Then scroll to **Ruled out** and **Without the graph** (search-420 and legacy-193, both tagged "wrong change"). | "The cause: a config change on the payments gateway, made by Sana Brandt forty minutes before the alert. Very likely: four of five suspects ruled out, and the slowdown travels gateway, payments, checkout. Two people are paged. The graph ruled out search, because checkout has no path to it, and legacy billing, because checkout stopped calling it three days ago. Without the graph, both change logs blame the wrong change." |
| 1:07-1:22 | Scroll up and click **Show me why**. Show "What this incident touched: … of 25 services" and the red evidence path. In the step list, click the title **Test suspect legacy-193**, then open its "5 queries, …" line: live_paths "read, 0 rows", any_path "read, 1 row", record_evidence "write". | "Show me why is the proof. This step ruled out legacy billing. The query for dependencies live at alert time finds nothing, a second query finds the old, retired one, and the verdict is written back to the graph." |
| 1:22-1:27 | Click **Answer**, then **Confirm cause**. The tag becomes "Confirmed" with "You confirmed this cause.", and Do this shows "Saved to memory". | "I confirm the cause. The graph keeps it, and the fix, as memory." |
| 1:27-1:46 | Click **Simulate an incident** (top right). In row 2, "refunds is slow", click **Simulate**. Cut the wait: first the run, then "Running the same alert again with memory switched off, for comparison." Hold on "Solved from memory", "3 investigator steps instead of 6" and "1 suspect tested instead of 4". | "Three days later, refunds slows down. The brain recalls the checkout incident because the same gateway sits on refunds' dependency path, and it tests that fix first. Three investigator steps instead of six, and one suspect instead of four, compared with the same alert run again with memory off." |
| 1:46-2:04 | When the numbers are in, click **Simulate an incident**. In row 3, "3 alerts at once", click **Simulate**. Cut the wait. The dark panel reads "3 alerts, 1 incident: subscriptions, refunds and checkout fired within 4 minutes and share payments and postgres-orders upstream." Cause: postgres-orders, a config change by Omar Tanaka, "explains all 3 alerting services". Also possible: subs-88. | "Three services alert within four minutes. FalkorDB's WCC algorithm joins them into one incident through the upstream services that went red, and PageRank orders who is hurt. The postgres-orders change explains all three alerts; the subscriptions deploy explains only one, so it is listed as also possible." |
| 2:04-2:19 | Click **Ask the brain**, then the example **Who owns kafka?**. The answer, the sources (one Decision marked "superseded") and the graph on the right. Type "and who is on call for it?" and press Enter. The answer starts "Taking "it" as kafka, from your earlier question". | "The same graph holds docs, tickets and chat. Kafka is owned by Platform, with who is on call and the sources, and the replaced decision is flagged. My follow-up says 'it', and the brain knows I mean kafka." |
| 2:19-2:40 | The terminal, already in Claude Code with the plugin on the live server (see "Before you record"). Type `/oncall-brain:incident alert:checkout-latency`. Claude calls `respond_to_alert` on the `oncall-brain-remote` server. Cut the wait. It reports the cause as confirmed, who is paged, the fix and what was ruled out. | "The web page is one window onto the brain. This is Claude Code with our plugin, on the same live server over MCP. One command, and Claude calls the tools itself. It already knows the cause is confirmed: same graph. Given only our tool list, Claude picked the right tool 17 times out of 17." |
| 2:40-2:48 | Back in the browser, click **Connect**: step 1, "Send alerts in with the webhook", shows the curl command. | "Alerts come in through a webhook like this one, and the same brain answers in Slack with slash oncall." |
| 2:48-2:58 | Click **Incidents**: the inbox with Open and Confirmed. | "One graph per company in FalkorDB. Agents that act on it, shared memory, and a company brain: that covers all three tracks. The code is at <GITHUB_REPO_URL>." |

While recording:
- Do not reload the page between act 1 and Show me why. The Cypher behind each step shows only for a run started
  in this tab. A reloaded incident links to the recorded run instead.
- Claude's step order and reasons change a little from run to run. The cause, the ruled-out list and the "Without
  the graph" row come from graph queries, so they should match this script. Read numbers off the screen, not from
  here. If the cause differs, use the backup take.
- **Skip to answer** only removes the on-screen pacing. The model still needs its time, so leave it alone.
- The status update says "Preview, not posted." Slack is not connected on this deployment, so do not say the update
  is posted to Slack.
- For a full investigation in the terminal instead of a confirmed one, type
  `/oncall-brain:incident alert:checkout-latency cli`. The second word names a fresh company, so Claude seeds it with
  `reset_tenant` and then runs the three agents (about a minute, two runs, about 100k tokens). Then the narration
  becomes "it works the incident with the browser closed".

If it runs long, cut in this order: the Cypher row (1:07-1:22, about 15 s), the Connect shot (say its line over the
terminal), then the "made-up company" sentence. Before recording, check `docs/EVAL.md` (186/200) and
`docs/MCP_PICK.md` (17/17) so the numbers you say match.

## Before you record

1. **Commit first.** `deploy/aws/deploy.sh` ships `git archive HEAD` and refuses to run while tracked files have
   uncommitted changes (`--allow-dirty` ships HEAD anyway).
2. **The limits are raised for the session already** (set on Oct 18 evening as SSM parameters, see docs/DEPLOY.md
   section E). One take is 6 runs from your IP: the reset, act 1, act 2 twice, act 3 and Claude Code. A take also spends
   about 400k model tokens: act 1 about 107k, act 2 about 71k plus the comparison run, act 3 about 105k. Past the hourly
   cap the rules choose the steps, and the badges would say "Chosen by the rules". So `/graphhacks/RUNS_PER_HOUR` is 30
   and `/graphhacks/LLM_HOURLY_TOKEN_CAP` is 1,500,000; the daily cap stays 2,000,000. To change one (then redeploy,
   about 2 minutes, which keeps the graphs):
   ```bash
   aws ssm put-parameter --region ap-south-1 --name /graphhacks/RUNS_PER_HOUR --type String --value 30 --overwrite
   deploy/aws/deploy.sh
   ```
   After judging, put both back to the defaults:
   `aws ssm delete-parameter --region ap-south-1 --name /graphhacks/RUNS_PER_HOUR`, the same for
   `/graphhacks/LLM_HOURLY_TOKEN_CAP`, then `deploy/aws/deploy.sh`.
3. **Check the planner and the budget:** `curl -s https://13-127-186-74.sslip.io/health` should show
   `"planner":"claude-opus-5-5 via Anthropic Messages API"`, with `llm_budget.used_this_hour` well under
   `hourly_cap`. The daily cap is 2,000,000 tokens and resets at 05:30 IST.
4. **Reset the demo company once.** Open https://13-127-186-74.sslip.io/ in a 1440x900 window at 100% zoom. Click
   **Simulate an incident**, then the **Reset demo company** link at the bottom of the menu. It asks "Reset the
   demo company? Every incident, confirmed cause and learned fix on it is deleted…". Click **Reset demo company**,
   not "Keep it". The inbox should say "No incidents yet." and the main button should read **Simulate an incident:
   checkout is slow**. The site is public and anyone with the link shares the demo company, so if the inbox is not
   empty when you start, reset again.
5. **Get the MCP token and start Claude Code.** Open a fresh terminal at the repo root and do not source
   `devenv/env.sh`. Without it, the plugin's local `oncall-brain` server has no Python and stays down, so Claude can
   only reach the live server. Expect Claude Code to show that local entry as failed:
   ```bash
   export ONCALL_BRAIN_URL=https://13-127-186-74.sslip.io
   export ONCALL_BRAIN_TOKEN="$(aws ssm get-parameter --region ap-south-1 --name /graphhacks/MCP_TOKEN \
     --with-decryption --query Parameter.Value --output text)"
   claude --plugin-dir ./plugin mcp list    # plugin:oncall-brain:oncall-brain-remote ... Connected
   clear
   claude --plugin-dir ./plugin
   ```
   The token never prints. Answer any trust or server-approval prompts now, not on camera. If the tool call ever
   times out, start Claude Code with `MCP_TOOL_TIMEOUT=300000` in front.
6. **If a run is slow or fails**, wait a minute and simulate it again. Signs: over 2 minutes, "The agents could not
   finish", a "busy" message, or "Chosen by the rules" on the steps. If it still misbehaves, record the backup take
   below.

## Backup take

The recorded replay at https://13-127-186-74.sslip.io/?offline=1&step_ms=1500 is the same UI playing back real
Claude Opus 5.5 runs, with no database behind it. `step_ms=1500` shows at most one step every 1.5 s, which matches
the narration; at the default pace act 1 is over in about 13 s. Follow the same table, with these differences:

- The buttons say **Replay an incident** and **Replay** instead of Simulate. The footer says "A recorded replay of
  real runs; Claude Opus 5.5 chose the steps." On camera, say "a recorded run", not "live".
- Confirm cause works for act 1 only. Acts 2 and 3 say "Confirming this one needs the live server." Act 2 shows its
  memory numbers right away.
- The act 3 recording is older than the WCC query, so name WCC only in the narration.
- Ask needs the live server ("This page is a recorded replay, so questions need the live server"). Record that
  segment on the live site: Ask uses no model and starts no run.

`make demo` on a local checkout also prints the three incidents, with the same verdicts, in the terminal.
