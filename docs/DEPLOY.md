# Deploying On-call Brain

One container serves everything: the web UI and HTTP API at `/`, the MCP server (Streamable HTTP) at `/mcp`, and
`/health` (`src/oncall_brain/serve.py`, what the `Dockerfile` runs). All state lives in FalkorDB, one graph per
tenant, so the container is stateless. FalkorDB comes from FalkorDB Cloud (`FALKORDB_URL`) or from docker-compose.

**The live site**, https://13-127-186-74.sslip.io/, is section E (one AWS box, built from the CLI) with its graphs on
FalkorDB Cloud (section F). The other sections are alternatives.

| Section | What | Database |
|---|---|---|
| A | Render, free tier: only sign-ins and pasting | FalkorDB Cloud |
| B | Any VM with Docker | the compose file's FalkorDB |
| C | GitHub Pages: a recorded replay, no backend | none |
| D | AWS from the console, one Ubuntu box; also the public limits, cost, update and backup | the box's FalkorDB, or FalkorDB Cloud (F) |
| E | AWS from the CLI: **what the live site runs** | FalkorDB Cloud (F); the box's FalkorDB as the fallback |
| F | FalkorDB Cloud as the live site's database | |

## A. FalkorDB Cloud + Render (free tiers, about 15 minutes)

1. **GitHub.** Push this repository to a GitHub repository you own. Render deploys from it.
2. **FalkorDB Cloud.** Create a free instance (section F, step 1) and build one URL from its connection details:
   `redis://<username>:<password>@<host>:<port>` (the Free tier has no TLS; `rediss://` on a tier with TLS).
   Optional check from your machine: `FALKORDB_URL='redis://...' make demo` must end with `DEMO OK`.
3. **Render.** Sign in at https://dashboard.render.com, New > Blueprint, pick the repository. `render.yaml` creates one
   Docker web service, `oncall-brain`, on the free plan with its health check on `/health`. The blueprint asks for
   `FALKORDB_URL`: paste the URL from step 2. Render generates `MCP_TOKEN`. `ALLOWED_HOSTS` stays empty: the app
   accepts the hostname Render sets (`RENDER_EXTERNAL_HOSTNAME`). Apply, then wait for the first deploy: the image
   builds, seeds the demo company if it is missing (`python -m scripts.seed --if-missing`, so restarts keep learned
   runbooks), and listens on Render's `$PORT`.
4. **Check.** Open `https://<service>.onrender.com/health`: `"ok": true`, `"falkordb": true`, `"mcp": "/mcp"`. Open
   `https://<service>.onrender.com/` and click **Simulate an incident**.
5. **Token.** In the service's Environment tab, copy the value of `MCP_TOKEN`.
6. **Claude Code, from anywhere.** With the plugin (`claude --plugin-dir ./plugin` from a checkout, or
   `/plugin install oncall-brain --marketplace harz05/oncall-brain`), and nothing else installed:
   ```bash
   export ONCALL_BRAIN_URL=https://<service>.onrender.com
   export ONCALL_BRAIN_TOKEN=<the MCP_TOKEN value>
   claude --plugin-dir ./plugin mcp list        # plugin:oncall-brain:oncall-brain-remote ... Connected
   ```
   Then `/oncall-brain:incident alert:checkout-latency` and `/oncall-brain:who-owns kafka` in a session. Any other
   MCP client uses the same URL with `Authorization: Bearer <token>` (see [MCP.md](MCP.md)).
7. **Optional: an LLM planner and Slack.** In the Environment tab add `LLM_PROVIDER=anthropic` and
   `ANTHROPIC_API_KEY=<key>` (or `LLM_API_KEY`); without them the deterministic planner runs. `SLACK_WEBHOOK_URL`
   posts status updates to a channel ([SLACK.md](SLACK.md)).

Free Render instances sleep when idle; the first request after a while takes about 30 s. Record a demo against a warm
instance.

## B. Any VM with Docker

```bash
MCP_TOKEN=<choose one> docker compose up --build -d   # falkordb/falkordb:v4.22.0 + the app on 127.0.0.1:8000: UI, API, /mcp, /health
docker compose --profile mcp up --build -d            # plus the standalone MCP server, no token, on 127.0.0.1:8001/mcp
```

