"""Composition root: the only place that picks concrete adapters."""

from oncall_brain.adapters.falkordb.repository import FalkorGraphStore
from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.config import LOCAL_HOSTS, Settings, get_settings
from oncall_brain.ports import LLMProvider

# LLM_PROVIDER -> (OpenAI-compatible base URL, default model). LLM_BASE_URL / LLM_MODEL override either.
PRESETS = {
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openrouter": ("https://openrouter.ai/api/v1", "google/gemini-2.5-flash"),
    "ollama": ("http://localhost:11434/v1", "qwen2.5:7b"),
}


def make_store(s: Settings | None = None) -> FalkorGraphStore:
    s = s or get_settings()
    return FalkorGraphStore(s.falkordb_host, s.falkordb_port, s.falkordb_username, s.falkordb_password,
                            s.falkordb_ssl, s.falkordb_url, lock_wait=s.lock_wait_seconds)


def make_llm(s: Settings | None = None) -> LLMProvider:
    """The deterministic planner unless a real provider is selected and has a key (ollama needs none)."""
    s = s or get_settings()
    p, key = s.llm_provider, s.api_key()
    if p == "mock" or not (key or p == "ollama"):
        return MockProvider()
    if p == "anthropic":
        from oncall_brain.adapters.llm.anthropic import DEFAULT_MODEL, AnthropicProvider

        return _capped(AnthropicProvider(key, s.llm_model or DEFAULT_MODEL), s)
    if p not in PRESETS and not s.llm_base_url:
        raise ValueError(f"LLM_PROVIDER={p!r}: use one of mock, anthropic, {', '.join(PRESETS)} or set LLM_BASE_URL")
    from oncall_brain.adapters.llm.openai_compat import OpenAICompatProvider

    base_url, model = PRESETS.get(p, ("", ""))
    if not (s.llm_model or model):
        raise ValueError(f"LLM_PROVIDER={p!r} has no default model; set LLM_MODEL")
    return _capped(OpenAICompatProvider(key, s.llm_model or model, s.llm_base_url or base_url), s)


def _capped(provider: LLMProvider, s: Settings) -> LLMProvider:
    provider.run_token_cap = s.llm_run_token_cap  # services/respond.py budgets each run with it (RunBudget)
    return provider


def exposure_warning(s: Settings | None = None) -> str | None:
    """What the API logs at startup when it answers on a public name (ALLOWED_HOSTS, or the hostname Render or Railway
    set) with a real model behind it but no daily token cap or no per-client run limit: anyone with the URL could
    spend on the key. None when local, on the rules planner, or both limits are set."""
    s = s or get_settings()
    public = s.hosts()[len(LOCAL_HOSTS):]
    missing = [name for name, value in (("LLM_DAILY_TOKEN_CAP", s.llm_daily_token_cap),
                                        ("RUNS_PER_HOUR", s.runs_per_hour)) if not value]
    try:
        paid = not isinstance(make_llm(s), MockProvider)
    except ValueError:  # a misconfigured provider; /api/health reports it
        return None
    if not (public and paid and missing):
        return None
    return (f"public on {', '.join(public)} with the {s.llm_provider} planner and {' and '.join(missing)} = 0: anyone "
            "with the URL can run the agents on your key. Set the public preset from .env.example.")
