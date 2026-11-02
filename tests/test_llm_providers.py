from sjef.config import Config, Secrets
from sjef.llm.factory import create_auth, create_llm


def test_selection_persists_and_routes_key_and_models(monkeypatch, tmp_path):
    monkeypatch.setattr("sjef.config.load_dotenv", lambda *args: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("CODEX_MODEL", "gpt-test")
    monkeypatch.setenv("CODEX_API_KEY", " codex-private-test-key ")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    secrets = Secrets.load()
    config = Config()
    config.set_llm_provider("anthropic")
    path = config.save(tmp_path / "config.yaml")
    restored = Config.load(path)
    llm = create_llm(secrets, provider=restored.llm_provider())
    assert type(llm).__name__ == "AnthropicLLM"
    assert llm.api_key == "private-test-key"
    assert llm.model == "claude-test"
    assert "private-test-key" not in repr(llm)
    assert "private-test-key" not in path.read_text()
    codex = create_llm(secrets, provider="codex")
    assert codex.model == "gpt-test"
    assert codex.api_key == "codex-private-test-key"
    assert "codex-private-test-key" not in repr(secrets)
    assert not create_auth(secrets).llm.api_key
    assert not hasattr(secrets, "llm_provider")
    assert type(create_auth(secrets)).__name__ == "CodexAuth"


def test_anthropic_validates_structured_response(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import Mock

    import pytest

    from sjef.llm import anthropic as provider

    message = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="tool_use", name="structured_result", input={"answer": "ok"}
            )
        ],
    )
    stream = Mock()
    stream.get_final_message.return_value = message
    client = Mock()
    client.messages.stream.return_value = nullcontext(stream)
    constructor = Mock(return_value=nullcontext(client))
    monkeypatch.setattr(provider, "Anthropic", constructor)
    llm = provider.AnthropicLLM(api_key="private-test-key")
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    assert llm.generate_json(system="sys", prompt="ask", schema=schema) == {
        "answer": "ok"
    }
    assert constructor.call_args.kwargs["api_key"] == "private-test-key"
    assert client.messages.stream.call_args.kwargs["tools"][0]["input_schema"] == schema
    message.content[0].input = {"answer": 1}
    with pytest.raises(RuntimeError, match="ongeldig"):
        llm.generate_json(system="sys", prompt="ask", schema=schema)
    message.stop_reason = "max_tokens"
    with pytest.raises(RuntimeError, match="onvolledig"):
        llm.generate_json(system="sys", prompt="ask", schema=schema)
