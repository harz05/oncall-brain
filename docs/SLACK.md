# On-call Brain in Slack

With Slack set up, an engineer works with the brain in the channel where the incident is already being discussed.
`/oncall` sends a question to the company graph or starts the three agents on an alert. The buttons on the answer
confirm or reject the cause, and that decision is written to the graph as memory, the same as from the web UI.

| You type | What happens |
|---|---|
| `/oncall who owns kafka?` (any question) | The brain answers from the graph with its sources. Only you see it. Follow-ups in the same channel remember the conversation, so `/oncall and who is on call for it?` works. |
| `/oncall share why was legacy-billing retired?` | Same answer, posted to the channel. |
| `/oncall incident checkout latency` | Slack answers at once: "Three agents are on it: checkout latency." The triage, investigator and comms agents then run. About a minute later the answer is posted in the channel: the likely cause (service, change, author, how long before the alert), the confidence, who is paged, the fix, up to five sources, and two buttons. The symptom is `latency` (or slow, p99, timeouts), `errors` (or 5xx, failing, down) or `saturation` (or cpu, memory). Other words around the service and symptom are ignored, and if one of the two is missing the reply says which. If that alert already has an incident the agents worked (from Slack, the web UI or the alert webhook), its card is shown at once instead of a second run. |
| **Confirm cause** | The incident is resolved through the same service the API's resolve route uses (`POST .../incidents/{id}/resolve`). The cause becomes `CAUSED_BY`, the fix becomes a runbook in memory, and the message is updated in place: "Confirmed by @you: the fix is saved to memory". Before that, the Fix field already suggests the runbook the cause implies. |
| **Wrong cause** | The message shows the other suspects (the ones the agents ruled out or outranked, plus whatever the change log alone would blame), each with a **This one: <change>** button. Picking one resolves the incident with that change, as the web UI does. Nothing is written until a change is picked. A click on an incident that is already resolved (here or anywhere else) tells only you so, and leaves the message as it is. |
| `/oncall help` | One line per command. |

`/oncall incident <service> <symptom>` takes the first alert still open in the inbox for that service and symptom.
On the demo company, `checkout latency` is act 1, and once that one is confirmed, `refunds latency` is solved from
memory. If no such alert is open, it raises a new alert at the current time through the same tool as the alert
webhook (`raise_alert`, then `run_agents`), so the tenant lock and every budget apply.

## Set it up (about 5 minutes)

Slack has to reach the app over public HTTPS. That means a deployment (`docs/DEPLOY.md`) or, to try it locally, a
tunnel to `localhost:8000`, for example `cloudflared tunnel --url http://localhost:8000`. Add the tunnel's host name
to `ALLOWED_HOSTS`.

