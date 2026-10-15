"""Runtime settings, read from environment variables or a `.env` file."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The vendor's own key variable(s), honoured when LLM_API_KEY is empty and that provider is selected.
VENDOR_KEYS = {"openai": ["openai_api_key"], "gemini": ["gemini_api_key", "google_api_key"],
               "groq": ["groq_api_key"], "openrouter": ["openrouter_api_key"], "anthropic": ["anthropic_api_key"]}


def _secret() -> str:
    return Field("", repr=False)  # keys never show up in a printed Settings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_username: str | None = None
    falkordb_password: str | None = Field(None, repr=False)
    default_tenant: str = "acme"

    # mock | openai | gemini | groq | openrouter | ollama | anthropic (presets in wiring.py).
    # Any other OpenAI-compatible endpoint: pick "openai" and set LLM_BASE_URL.
    llm_provider: str = "mock"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = _secret()
    openai_api_key: str = _secret()
    gemini_api_key: str = _secret()
    google_api_key: str = _secret()
    groq_api_key: str = _secret()
    openrouter_api_key: str = _secret()
    anthropic_api_key: str = _secret()

    def api_key(self) -> str:
        """LLM_API_KEY, else the selected vendor's usual variable (so an existing GEMINI_API_KEY just works)."""
        names = VENDOR_KEYS.get(self.llm_provider, [])
        return self.llm_api_key or next((getattr(self, n) for n in names if getattr(self, n)), "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
