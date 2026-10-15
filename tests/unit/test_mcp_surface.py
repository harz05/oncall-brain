"""The MCP surface an outside agent sees: every tool and argument described, prompts that render, a token on the
remote transport. No FalkorDB needed (the server connects lazily)."""

from starlette.testclient import TestClient

from oncall_brain.config import get_settings
from oncall_brain.mcp_server import PROMPTS, catalogue, prompt_text
from oncall_brain.mcp_server.__main__ import http_app


def _schema(tool) -> dict:
    return getattr(tool, "input_schema", None) or tool.inputSchema


def test_every_mcp_tool_and_every_argument_is_described():
    tools = catalogue()
    assert len(tools) >= 24
    for name, (tool, _) in tools.items():
        assert tool.description and len(tool.description) > 40, f"{name} needs a real description"
        schema = _schema(tool)
        assert schema["required"][0] == "tenant"
        for arg, spec in schema["properties"].items():
            assert spec.get("description"), f"{name}.{arg} has no description (an outside model has only the schema)"


def test_prompts_render_the_workflow_with_their_arguments():
    assert set(PROMPTS) == {"work_alert", "company_question"}
    text = prompt_text("work_alert", {"tenant": "acme", "alert_id": "alert:checkout-latency"})
    assert "respond_to_alert" in text and "alert:checkout-latency" in text and "resolve_incident" in text
    text = prompt_text("company_question", {"tenant": "acme", "question": "who owns kafka?"})
    assert text.startswith("Answer this question about company 'acme'") and "who owns kafka?" in text


def test_remote_mcp_requires_the_token_when_one_is_set(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "s3cret")
    get_settings.cache_clear()
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    try:
        with TestClient(http_app("127.0.0.1")) as c:  # the context runs the lifespan the session manager needs
            assert c.post("/mcp", json=body, headers=headers).status_code == 401
            assert c.post("/mcp", json=body, headers={**headers, "authorization": "Bearer s3cret"}).status_code != 401
    finally:
        get_settings.cache_clear()
