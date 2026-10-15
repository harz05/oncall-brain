"""Runtime settings, read from environment variables or a `.env` file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_username: str | None = None
    falkordb_password: str | None = None
    default_tenant: str = "acme"

    # mock | openai | anthropic. "openai" covers any OpenAI-compatible endpoint (OpenAI, Gemini, Groq, Ollama).
    llm_provider: str = "mock"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
