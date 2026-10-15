"""Composition root: the only place that picks concrete adapters."""

from oncall_brain.adapters.falkordb.repository import FalkorGraphStore
from oncall_brain.adapters.llm.mock import MockProvider
from oncall_brain.config import Settings, get_settings
from oncall_brain.ports import LLMProvider


def make_store(s: Settings | None = None) -> FalkorGraphStore:
    s = s or get_settings()
    return FalkorGraphStore(s.falkordb_host, s.falkordb_port, s.falkordb_username, s.falkordb_password)


def make_llm(s: Settings | None = None) -> LLMProvider:
    s = s or get_settings()
    if s.llm_provider == "mock" or not s.llm_api_key:
        return MockProvider()
    if s.llm_provider == "anthropic":
        from oncall_brain.adapters.llm.anthropic import AnthropicProvider

        return AnthropicProvider(s.llm_api_key, s.llm_model)
    from oncall_brain.adapters.llm.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(s.llm_api_key, s.llm_model, s.llm_base_url)
