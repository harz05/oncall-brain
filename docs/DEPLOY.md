# Deploying On-call Brain

Two pieces: a FalkorDB database and the app container (API + web UI, optionally the MCP server). The app is one stateless container; all state lives in FalkorDB, one graph per tenant.

## Option A: FalkorDB Cloud + Render (free tiers, about 15 minutes)

1. **Database.** Create a free database at https://app.falkordb.cloud. Copy its host, port, username and password. Build one URL from them:
   `rediss://<username>:<password>@<host>:<port>` (use `redis://` if the instance has no TLS).
   Check it from your machine before going further:
   ```bash
   FALKORDB_URL='rediss://...' python -m scripts.seed --tenant acme    # seeds the demo company + pristine copy
   FALKORDB_URL='rediss://...' python -m scripts.demo --tenant demo    # must end with DEMO OK
   ```
   If `make demo` fails on a Cloud instance running a different FalkorDB major version, note the failing query and compare with v4.22.0, which is what local dev and docker-compose pin.
2. **App.** Push the repo to GitHub. In Render: New > Blueprint, pick the repo. `render.yaml` creates a Docker web service with a health check on `/api/health`. In the dashboard, set:
   - `FALKORDB_URL`: the URL from step 1.
   - `ALLOWED_HOSTS`: the public hostname Render gives you, e.g. `oncall-brain.onrender.com`. Requests with any other `Host` header get 400.
   - Optional: `LLM_PROVIDER` + `LLM_API_KEY` (see `.env.example`) for an LLM planner; leave `mock` for the deterministic one.
3. **Check.** Open `https://<your-app>/`, click 0 Reset, then 1 Act 1. `GET /api/health` should say `"falkordb": true`.

The container seeds the default tenant on first start (`python -m scripts.seed --if-missing`) and keeps it across restarts, so learned runbooks survive. It listens on `$PORT` (set by Render, Railway and Fly) or 8000.

Free Render instances sleep when idle; the first request after a while takes about 30 s. Record the demo video against a warm instance.

## Option B: any VM with Docker

```bash
docker compose up --build -d                 # falkordb/falkordb:v4.22.0 + app on 127.0.0.1:8000
docker compose --profile mcp up --build -d   # plus the MCP server on 127.0.0.1:8001/mcp
```
Ports are published on 127.0.0.1 only. Put a reverse proxy (Caddy, nginx) with TLS in front of port 8000, pass the `Host` header through, and add the public name to `ALLOWED_HOSTS`. Do not publish 6379: FalkorDB in the compose file has no password.

## Settings that matter in public

| Setting | Why |
|---|---|
| `ALLOWED_HOSTS` | Host-header allow-list (blocks DNS rebinding). Must include your public hostname. |
| `API_TOKEN` | If set, every `/api/*` call except `/api/health` needs `Authorization: Bearer <token>`. The bundled UI does not send it, so set this only for API/MCP-only deployments. |
| `MAX_TENANTS` | Each new tenant costs two graphs; resetting a new tenant past the cap returns 429. |
| `FALKORDB_URL` / `FALKORDB_SSL` | Connection to a hosted FalkorDB (TLS). |

There is no per-user auth: anyone who can reach the API can address any tenant. That is fine for a demo; a real deployment would put an identity-aware proxy in front and map users to tenants.

## MCP for remote clients

Run `python -m oncall_brain.mcp_server --http --host 0.0.0.0 --port 8001` next to the app (same env vars). It checks `Host` and `Origin` on every request against `ALLOWED_HOSTS`, so add the public name there too. Clients connect to `https://<host>/mcp`; see docs/MCP.md.