FalkorDB Browser is on 127.0.0.1:3000. Every port is published on 127.0.0.1 only. Put a reverse proxy (Caddy,
nginx) with TLS in front of port 8000, pass the `Host` header through, and add the public name to `ALLOWED_HOSTS`.
Do not publish 6379: FalkorDB in the compose file has no password.

In public, also set the abuse-limit preset from `.env.example` (docs/ARCHITECTURE.md 2.5), including
`LOCK_WAIT_SECONDS=5` and `FORWARDED_ALLOW_IPS` naming the proxy's network (`172.16.0.0/12` for a proxy container on
the compose network; not `*` behind a load balancer that appends to `X-Forwarded-For`). Restore the demo company on a
timer, which undoes whatever visitors wrote into it:
`*/30 * * * * cd <checkout> && docker compose exec -T app python -m scripts.seed --reset`.

## C. A static replay on GitHub Pages (no backend)

`.github/workflows/pages.yml` publishes `web/` on every push to main (enable once: Settings -> Pages -> Source: GitHub
Actions). With no API behind it, the UI replays the recorded runs in `web/fixtures/` and says it is a recorded replay.
Ask, **Plan**, resets and confirming acts 2 and 3 need the live server. The recordings are older than some current
queries; regenerate them with `python -m scripts.gen_fixtures` after changing the agents.

`.github/workflows/ci.yml` runs lint, the query-doc check, the demo and the tests against `falkordb/falkordb:v4.22.0`
on every push.

## D. AWS from the console, one box (EC2 or Lightsail)

One Ubuntu 24.04 instance runs `docker-compose.yml` plus `deploy/aws/docker-compose.aws.yml`: FalkorDB (with a
password, no public port), the app (no public port) and Caddy, which gets a Let's Encrypt certificate and is the only
thing listening on 80 and 443. `deploy/aws/user-data.sh` installs Docker, adds 2 GB of swap, clones the repository to
`/opt/oncall-brain`, writes `/opt/oncall-brain/.env` with a generated `MCP_TOKEN` and FalkorDB password, and starts
everything. Allow about 20 minutes, most of it waiting. The repository must be public on GitHub first; if it is not,
leave `REPO_URL` empty and the script's log prints how to copy the code in over SSH.

### EC2 checklist (t3.small in Mumbai)

1. **Launch.** At https://console.aws.amazon.com pick **Asia Pacific (Mumbai) ap-south-1**, then EC2 -> Instances ->
   **Launch instances**. Name `oncall-brain`. Image: **Ubuntu Server 24.04 LTS**, 64-bit (x86). Type: **t3.small**
   (2 GiB; a t3.micro is too small for FalkorDB plus the app). Storage: **20 GiB gp3** (the default 8 GiB fills up
   with Docker images).
2. **Access.** Create a key pair and keep the `.pem` file for SSH. Without SSH: create an IAM role for EC2 with
   `AmazonSSMManagedInstanceCore` (name it `oncall-brain-ssm`), pick it under Advanced details -> IAM instance
   profile, choose "Proceed without a key pair", and use Systems Manager -> Session Manager for a shell.
3. **Firewall (security group).** Inbound:
   - SSH, TCP 22, from **My IP** only (no SSH rule when you use Session Manager).
   - HTTP, TCP 80, from anywhere: Caddy needs it for the certificate and the redirect to HTTPS.
   - HTTPS, TCP 443, from anywhere.
   - Optional: UDP 443 from anywhere, for HTTP/3. Browsers fall back to TCP without it.
4. **User data.** Advanced details -> User data: paste all of `deploy/aws/user-data.sh` and set `REPO_URL` in its
   first lines (`https://github.com/<you>/<repo>.git`), and `BRANCH` if it is not `main`. Leave `DOMAIN` empty to get
   `<public-ip-with-dashes>.sslip.io`. Keep "Metadata version" at "V2 only" and set **Metadata response hop limit**
   to **1**, so the containers cannot reach instance metadata. Never put a secret in user data (the Anthropic key, a
   GitHub token inside `REPO_URL`): anyone with console access can read it for the life of the instance. The script
   generates the tokens on the box, in `/opt/oncall-brain/.env` (mode 600).
5. **Launch, then pin the address.** EC2 -> Elastic IPs -> Allocate Elastic IP address -> Associate it with the
   instance. Once setup has finished (step 6), run `sudo bash /opt/oncall-brain/deploy/aws/user-data.sh` on the box:
   it moves `DOMAIN` to the new address and keeps the tokens and the key. Without an Elastic IP, the public IP, the
   sslip.io name and the certificate change on every stop and start (a reboot keeps them), and the script has to run
   again each time.
