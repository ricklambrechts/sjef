from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest


class Auth:
    account_data = None
    used_device_auth = None

    def account(self):
        return self.account_data

    def start_login(self, *, device_auth=False):
        self.used_device_auth = device_auth

        def wait(timeout=0):
            self.account_data = {"email": "cook@example.com"}
            return True

        return SimpleNamespace(
            url="https://auth.openai.com/test",
            user_code="ABCD-1234" if device_auth else None,
            wait=wait,
            close=lambda: None,
        )

    def logout(self):
        self.account_data = None


def dashboard(auth, *, anthropic_key_configured=False, codex_key_configured=False):
    app = AppTest.from_string("""
import streamlit as st
from sjef.interfaces.ai_login import render_chatgpt_login
from sjef.config import Config
if "config" not in st.session_state:
    st.session_state.config = Config()
ready = render_chatgpt_login(st.session_state.auth,
    anthropic_key_configured=st.session_state.anthropic_key_configured,
    codex_key_configured=st.session_state.codex_key_configured,
    config=st.session_state.config, save_selection=lambda: None)
st.button("Plan maken", disabled=not ready)
""")
    app.session_state.codex_key_configured = codex_key_configured
    app.session_state.auth = auth
    app.session_state.anthropic_key_configured = anthropic_key_configured
    return app.run()


@pytest.mark.parametrize("device_auth", [False, True])
def test_dashboard_login_and_logout_flow(device_auth):
    auth = Auth()
    app = dashboard(auth)
    assert not app.exception
    assert len(app.get("popover")) == 1
    assert app.button[-1].disabled
    key = "ai_start_device_login" if device_auth else "ai_start_login"
    app.button(key=key).click().run()
    assert not app.exception
    assert auth.used_device_auth is device_auth
    assert app.get("link_button")[0].url == "https://auth.openai.com/test"
    if device_auth:
        assert app.code[0].value == "ABCD-1234"
    app.button(key="ai_finish_login").click().run()
    assert not app.exception
    assert not app.button[-1].disabled
    assert any("cook@example.com" in item.value for item in app.success)
    app.button(key="ai_logout").click().run()
    assert not app.exception
    assert app.button[-1].disabled
    auth.account_data = {"email": "cook@example.com"}
    app.button(key="ai_refresh").click().run()
    assert not app.exception
    assert not app.button[-1].disabled


def test_existing_login_is_shown_once():
    auth = Auth()
    auth.account_data = {"email": "cook@example.com"}
    app = dashboard(auth)
    assert not app.exception
    assert not any(
        b.key in {"ai_start_login", "ai_start_device_login"} for b in app.button
    )
    assert sum("Al gekoppeld" in item.value for item in app.success) == 1
    assert auth.used_device_auth is None
    assert not app.button[-1].disabled


@pytest.mark.parametrize("configured", [False, True])
def test_single_available_provider_is_selected(configured):
    app = dashboard(Auth(), anthropic_key_configured=configured)
    assert not app.exception
    statuses = [item.value for item in [*app.success, *app.info]]
    expected = "API-key ingesteld" if configured else "Geen API-key ingesteld"
    assert expected in statuses
    assert not app.text_input
    assert app.button[-1].disabled is not configured


def test_switch_between_both_available_providers():
    auth = Auth()
    auth.account_data = {"email": "cook@example.com"}
    app = dashboard(auth, anthropic_key_configured=True)
    app.button(key="ai_use_anthropic").click().run()
    assert not app.exception
    assert app.session_state.config.llm_provider() == "anthropic"
    assert not app.button[-1].disabled
    app.button(key="ai_logout").click().run()
    assert not app.button[-1].disabled
    auth.account_data = {"email": "cook@example.com"}
    app.button(key="ai_refresh").click().run()
    app.button(key="ai_use_codex").click().run()
    assert app.session_state.config.llm_provider() == "codex"
    assert not app.button[-1].disabled


def test_anthropic_can_plan_without_chatgpt():
    app = dashboard(Auth(), anthropic_key_configured=True)
    assert app.session_state.config.llm_provider() == "anthropic"
    assert not app.exception
    assert not app.button[-1].disabled


def test_anthropic_remains_available_when_codex_status_fails():
    class BrokenAuth(Auth):
        def account(self):
            raise RuntimeError("Codex niet beschikbaar")

    app = dashboard(BrokenAuth(), anthropic_key_configured=True)
    assert app.session_state.config.llm_provider() == "anthropic"
    assert not app.exception
    assert not app.button[-1].disabled


def test_multiple_providers_require_initial_choice():
    auth = Auth()
    auth.account_data = {"email": "cook@example.com"}
    app = dashboard(auth, anthropic_key_configured=True)
    assert app.button[-1].disabled
    app.button(key="ai_use_codex").click().run()
    assert not app.button[-1].disabled
    assert app.session_state.config.llm_provider() == "codex"


def test_unavailable_selection_is_not_silently_replaced():
    auth = Auth()
    auth.account_data = {"email": "cook@example.com"}
    app = dashboard(auth, anthropic_key_configured=True)
    app.button(key="ai_use_codex").click().run()
    app.button(key="ai_logout").click().run()
    assert app.session_state.config.llm_provider() == "codex"
    assert app.button[-1].disabled


def test_codex_key_is_ready_without_checking_account():
    class NoAccountCheck(Auth):
        def account(self):
            raise AssertionError("API-key must not require account lookup")

    app = dashboard(NoAccountCheck(), codex_key_configured=True)
    assert not app.exception
    assert not app.button[-1].disabled
    assert any("Codex — API-key ingesteld" in item.value for item in app.success)
    assert not any(
        b.key in {"ai_start_login", "ai_start_device_login"} for b in app.button
    )
