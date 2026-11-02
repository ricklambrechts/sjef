from unittest.mock import Mock

import pytest
from openai_codex import ApprovalMode, Codex, CodexError, Sandbox, Thread, TurnResult
from openai_codex.types import GetAccountResponse, TurnStatus

SCHEMA = {
    "type": "object",
    "properties": {"naam": {"type": "string"}},
    "required": ["naam"],
}


def turn_result(output='{"naam":"Soep"}', status=TurnStatus.completed):
    return TurnResult(
        id="turn-1",
        status=status,
        error=None,
        started_at=None,
        completed_at=None,
        duration_ms=None,
        final_response=output,
        items=[],
        usage=None,
    )


@pytest.fixture
def sdk(monkeypatch):
    from sjef.llm import codex

    client = Mock(spec=Codex)
    client.account.return_value = GetAccountResponse.model_validate(
        {
            "requiresOpenaiAuth": True,
            "account": {
                "type": "chatgpt",
                "email": "cook@example.com",
                "planType": "plus",
            },
        }
    )
    thread = Mock(spec=Thread)
    thread.run.return_value = turn_result()
    client.thread_start.return_value = thread
    constructor = Mock(return_value=client)
    monkeypatch.setattr(codex, "Codex", constructor)
    return client, thread, constructor


def test_sdk_generates_validated_json_with_chatgpt_auth(tmp_path, monkeypatch, sdk):
    from sjef.llm.codex import CodexLLM

    monkeypatch.setenv("OPENAI_API_KEY", "do-not-use")
    monkeypatch.setenv("PICNIC_PASSWORD", "private")
    client, thread, constructor = sdk
    llm = CodexLLM(home=tmp_path / "auth")
    assert llm.generate_json(
        system="voedingscoach", prompt="avondeten", schema=SCHEMA
    ) == {"naam": "Soep"}
    settings = constructor.call_args.args[0]
    assert settings.env["OPENAI_API_KEY"] == ""
    assert settings.env["PICNIC_PASSWORD"] == ""
    assert settings.env["CODEX_HOME"] == str(tmp_path / "auth")
    assert 'forced_login_method="chatgpt"' in settings.config_overrides
    assert "features.shell_tool=false" in settings.config_overrides
    assert client.thread_start.call_args.kwargs["sandbox"] == Sandbox.read_only
    assert (
        client.thread_start.call_args.kwargs["approval_mode"] == ApprovalMode.deny_all
    )
    assert client.thread_start.call_args.kwargs["base_instructions"] == "voedingscoach"
    assert thread.run.call_args.args[0] == "avondeten"
    assert thread.run.call_args.kwargs["output_schema"]["additionalProperties"] is False
    assert "additionalProperties" not in SCHEMA
    client.close.assert_called_once()


@pytest.mark.parametrize("output", ["not JSON", "[]", '{"naam":7}', "{}", None])
def test_invalid_output_is_not_a_success(tmp_path, sdk, output):
    from sjef.llm.codex import CodexLLM

    sdk[1].run.return_value = turn_result(output)
    with pytest.raises(RuntimeError, match="ongeldig"):
        CodexLLM(home=tmp_path).generate_json(system="", prompt="", schema=SCHEMA)


@pytest.mark.parametrize("account", [None, {"type": "apiKey"}])
def test_refuses_generation_without_chatgpt_account(tmp_path, sdk, account):
    from sjef.llm.codex import CodexLLM

    sdk[0].account.return_value = GetAccountResponse.model_validate(
        {"account": account, "requiresOpenaiAuth": True}
    )
    with pytest.raises(RuntimeError, match="Inloggen met ChatGPT"):
        CodexLLM(home=tmp_path).generate_json(system="", prompt="", schema=SCHEMA)
    sdk[0].thread_start.assert_not_called()


@pytest.mark.parametrize("status", [TurnStatus.failed, TurnStatus.interrupted])
def test_failed_turn_with_valid_partial_json_is_not_a_success(tmp_path, sdk, status):
    from sjef.llm.codex import CodexLLM

    sdk[1].run.return_value = turn_result(status=status)
    with pytest.raises(RuntimeError, match="mislukt"):
        CodexLLM(home=tmp_path).generate_json(system="", prompt="", schema=SCHEMA)


@pytest.mark.parametrize(
    "error, message",
    [
        (FileNotFoundError(), "runtime"),
        (TimeoutError(), "tijd"),
        (CodexError("401 unauthorized SECRET"), "Inloggen met ChatGPT"),
        (CodexError("usage limit reached SECRET"), "gebruikslimiet"),
        (CodexError("unknown SECRET"), "mislukt"),
    ],
)
def test_sdk_failures_have_safe_messages(tmp_path, sdk, error, message):
    from sjef.llm.codex import CodexLLM

    sdk[1].run.side_effect = error
    with pytest.raises(RuntimeError, match=message) as exc:
        CodexLLM(home=tmp_path).generate_json(system="", prompt="", schema=SCHEMA)
    assert "SECRET" not in str(exc.value)
    sdk[0].close.assert_called_once()


def test_api_key_login_uses_temporary_home_and_preserves_chatgpt(tmp_path, sdk):
    from pathlib import Path

    from sjef.llm.codex import CodexLLM

    home = tmp_path / "chatgpt"
    home.mkdir()
    saved = home / "auth.json"
    saved.write_text("existing-login")
    llm = CodexLLM(home=home, api_key="private-test-key")
    assert llm.generate_json(system="", prompt="", schema=SCHEMA) == {"naam": "Soep"}
    client, _, constructor = sdk
    client.login_api_key.assert_called_once_with("private-test-key")
    client.account.assert_not_called()
    settings = constructor.call_args.args[0]
    assert 'forced_login_method="api"' in settings.config_overrides
    assert settings.env["CODEX_HOME"] != str(home)
    assert not Path(settings.env["CODEX_HOME"]).exists()
    assert saved.read_text() == "existing-login"
    assert "private-test-key" not in repr(llm)


def test_invalid_api_key_does_not_fall_back_to_chatgpt(tmp_path, sdk):
    from sjef.llm.codex import CodexLLM

    sdk[0].login_api_key.side_effect = CodexError("401 unauthorized private-test-key")
    with pytest.raises(RuntimeError, match="CODEX_API_KEY") as exc:
        CodexLLM(home=tmp_path, api_key="private-test-key").generate_json(
            system="", prompt="", schema=SCHEMA
        )
    assert "private-test-key" not in str(exc.value)
    sdk[0].account.assert_not_called()
    sdk[0].thread_start.assert_not_called()