6. **Wait 5 to 8 minutes** (Docker install, image build, seeding the demo company). To watch: `chmod 400 <key>.pem`,
   then `ssh -i <key>.pem ubuntu@<public-ip> sudo tail -f /var/log/oncall-brain-setup.log`. It ends with "On-call
   Brain is up" and the URL.
7. **Check.** `curl -fsS https://<domain>/health` answers `"ok": true`, `"falkordb": true`, `"mcp": "/mcp"`. The
   first HTTPS request can take about 30 s while Caddy gets the certificate.
8. **Set the Anthropic key.** In the Anthropic Console, create a key only for this deployment and set a monthly spend
   limit on its workspace; `LLM_DAILY_TOKEN_CAP` (below) is the app's own cap on top. On the box (the key stays out
   of the shell history):
   ```bash
   read -rsp 'Anthropic API key: ' K; echo; sudo sed -i "s|^LLM_API_KEY=.*|LLM_API_KEY=$K|" /opt/oncall-brain/.env; unset K
   cd /opt/oncall-brain && sudo docker compose up -d
   ```
   `up -d` recreates the app with the new value (`restart` would keep the old one). Without a key the deterministic
   planner runs. `LLM_MODEL` empty means `claude-sonnet-5-5`. The live site uses Opus:
   ```bash
   sudo sed -i 's|^LLM_MODEL=.*|LLM_MODEL=claude-opus-5-5|' /opt/oncall-brain/.env && cd /opt/oncall-brain && sudo docker compose up -d
   ```
9. **Connect Claude Code.** Get the token with `sudo grep ^MCP_TOKEN= /opt/oncall-brain/.env`, then do step 6 of
   section A with `ONCALL_BRAIN_URL=https://<domain>` and `ONCALL_BRAIN_TOKEN=<that value>`.
10. **Before recording a demo**, open the UI, reset the demo company, run act 1 once and check that the steps show
    the model name. Each agent run and each reset counts against `RUNS_PER_HOUR` (12 per client IP; the three acts
    with a reset use 5), so raise it for the session and put it back afterwards:
    ```bash
    cd /opt/oncall-brain && echo RUNS_PER_HOUR=30 | sudo tee -a .env && sudo docker compose up -d     # before
    cd /opt/oncall-brain && sudo sed -i '/^RUNS_PER_HOUR=/d' .env && sudo docker compose up -d       # after
    ```

### Lightsail instead (2 GB plan)

Lightsail -> Create instance -> Mumbai -> Linux/Unix -> OS Only -> **Ubuntu 24.04 LTS**. Under "Add launch script",
paste `deploy/aws/user-data.sh` with the same `REPO_URL` edit. Choose the 2 GB plan and create it. When it runs, open
its Networking tab: add an **HTTPS (TCP 443)** rule to the IPv4 firewall (Lightsail opens only 22 and 80 by default),
restrict SSH to your IP, and optionally add UDP 443. Attach a static IP there too (free while attached), then run
`sudo bash /opt/oncall-brain/deploy/aws/user-data.sh` from the browser SSH button so `DOMAIN` follows it. Steps 6 to
10 above are the same.

### The public limits

Defaults live in `deploy/aws/docker-compose.aws.yml`; set a line in `/opt/oncall-brain/.env` to change one, then
`sudo docker compose up -d`. On the section E box, set a parameter under `/graphhacks/` and redeploy instead.