1. **Create the app from the manifest.** Go to [api.slack.com/apps](https://api.slack.com/apps), then **Create New
   App**, then **From a manifest**, and pick your workspace. Paste
   [`deploy/slack/manifest.yml`](../deploy/slack/manifest.yml) with `YOUR_DOMAIN` replaced by your public host name
   (no `https://`), then click **Create**.
2. **Install it.** Open **Install App** and click **Install to Workspace**. Pick the channel the status updates should
   go to (for example `#incidents`) and click **Allow**.
3. **Copy the signing secret.** It is under **Basic Information**, then **App Credentials**, then **Signing Secret**.
   Put it in `SLACK_SIGNING_SECRET` (`.env` or your host's environment).
4. **Copy the webhook URL (optional).** It is under **Incoming Webhooks**. Put it in `SLACK_WEBHOOK_URL`. Then every
   status update from a run started in the web UI or by the alert webhook, plus the update after a cause is confirmed
   in the web UI, is posted to that channel. Runs over MCP are not posted. What `/oncall` and its buttons start is
   answered where it was asked, so the channel never gets it twice.
5. **Restart the app.** If `/oncall` should work on a company graph other than `DEFAULT_TENANT`, set `SLACK_TENANT`.
   That graph must be seeded (`POST /api/tenants/<name>/reset`). Your public host must be in `ALLOWED_HOSTS`, or
   Render or Railway must set it for you.
6. **Try it.** In any channel, type `/oncall help`, then `/oncall who owns kafka?` and
   `/oncall incident checkout latency`.

The live site runs with both settings: `/health` shows `"slack": true`, and `/slack/commands` refuses an unsigned
request with 401.

To try it without Slack, sign a request yourself. This is the same check Slack's requests go through:

```bash
ts=$(date +%s)
body='command=/oncall&text=who+owns+kafka%3F&user_id=U1&channel_id=C1&response_url=https://hooks.slack.com/x'
sig="v0=$(printf 'v0:%s:%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$SLACK_SIGNING_SECRET" | sed 's/^.* //')"
curl -s localhost:8000/slack/commands -H "X-Slack-Request-Timestamp: $ts" -H "X-Slack-Signature: $sig" -d "$body"
```

## Security model

- **Signed requests only.** Every request to `/slack/commands` and `/slack/actions` must carry Slack's signature.
  The check is `X-Slack-Signature` equal to `v0=` + HMAC-SHA256(signing secret, `v0:<timestamp>:<raw body>`),
  computed over the raw body bytes and compared in constant time. `X-Slack-Request-Timestamp` must be within 5
  minutes of now, so a captured request cannot be replayed later. A missing header, a bad signature or a stale
  timestamp gets `401 invalid Slack signature` and nothing else. Without `SLACK_SIGNING_SECRET`, both endpoints
  answer 404. The secret and request bodies are never logged.
- **The signature is the credential.** The two endpoints are outside `/api/`, so `API_TOKEN` (which Slack cannot
  send) does not apply to them. The Host allow-list (`ALLOWED_HOSTS`) still applies. Slack sends no `Origin`, so the
  same-origin check on writes lets them through.
- **Each signed request is accepted once.** Slack never sends a command or a click twice, so a repeat of a seen
  signature within the window is a replay and gets the same 401.
- **Answers go to Slack only.** A `response_url` that is not `https://hooks.slack.com/...` (or Slack's GovSlack host)
  is refused and logged, so a forged request cannot make the app POST to an internal address. httpx's request log,
  which would print those URLs, is kept at WARNING.
- **Buttons carry only ids.** A button's value is `{"t": tenant, "i": incident, "c": change}`. Slack signs it when it
  sends the click back, and the handler checks the signature again before it reads anything. The tenant must be
  `SLACK_TENANT`: a button naming another company graph is refused, whoever crafted it. A value this app did not
  make is refused too. The incident and change are resolved by the same service the API uses, which rejects
  unknown ids.
- **Per-user conversation memory.** Each asker is the user `slack:<user id>`, with one session per channel
  (`session:slack:<user>:<channel>` in the graph). A follow-up's "it" reads only your own last question in that
  channel. `my_questions` with that user lists them, and a tenant reset wipes them. The HTTP API (403) and MCP (a
  tool error) refuse a `slack:` user, so nobody can read or steer a Slack user's conversation through them. On the
  API, once a token is set, any user name other than a `web-*` id needs it.
- **Budgets.** `/oncall incident` runs through `run_agents`, so the same limits apply as in the web UI: one agent run
  per tenant at a time (the tenant lock), `MAX_CONCURRENT_RUNS`, `LLM_RUN_TOKEN_CAP` and the daily and hourly token
  budgets. Past a token cap, the deterministic planner decides. `RUNS_PER_HOUR` counts per Slack user, because every
  request comes from Slack's addresses. If another run holds the lock, or another `/oncall incident` is already
  starting one, it says so and starts nothing. An alert the agents already worked shows its card instead of running
  again. **Confirm cause** and **This one** wait for the lock in the background (Slack gets its answer at once) and
  update the message when done. Questions go through `ask`, which answers from the graph and its full-text indexes
  and calls no LLM, so it answers within Slack's 3-second limit.
- **Failures are said, not swallowed.** If the agents fail part way, the channel gets "The agents could not finish:
  ..." and the server log gets the traceback. The channel never sees FalkorDB's address: a database failure reads
  "the graph database is unreachable or failed". If Slack refuses a card, it is sent again as plain text.

Code: `src/oncall_brain/api/slack_app.py` (the endpoints) and `src/oncall_brain/adapters/slack_blocks.py` (the Block
Kit messages, pure functions, every graph string escaped and capped under Slack's limits). Tests:
`tests/unit/test_slack_blocks.py` and `tests/integration/test_slack.py`.
