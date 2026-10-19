# Security and limits

## What protects a public deployment

The settings are listed in `.env.example`. The public preset is in `deploy/aws/docker-compose.aws.yml` and
`render.yaml`. `docs/ARCHITECTURE.md` section 2.5 explains how each one works.

- **Cost.** Each run has its own token cap. A daily and an hourly token budget are shared by every process: they are
  Counter nodes in the `oncall_brain_coord` graph. Past a budget, the rules planner decides, and every step says why.
- **Load.**
  - There are per-client limits on requests, writes and agent runs (`/oncall` counts runs per Slack user), a cap on
    concurrent runs, and a body size cap on every path.
  - A run, reset or write waits at most `LOCK_WAIT_SECONDS` for a busy demo company, then is refused with "retry
    shortly" instead of hanging.
  - Every read has a 3 s server-side timeout (`READ_TIMEOUT_MS`), because FalkorDB Cloud sets none.
- **Input.** Every service argument, on every surface, is resolved against the graph before a tool runs
  (`registry.call`). An unknown name is refused with the closest names the graph holds.
- **Access.**
  - `/mcp` needs `MCP_TOKEN`. Once a token is set, the write tools over `/api` need it too, and so does a named
    conversation user.
  - Slack requests are checked against their signature and timestamp, and replays are refused.
  - The graphs live on FalkorDB Cloud, reachable only with the instance's password. The password sits in AWS
    Parameter Store and in the box's root-only `.env`, never in the repository. The box's own FalkorDB container,
    kept as the fallback, has no public port and needs a password too.
  - Besides graph commands the app sends only `RENAME`, `EXPIRE` and `PING`, never `SET`, `INCR` or `EVAL` (Cloud
    refuses those to every user). Its locks and limits are graph writes under the same password.
- **Output.**
  - Security headers (CSP, nosniff, no-referrer, Permissions-Policy, and HSTS over https) are on every response.
  - Graph text is escaped before it reaches Slack. Webhook status updates are posted as a code block, so links and
    mentions do not render. `/oncall` cards escape every graph string.
  - `scripts/headless.py` shows control characters escaped instead of printing them to the terminal.

## Reviews run on Oct 18

These reviews were AI-assisted (docs/AI_USAGE.md). I checked each finding against the code before fixing it.

| Review | How | Result |
|---|---|---|
| Code review and silent-failure review of the patch stack | Two separate passes, each issue reproduced on a scratch tenant | 22 issues, all fixed |
| Adversarial test of the throttles | Attacks run against live servers | 2 high, 3 medium and 3 low, fixed before merge |
| System-design and architecture review | Each finding checked against the code | 19 real findings, all fixed |
| Two-way Slack | A security review and a Slack platform QA pass | Fixed before merge |
| Security scan | src, plugin, deploy and scripts, high effort, three votes per candidate finding | 8 verified findings (1 medium, 7 low), all fixed |
| Security scan of the Slack commit | Changes mode on that commit (18 files, 1,128 lines), high effort | 1 verified finding (low): agents could pass a `user` to `ask`. Fixed: agents get no asker, and change ids are ASCII |

## Security scan findings and their fixes

| # | Severity | Finding | Fix |
|---|---|---|---|
| F1 | medium | A TLS connection built from FALKORDB_HOST did not check the hostname (the falkordb client defaults it off) | `ssl_check_hostname=ssl` |
| F2 | low | An anonymous caller could plant a question in a named user's conversation memory | Once a token is set, only `web-*` conversation ids are open; a named user needs the token |
| F3 | low | Alert names from the webhook reached Slack as text that could carry phishing links | Slack posts are escaped and sent as a code block |
| F4 | low | A repeat resolve re-posted the update to Slack | A resolve that changes nothing posts nothing |
| F5 | low | `/health` could echo part of a malformed FALKORDB_URL's password | Fixed error categories; details go to the server log |
| F6 | low | `scripts/headless.py` printed graph text with terminal control characters | Control characters are shown escaped |
| F7 | low | `scripts/falkordb_bin.sh` checked hashes in a shared /tmp directory | A private `mktemp -d` work directory |
| F8 | low | The plugin launcher's import probe could import from the current directory | `python -P` |

Tests: F1, F5, F6, F8 and the Slack finding in `tests/unit/test_security_scan_fixes.py`, F2 and F4 in
`tests/integration/test_hardening.py`, F3 in `tests/unit/test_sysdesign_fixes.py`. F7 changes a shell script and has
no test.

## Open on purpose

- On a deployment where only `MCP_TOKEN` is set, anyone with the URL can simulate, confirm and reset on the demo
  company through the UI's API, within the limits above. This is so that judges need no login. Set `API_TOKEN` for
  an MCP-only deployment.
- Clients behind one office NAT share a throttle bucket.
- The concurrent-run cap counts runs in one app process. The deployment runs one.
- The FalkorDB Cloud Free tier has no TLS, so queries and the password travel unencrypted between the AWS box and
  the instance (both in ap-south-1, over the public internet). The data is synthetic and the password is used for
  nothing else. A paid tier with TLS takes `rediss://` in `FALKORDB_URL` and no code change.
- The Free tier keeps no backups and nothing across a restart. The watchdog (`serve.tend`) re-seeds the demo company,
  so a restart loses what visitors taught it (confirmed fixes, runbooks), not the demo.
