# Security review and limits

## What protects a public deployment

The settings are listed in `.env.example`, and the public preset is in `deploy/aws/docker-compose.aws.yml` and
`render.yaml`. `docs/ARCHITECTURE.md` section 2.5 explains how they work.

- **Cost.** Each run has its own token cap, and a daily and an hourly token budget are shared by every process. Past a
  budget, the rules planner decides, and every step says why.
- **Load.** There are per-client limits on requests, on writes and on agent runs (`/oncall` limits runs per Slack
  user), a cap on concurrent runs, and a body size cap on every path. A busy demo company answers at once instead of
  hanging.
- **Access.**
  - `/mcp` needs `MCP_TOKEN`. Once a token is set, the write tools over `/api` need it too, and so does a named
  conversation user.
  - Slack requests are checked against their signature and timestamp, and replays are refused.
  - FalkorDB has no public port and needs a password.
- **Output.** Security headers (CSP, nosniff, no-referrer, Permissions-Policy, and HSTS over https) are on every
  response. Text from the graph is escaped before it reaches Slack, where it is posted as a code block so links and
  mentions do not render. It is also escaped before the headless script prints it to a terminal.

## Reviews run on Oct 18

| Review | What it was | Result |
|---|---|---|
| Code review and silent-failure review of the patch stack | Two independent reviewers, with repros on scratch tenants | 22 issues, fixed in f66b01f |
| Adversarial test of the throttles | An attacker agent working against live servers | 2 high, 3 medium and 3 low, fixed before merge (6da2baa) |
| System-design and architecture review | The engineering plugin's skills, each finding checked against the code | 19 real, fixed in 6da2baa |
| Two-way Slack | A security reviewer and a Slack platform QA reviewer | Fixed before merge (b7b3746) |
| Claude Security scan | The claude-security plugin's pipeline on src, plugin, deploy and scripts at 6da2baa, high effort, with a three-voter panel per candidate | 8 verified findings (1 medium, 7 low), all fixed in the commit after b7b3746 |

## The Claude Security findings and their fixes

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

The scan's report is in `CLAUDE-SECURITY-20261018-104619/` (git-ignored, local). It was verified on revision 6da2baa,
and each fix has a test in `tests/unit/test_security_scan_fixes.py` or `tests/integration/test_hardening.py`.

## What is still open, on purpose

- On a deployment where only `MCP_TOKEN` is set, anyone with the URL can drive the demo company through the UI's API.
  That covers simulate, confirm and reset, within the limits above. This is so that judges need no login. Set
  `API_TOKEN` for an MCP-only deployment.
- Clients behind one office NAT share a throttle bucket.
- The per-process run cap counts runs in one app process. The deployment runs one.