| Limit | Value | What it does |
|---|---|---|
| `MCP_TOKEN` | generated | `/mcp`, and the write tools over `/api`, need `Authorization: Bearer <token>`. The UI and the rest of `/api` stay open so the demo works for anyone with the link. |
| `RATE_LIMIT_PER_MIN` | 120 | Requests per minute from one client IP to `/api/*` (except `/api/health`) and `/mcp`; pages, scripts and `/health` are not counted. Over it: 429 with Retry-After. |
| `WRITES_PER_MIN` | 20 | Non-GET `/api/*` calls per minute from one client IP (simulate, confirm, reset, new alerts, and Ask, which records the question in the asker's session), and MCP write tools. |
| `RUNS_PER_HOUR` | 12 | Agent runs and tenant resets one client IP may start per hour: respond, respond/stream, `alerts?respond=true`, reset, and the MCP `respond_to_alert` / `reset_tenant` tools. `/oncall incident` counts per Slack user. One run is 60-150 s and about 60-100k tokens; `?compare=memory` (act 2) runs the agents twice and counts as two runs. |
| `MAX_CONCURRENT_RUNS` | 2 | Agent runs in progress at once, all clients together (the box runs one app process). One more is refused at once: 429, or an error line in the run stream. |
| `LLM_DAILY_TOKEN_CAP` | 2,000,000 | Model tokens all runs may spend per UTC day (resets 05:30 IST), about 20 to 30 full runs. Counted in the coordination graph in FalkorDB, so an app restart does not reset it; `curl -s https://<domain>/health` shows `llm_budget.used_today`. Checked before each model call, so runs in flight at the cap go one call over. Past it, runs use the deterministic planner. |
| `LLM_HOURLY_TOKEN_CAP` | 500,000 | This hour's slice of the daily budget, so one busy hour cannot spend the day. Past it the deterministic planner decides until the next hour. |
| `LLM_RUN_TOKEN_CAP` | 150,000 | Model tokens one run may spend. Past it the deterministic planner finishes that run and the trace says so. |
| `MAX_TENANTS` | 8 | Tenants a reset may create, the default one included (each is two graphs of about 4 MB; 8 fit FalkorDB Cloud Free's 100 MB). A judge can open `?tenant=<name>` and reset for a private copy of the demo company. Past it: 429. |
| `LOCK_WAIT_SECONDS` | 5 | How long a run, reset or write waits for the demo company while an agent run holds it. Past it: a 409 that says another run holds the lock and to retry shortly, instead of a 2-minute wait. |
| `MAX_BODY_BYTES` | 65536 | Largest body `/api/*` and `/mcp` accept (413). Caddy refuses bodies over 1 MB first. |

Without these settings the app's own defaults apply: every throttle and token budget off (0), `LOCK_WAIT_SECONDS`
120, `LLM_RUN_TOKEN_CAP` 300,000 and `MAX_TENANTS` 20. The throttles are per client IP, so people behind one office
NAT share them.

The box adds, outside the app: Caddy terminates HTTPS, redirects HTTP, drops clients that take over 10 s to send
their headers, removes the `Server` header and adds HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy` and `Permissions-Policy` where the app sent none. Caddy replaces any `X-Forwarded-For` a client sends
with the real address, so the per-IP limits cannot be dodged by faking it. The box's FalkorDB has a password and
`maxmemory 768mb`. Every container keeps at most 3 x 10 MB of logs.

### Cost, roughly (on-demand, ap-south-1; check the AWS pricing pages)

| Box | Per month |
|---|---|
| EC2 t3.small + 20 GB gp3 + public IPv4 | about $22 (instance ~$16, disk ~$2, IPv4 address $3.65) |
| EC2 t3.medium (4 GiB), if 2 GiB proves tight | about $38 |
| Lightsail 2 GB plan (IP and disk included) | about $12 |

Anthropic usage comes on top, bounded by `LLM_DAILY_TOKEN_CAP` and the Console spend limit (step 8), which is the
hard stop. Worst case per day is `LLM_DAILY_TOKEN_CAP` x the model's input price (most tokens are input); work it out
for the model in `LLM_MODEL` from Anthropic's pricing page. A demo stays far below the 100 GB a month of outbound
traffic AWS does not bill.

### Update, back up, tear down

- **Update.** `cd /opt/oncall-brain && sudo git pull --ff-only && sudo docker compose up -d --build && sudo docker
  image prune -f`, or run `sudo bash /opt/oncall-brain/deploy/aws/user-data.sh` again. Both keep `.env` and the
  graphs. Update when no agent run is in flight; if one was, its lease frees the demo company within 2 minutes.
- **Back up the whole box.** EC2 -> Elastic Block Store -> Volumes -> the instance's volume -> Actions -> Create
  snapshot (Lightsail: the instance's Snapshots tab). The snapshot includes `.env` with the keys, so keep it private.
- **Back up only the graphs.** With `FALKORDB_URL` set (section F) the graphs are on FalkorDB Cloud, and the Free
  tier keeps no backups (after a restart the app re-seeds the demo company). With the box's own FalkorDB:
  `cd /opt/oncall-brain && sudo docker compose exec falkordb redis-cli SAVE && sudo docker compose cp
  falkordb:/var/lib/falkordb/data/dump.rdb ./dump-$(date +%F).rdb`.
- **Tear down.** EC2 -> Instances -> select it -> Instance state -> Terminate (the root volume goes with it unless you
  turned off "Delete on termination"). Then delete any volume left "available", release the Elastic IP (an
  unattached one is still billed), delete the snapshots, revoke the Anthropic key, and delete the `oncall-brain`
  security group, the key pair, your local `.pem` and the `oncall-brain-ssm` role if you made one. On Lightsail:
  delete the instance, the static IP and the snapshots.
- **If something is wrong.** `cd /opt/oncall-brain && sudo docker compose ps` and
  `sudo docker compose logs --tail 100 caddy app falkordb`. No certificate usually means port 80 or 443 is closed in
  the security group or firewall. `sudo docker compose logs caddy | grep -i -E 'rateLimited|too many'` means Let's
  Encrypt refused the shared sslip.io name; Caddy keeps retrying with backoff. To add a second CA, put
  `email you@your-real-domain` as the first line inside the top `{ }` block of `deploy/aws/Caddyfile`, then
  `sudo docker compose restart caddy`. A domain of your own (an A record to the box, `DOMAIN=<it>` in `.env`,
  `sudo docker compose up -d`) avoids the shared limit.

## E. AWS from the CLI (what the live site runs)

The same one-box setup as section D, made from your terminal by four scripts in `deploy/aws/`, on a Graviton (ARM)
box with Amazon Linux 2023. There is no console step, no SSH and no key pair: commands reach the box through AWS
Systems Manager (SSM) Run Command, and the box reads its settings from SSM Parameter Store. Everything the scripts
create is named `oncall-brain-*` and tagged `Project=graphhacks`.

What `provision.sh` creates, in ap-south-1 (Mumbai):

- **The box.** One t4g.small (2 vCPU, 2 GiB) in the default VPC, Amazon Linux 2023 arm64 (the AMI comes from the
  public SSM parameter), a 20 GB encrypted gp3 disk, and IMDSv2 only with hop limit 1, so the containers cannot read
  instance metadata. Its user data, `deploy/aws/bootstrap-al2023.sh`, installs Docker, the Compose and Buildx plugins
  (pinned versions, checksums checked) and 2 GB of swap. Nothing secret goes into user data.
- **Its role**, `oncall-brain-host`, with an instance profile of the same name. It has `AmazonSSMManagedInstanceCore`
  (so Run Command and Session Manager work), read access to `s3://<bucket>/oncall-brain/*` and to the parameters
  under `/graphhacks/`, and `kms:Decrypt` on the AWS-managed SSM key only when SSM asks. The managed policy alone
  would let the box read and decrypt every parameter in the account, so an explicit Deny limits its parameter reads
  to `/graphhacks/`.
- **A security group**, `oncall-brain-web`. It opens 80 and 443 (TCP, and UDP 443 for HTTP/3) to the internet and
  nothing else. FalkorDB's 6379 and the app's 8000 are never published.
- **An Elastic IP**, `oncall-brain-ip`. The site's name is that address with dashes plus `.sslip.io`, so the name and
  its certificate survive a stop and start.
- **A private bucket**, `oncall-brain-<account-id>-ap-south-1`, for the code: public access blocked, SSE-S3
  encryption, tarballs deleted after 14 days.

### Before you start

- The AWS CLI v2, signed in: `aws sts get-caller-identity --query Arn --output text` prints your user. The scripts use
  ap-south-1; to move, change `REGION` at the top of each script.
- git, curl, openssl and python3 (provision.sh uses it to read the price list). Docker is not needed on your machine:
  the box builds the image itself.
- For Claude as the planner: `LLM_API_KEY` (an Anthropic key) in this repository's `.env`. deploy.sh copies it to
  Parameter Store once and never prints it. Without a key the box runs the deterministic planner.
- Commit what you want to ship. deploy.sh sends `git archive HEAD`, not your working tree, and refuses to run while
  tracked files have uncommitted changes or files the image needs are untracked (`--allow-dirty` ships HEAD anyway).

### The four commands

Run them from the repository root, in this order.

| Step | Command | What it does | Time |
|---|---|---|---|
| 1 | `deploy/aws/provision.sh --dry-run` | Prints the plan (what exists, what would be created), the monthly estimate from the live AWS price list, and EC2's answers to dry-run requests. Makes only read-only calls; creates nothing. | about 1 min |
| 2 | `deploy/aws/provision.sh` | Prints the same plan, asks `Create these? [y/N]` (`--yes` skips the question), creates what is missing, launches the box and attaches the Elastic IP. Ends with the instance id, the Elastic IP and the domain. Safe to run again: it creates only what is missing, and starts the box if it is stopped. | about 2 min, then 2 to 3 min of first boot in the background |
| 3 | `deploy/aws/deploy.sh` | Uploads HEAD as `s3://<bucket>/oncall-brain/<sha>.tar.gz`. Writes the settings that are missing under `/graphhacks/`: `MCP_TOKEN` and `FALKORDB_PASSWORD` are generated once and kept on every later deploy; `LLM_API_KEY` (and `SLACK_WEBHOOK_URL`, `SLACK_SIGNING_SECRET` if set) come from `.env`. Then it runs `deploy/aws/host.sh` on the box through Run Command, prints the box's output, checks `https://<domain>/health` from your machine and prints the URL and how to get the token. Run it again for every new commit. | 5 to 10 min the first time, 2 to 4 min after |
| 4 | `deploy/aws/teardown.sh` | Deletes everything above, then runs the checks from the AWS guide and says what, if anything, still bills. See "Tear down" below. | 2 to 4 min |

On the box, `host.sh` waits for the first boot to finish, unpacks the tarball into a new directory and swaps it in
for `/opt/oncall-brain`. It writes `/opt/oncall-brain/.env` (mode 600) from every parameter under `/graphhacks/` plus
`DOMAIN=<elastic-ip-with-dashes>.sslip.io`, `LLM_PROVIDER=anthropic` and `LLM_MODEL=claude-opus-5-5` (a
`/graphhacks/LLM_PROVIDER` or `/graphhacks/LLM_MODEL` parameter wins). It builds the app image while the old one
still serves, runs `docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml up -d`, prunes the old
image and waits for `/health`. If an agent run is in flight (a live `Lease` in the coordination graph), host.sh waits
up to 150 s for it before restarting the app. It never deletes the lease: a run cut short frees the demo company by
itself within 2 minutes, when its lease runs out.

A redeploy keeps the graphs (on FalkorDB Cloud, or in the fallback container's Docker volume) and Caddy's certificate
(a Docker volume). The page asks for its scripts and styles with a version in the URL, and `/web/` answers with
`Cache-Control: no-cache`, so a browser never mixes old and new files after a redeploy.

### Get the MCP token and connect Claude Code

The token stays in Parameter Store; nothing prints it unless you ask:

```bash
export ONCALL_BRAIN_URL=https://<elastic-ip-with-dashes>.sslip.io
export ONCALL_BRAIN_TOKEN="$(aws ssm get-parameter --region ap-south-1 --name /graphhacks/MCP_TOKEN \
  --with-decryption --query Parameter.Value --output text)"
claude --plugin-dir ./plugin mcp list      # plugin:oncall-brain:oncall-brain-remote ... Connected
```

Then use the plugin as in step 6 of section A.

### Change a setting, e.g. RUNS_PER_HOUR for a recording session

Every deploy rewrites the box's `.env` from Parameter Store, so a lasting change is a parameter plus a redeploy. The
redeploy takes about 2 minutes, because the image is cached, and keeps the graphs:

```bash
aws ssm put-parameter --region ap-south-1 --name /graphhacks/RUNS_PER_HOUR --type String --value 30 \
  --tags Key=Project,Value=graphhacks      # to change it later: --overwrite instead of --tags
deploy/aws/deploy.sh
# afterwards
aws ssm delete-parameter --region ap-south-1 --name /graphhacks/RUNS_PER_HOUR && deploy/aws/deploy.sh
```

The same works for `LLM_MODEL` and every limit in section D's table. To change the Anthropic key, delete
`/graphhacks/LLM_API_KEY`, put the new key in `.env` and run `deploy/aws/deploy.sh`, which copies it without putting
it on a command line.

For a quick change without a redeploy, open a shell on the box (`aws ssm start-session --region ap-south-1 --target
<instance-id>`; deploy.sh prints the id), then
`cd /opt/oncall-brain && echo RUNS_PER_HOUR=30 | sudo tee -a .env && sudo docker compose up -d`. The next deploy
overwrites it.

### Cost

About $13.65 a month at on-demand prices from the AWS price list: t4g.small $0.0112/h ($8.18), the public IPv4
address $0.005/h ($3.65) and 20 GB of gp3 at $0.0912 per GB-month ($1.82). `provision.sh --dry-run` looks the prices
up again and prints the sum. S3 and standard parameters cost cents. Anthropic usage comes on top, bounded by
`LLM_DAILY_TOKEN_CAP` and the Console spend limit (section D, step 8). A t4g box uses unlimited CPU credits by
default: an idle demo stays below its baseline, while hours of full CPU would add a small charge.

To pause it, run `aws ec2 stop-instances --region ap-south-1 --instance-ids <instance-id>`. A stopped box costs
about $5.50 a month: the disk, plus the Elastic IP, which bills while idle too. `deploy/aws/provision.sh` starts it
again with the same address, name and data.

### Tear down

`deploy/aws/teardown.sh` lists what it found and asks before deleting (`--yes` skips the questions). It terminates the
box, which deletes its disk and the fallback FalkorDB's graphs on it (section D, "Back up only the graphs"). Then it
releases the Elastic IP and deletes the security group, the instance profile and role, and the bucket with its
tarballs. It asks a second time before deleting the parameters under `/graphhacks/` (they are free; a new deploy
makes new tokens). Last, it runs the AWS guide's region-wide checks (instances, volumes, snapshots, Elastic IPs, NAT
gateways, RDS, load balancers) and says whether anything still bills. The script does not touch FalkorDB Cloud:
delete that instance in its console. Revoke the Anthropic key in the Console too if you made it for this deployment.

### If something fails

- deploy.sh prints the box's output. The full logs are on the box: `/var/log/oncall-brain-deploy.log` and, for the
  first boot, `/var/log/oncall-brain-bootstrap.log`. Read them in a Session Manager shell (above).
- When the health check fails, host.sh prints `docker compose ps` and the last 50 lines of the app's log.
- "Not Online in Systems Manager": the box is still booting, or it has no route out. Give it a minute and run
  deploy.sh again.
- No certificate: in a Session Manager shell, `cd /opt/oncall-brain && sudo docker compose logs caddy | grep -i -E
  'rateLimited|too many'`. A match means Let's Encrypt refused the shared sslip.io name. To add ZeroSSL as a second
  CA, put `email you@your-domain` as the first line inside the top `{ }` block of `deploy/aws/Caddyfile` in the
  repository, commit, and run deploy.sh: host.sh recreates Caddy whenever the Caddyfile changes. (Editing the file on
  the box, as in section D, is undone by the next deploy.)

## F. The live site's database on FalkorDB Cloud

The live site's graphs are on a FalkorDB Cloud instance (Free tier, AWS ap-south-1, the box's region). The app needs
only `FALKORDB_URL`; the box's own FalkorDB container stays as the fallback. `/health` names the database:
`"database": "FalkorDB Cloud (ap-south-1)"`.

1. **Create the instance.** At https://app.falkordb.cloud: Create, Free, AWS, ap-south-1, user `falkordb` and a
   password. When it shows Running, the Connectivity tab (or Nodes) gives the host and port.
2. **Check it from your machine first**, on a throwaway company, before the live site touches it. URL-encode the
   password: `FALKORDB_URL='redis://falkordb:<password>@<host>:<port>' LLM_PROVIDER=mock make demo` must print
   `DEMO OK`, and `FALKORDB_URL=... pytest tests/integration` runs the whole suite there.
3. **Store the URL and deploy.** The URL holds the password, so it reaches the CLI through a pipe, as `deploy.sh`
   does with the other secrets:
   ```bash
   aws ssm put-parameter --region ap-south-1 --name /graphhacks/FALKORDB_URL --type SecureString \
     --tags Key=Project,Value=graphhacks --value file://<(printf %s "$URL")
   deploy/aws/deploy.sh
   ```
   `MAX_TENANTS` is already 8 on the box (`deploy/aws/docker-compose.aws.yml`), so the Free tier's 100 MB holds every
   company. On its first start against Cloud, the container seeds the demo company if it is missing, loads the
   `oncall` and `flex` UDF libraries on the first query, and builds the coordination graph on first use.
4. **Check.** `/health` says `"falkordb": true` and names FalkorDB Cloud; run an incident from the UI.
5. **Roll back** to the box's own FalkorDB: `aws ssm delete-parameter --region ap-south-1 --name
   /graphhacks/FALKORDB_URL && deploy/aws/deploy.sh`.

What the Free tier means for the code (each item is handled in it; see FALKORDB_NOTES.md):

- Its users get the graph commands but never `SET`, `INCR` or `EVAL`. So locks, throttles and the LLM budget are
  `Lease` and `Counter` nodes in the `oncall_brain_coord` graph, with a UNIQUE constraint as the mutex
  (`adapters/falkordb/coordination.py`).
- No TLS: `redis://`, not `rediss://` (docs/SECURITY.md says what that exposes).
- No persistence or backups, and an instance unused for a day is stopped (deleted after 7). The health check (every
  5 s) and the watchdog `serve.tend` (every minute) run real graph queries. After a restart, `serve.tend` restores
  the coordination constraints and the demo company; the first query that misses a UDF library reloads it.
- No query timeout of its own: the app sets one on every read (`READ_TIMEOUT_MS`, 3 s).
- 100 MB of RAM for every graph: `MAX_TENANTS=8`. Scratch graphs for the algorithms expire after 5 minutes, even if
  a process dies before dropping them.

## Settings that matter in public

| Setting | Why |
|---|---|
| `MCP_TOKEN` | Required by `/mcp` on a deployment: without it that endpoint answers 401 (the UI and API still work). Once set, the write tools over `/api` and a named conversation user need it too. The plugin sends it as `ONCALL_BRAIN_TOKEN`. |
| `API_TOKEN` | If set, every `/api/*` call except `/api/health` needs `Authorization: Bearer <token>`, and it doubles as the MCP token when `MCP_TOKEN` is empty. The bundled UI does not send it, so set this only for API/MCP-only deployments. Without it, anyone who can reach the URL can simulate, confirm and reset on the demo company through the UI's API. |
| `ALLOWED_HOSTS` | Host-header allow-list (blocks DNS rebinding) on the API and the MCP endpoint. The hostname Render (`RENDER_EXTERNAL_HOSTNAME`) or Railway (`RAILWAY_PUBLIC_DOMAIN`) sets is accepted by itself; list any other public name here. |
| `MAX_TENANTS` | Each new tenant costs two graphs; resetting a new tenant past the cap returns 429. |
| Abuse limits | `RATE_LIMIT_PER_MIN`, `WRITES_PER_MIN`, `RUNS_PER_HOUR`, `MAX_CONCURRENT_RUNS`, `LLM_DAILY_TOKEN_CAP`, `LLM_HOURLY_TOKEN_CAP`, `LOCK_WAIT_SECONDS`, `MAX_BODY_BYTES`: the public preset is in `.env.example`, `render.yaml` sets it, and docs/ARCHITECTURE.md 2.5 says what each bounds. |
| `FORWARDED_ALLOW_IPS` | The proxy addresses uvicorn takes `X-Forwarded-For` from, so each visitor has its own throttle bucket. Name the proxy's network; `*` is safe only behind one proxy that overwrites the header. |
| `FALKORDB_URL` / `FALKORDB_SSL` | Connection to a hosted FalkorDB: `redis://user:password@host:port` (FalkorDB Cloud Free has no TLS), `rediss://` where TLS is on. |
| `READ_TIMEOUT_MS` | Server-side cap on every read (`GRAPH.RO_QUERY ... TIMEOUT`), 3000 by default, because FalkorDB Cloud sets none. 0 turns it off. |

`/health` answers on any `Host` (a platform's checker may not send the public name) and reveals only flags. There is
no per-user auth: anyone with the token can address any tenant over MCP, and anyone who can reach the API can address
any tenant there. That is fine for a demo; a real deployment would put an identity-aware proxy in front and map users
to tenants.

## MCP for remote clients

A deployment serves MCP at `https://<host>/mcp` with the bearer token above, from the same process as the UI and API.
[MCP.md](MCP.md) lists the clients (the Claude Code plugin's remote entry, `claude mcp add --transport http`, the
Inspector, any MCP SDK). The standalone server, `python -m oncall_brain.mcp_server --http --host 0.0.0.0 --port 8001`,
also runs as a second process next to `make dev`; it checks `Host` and `Origin` the same way and needs no token unless
one is set. `tests/integration/test_deploy.py` starts the deployment app as the Dockerfile does and checks all of this
from outside: `/health`, the open API, the UI, the Host checks on both halves, 33 tools and an `ask` over `/mcp`, 401
on a wrong token.
