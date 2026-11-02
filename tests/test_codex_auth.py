import threading
from unittest.mock import Mock

import pytest
from openai_codex import ChatgptLoginHandle, Codex, DeviceCodeLoginHandle
from openai_codex.types import AccountLoginCompletedNotification, GetAccountResponse


@pytest.fixture
def sdk(monkeypatch):
    from sjef.llm import codex

    client = Mock(spec=Codex)
    handle = Mock(spec=ChatgptLoginHandle)
    handle.auth_url = "https://auth.openai.com/test"
    handle.wait.return_value = AccountLoginCompletedNotification(
        success=True, loginId="login-1"
    )
    client.login_chatgpt.return_value = handle
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
    monkeypatch.setattr(codex, "Codex", Mock(return_value=client))
    return client, handle


def test_browser_login_and_account(tmp_path, sdk):
    from sjef.llm.codex import CodexLLM
    from sjef.llm.codex_auth import CodexAuth

    auth = CodexAuth(CodexLLM(home=tmp_path))
    login = auth.start_login()
    assert login.url == "https://auth.openai.com/test"
    assert login.wait(timeout=5) is True
    assert auth.account()["email"] == "cook@example.com"
    auth.logout()
    sdk[0].logout.assert_called_once()


def test_device_login_shows_verification_code(tmp_path, sdk):
    from sjef.llm.codex import CodexLLM
    from sjef.llm.codex_auth import CodexAuth

    handle = Mock(spec=DeviceCodeLoginHandle)
    handle.verification_url = "https://auth.openai.com/codex/device"
    handle.user_code = "ABCD-1234"
    handle.wait.return_value = AccountLoginCompletedNotification(success=True)
    sdk[0].login_chatgpt_device_code.return_value = handle
    login = CodexAuth(CodexLLM(home=tmp_path)).start_login(device_auth=True)
    assert login.url == "https://auth.openai.com/codex/device"
    assert login.user_code == "ABCD-1234"
    assert login.wait(timeout=5)
    sdk[0].login_chatgpt.assert_not_called()


def test_failed_login_is_reported_and_client_closed(tmp_path, sdk):
    from sjef.llm.codex import CodexLLM
    from sjef.llm.codex_auth import CodexAuth

    sdk[1].wait.return_value = AccountLoginCompletedNotification(
        success=False, error="private error"
    )
    login = CodexAuth(CodexLLM(home=tmp_path)).start_login()
    with pytest.raises(RuntimeError, match="niet gelukt") as exc:
        login.wait(timeout=5)
    assert "private" not in str(exc.value)
    sdk[0].close.assert_called()


def test_pending_login_can_be_polled_and_cancelled(tmp_path, sdk):
    from sjef.llm.codex import CodexLLM
    from sjef.llm.codex_auth import CodexAuth

    finished = threading.Event()
    sdk[1].wait.side_effect = lambda: (
        finished.wait(5),
        AccountLoginCompletedNotification(success=False),
    )[1]
    sdk[1].cancel.side_effect = finished.set
    login = CodexAuth(CodexLLM(home=tmp_path)).start_login()
    try:
        assert login.wait(timeout=0) is None
        login.close()
        assert finished.is_set()
    finally:
        finished.set()


def test_real_sdk_can_read_logged_out_account_offline(tmp_path):
    from sjef.llm.codex import CodexLLM
    from sjef.llm.codex_auth import CodexAuth

    assert CodexAuth(CodexLLM(home=tmp_path)).account() is None
