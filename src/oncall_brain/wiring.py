"""Composition root: the only place that picks concrete adapters."""

from oncall_brain.adapters.falkordb.repository import FalkorGraphStore
from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.config import Settings, get_settings
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
    return FalkorGraphStore(s.falkordb_host, s.falkordb_port, s.falkordb_username, s.falkordb_password)


def make_llm(s: Settings | None = None) -> LLMProvider:
    """The deterministic planner unless a real provider is selected and has a key (ollama needs none)."""
    s = s or get_settings()
    p, key = s.llm_provider, s.api_key()
    if p == "mock" or not (key or p == "ollama"):
        return MockProvider()
    if p == "anthropic":
        from oncall_brain.adapters.llm.anthropic import DEFAULT_MODEL, AnthropicProvider

        return AnthropicProvider(key, s.llm_model or DEFAULT_MODEL)
    if p not in PRESETS and not s.llm_base_url:
        raise ValueError(f"LLM_PROVIDER={p!r}: use one of mock, anthropic, {', '.join(PRESETS)} or set LLM_BASE_URL")
    from oncall_brain.adapters.llm.openai_compat import OpenAICompatProvider

    base_url, model = PRESETS.get(p, ("", ""))
    if not (s.llm_model or model):
        raise ValueError(f"LLM_PROVIDER={p!r} has no default model; set LLM_MODEL")
    return OpenAICompatProvider(key, s.llm_model or model, s.llm_base_url or base_url)
