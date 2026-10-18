"""Runtime settings, read from environment variables or a `.env` file."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The vendor's own key variable(s), honoured when LLM_API_KEY is empty and that provider is selected.
VENDOR_KEYS = {"openai": ["openai_api_key"], "gemini": ["gemini_api_key", "google_api_key"],
               "groq": ["groq_api_key"], "openrouter": ["openrouter_api_key"], "anthropic": ["anthropic_api_key"]}
# Host names always accepted by the HTTP servers: loopback, FastAPI's TestClient and the docker-compose service name.
LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver", "app", "0.0.0.0"]


def _secret() -> str:
    return Field("", repr=False)  # keys never show up in a printed Settings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_username: str | None = None
    falkordb_password: str | None = Field(None, repr=False)
    falkordb_ssl: bool = False  # FalkorDB Cloud and most hosted Redis need TLS
    falkordb_url: str = Field("", repr=False)  # e.g. rediss://user:pass@host:port; overrides the fields above
    default_tenant: str = "acme"

    # mock | openai | gemini | groq | openrouter | ollama | anthropic (presets in wiring.py).
    # Any other OpenAI-compatible endpoint: pick "openai" and set LLM_BASE_URL.
    llm_provider: str = "mock"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = _secret()
    # Most input + output tokens one incident run may spend on the model; past it the deterministic planner
    # finishes the run (services/respond.py RunBudget). A full three-role run on Claude is ~60-90k tokens.
    llm_run_token_cap: int = 300_000
    openai_api_key: str = _secret()
    gemini_api_key: str = _secret()
    google_api_key: str = _secret()
    groq_api_key: str = _secret()
    openrouter_api_key: str = _secret()
    anthropic_api_key: str = _secret()

    # HTTP hardening (api/app.py, MCP over HTTP); see .env.example.
    allowed_hosts: str = ""  # extra Host names, comma-separated, on top of LOCAL_HOSTS; "*" accepts any
    # Public hostnames the container host sets by itself (Render, Railway): accepted without listing them.
    render_external_hostname: str = ""
    railway_public_domain: str = ""
    api_token: str = _secret()  # when set, /api/* except /api/health needs "Authorization: Bearer <token>"
    # The token the MCP endpoint of a deployment requires (oncall_brain.serve, the Dockerfile); API_TOKEN when empty.
    mcp_token: str = _secret()
    max_tenants: int = 20  # most tenant graphs a reset may create (~5 MB each)
    # Abuse limits for a public deployment (api/guards.py, services/limits.py); 0 turns one off. Throttles are per
    # client address in fixed windows, counted in FalkorDB's Redis so every process (app, MCP) shares them.
    rate_limit_per_min: int = 0  # requests to /api/* and /mcp per client per minute
    writes_per_min: int = 0  # non-GET /api/* requests and MCP write tools per client per minute (Ask included)
    runs_per_hour: int = 0  # agent runs (?compare=memory counts 2) and tenant resets per client per hour, API and MCP
    max_concurrent_runs: int = 0  # agent runs in progress at once in this process; more are refused (429)
    llm_daily_token_cap: int = 0  # LLM tokens per UTC day across every process; past it the rules planner decides
    llm_hourly_token_cap: int = 0  # the same per UTC hour, so the day's budget cannot all go in one hour
    max_body_bytes: int = 65_536  # largest request body the API (any path) and /mcp accept (413 past it)
    # Longest a write, reset or run waits for its tenant's lock (an agent run holds it 60-150 s on Claude) before it
    # is refused with 409. Every waiter holds a server thread, so a public deployment keeps this short (preset 5).
    lock_wait_seconds: float = 120

    # Optional: post each status update to Slack through an incoming webhook (adapters/slack.py).
    slack_webhook_url: str = _secret()
    # Two-way Slack, the /oncall command and its buttons (api/slack_app.py, docs/SLACK.md): the Slack app's signing
    # secret. Empty: /slack/* answer 404. SLACK_TENANT is the company graph /oncall works on (default DEFAULT_TENANT).
    slack_signing_secret: str = _secret()
    slack_tenant: str = ""

    def hosts(self) -> list[str]:
        names = [h.strip() for h in self.allowed_hosts.split(",")] + [self.render_external_hostname,
                                                                     self.railway_public_domain]
        return LOCAL_HOSTS + [h for h in names if h and h not in LOCAL_HOSTS]

    def mcp_bearer(self) -> str:
        """The bearer token MCP over HTTP checks: MCP_TOKEN, else API_TOKEN (one token for the API and MCP)."""
        return self.mcp_token or self.api_token

    def api_key(self) -> str:
        """LLM_API_KEY, else the selected vendor's usual variable (so an existing GEMINI_API_KEY just works)."""
        names = VENDOR_KEYS.get(self.llm_provider, [])
        return self.llm_api_key or next((getattr(self, n) for n in names if getattr(self, n)), "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
