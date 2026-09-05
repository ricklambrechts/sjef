"""AI-koppelingen voor een persoonlijke Sjef-installatie."""

from collections.abc import Callable

import streamlit as st

from sjef.config import Config
from sjef.llm.codex_auth import CodexAuth


def render_chatgpt_login(
    auth: CodexAuth,
    *,
    config: Config,
    anthropic_key_configured: bool = False,
    codex_key_configured: bool = False,
    save_selection: Callable[[], object] | None = None,
) -> bool:
    selected = config.llm_provider()
    with st.popover("Koppel je AI", use_container_width=True):
        st.markdown(
            "### Anthropic / Claude API"
            + (" · Actief" if selected == "anthropic" else "")
        )
        if anthropic_key_configured:
            st.success("API-key ingesteld")
        else:
            st.info("Geen API-key ingesteld")
        st.caption(
            "Stel ANTHROPIC_API_KEY in via .env. De sleutel wordt hier niet getoond "
            "of op geldigheid getest. Gebruik wordt via de Anthropic API afgerekend."
        )
        use_anthropic = False
        if anthropic_key_configured and selected != "anthropic":
            use_anthropic = st.button("Gebruik Claude", key="ai_use_anthropic")
        st.divider()
        if codex_key_configured:
            st.markdown("### Codex" + (" · Actief" if selected == "codex" else ""))
            st.success("Codex — API-key ingesteld")
            st.caption(
                "CODEX_API_KEY uit .env wordt gebruikt voor nieuwe plannen. "
                "De sleutel is niet vooraf op geldigheid getest. "
                "Je bestaande ChatGPT-login blijft bewaard; verwijder de sleutel om die te gebruiken."
            )
            codex_ready = True
        else:
            codex_ready = _render_chatgpt_options(auth, active=selected == "codex")
        use_codex = False
        if codex_ready and selected != "codex":
            use_codex = st.button("Gebruik Codex", key="ai_use_codex")
        available = [
            p
            for p, ready in {
                "codex": codex_ready,
                "anthropic": anthropic_key_configured,
            }.items()
            if ready
        ]
        automatic = available[0] if selected is None and len(available) == 1 else None
        if use_anthropic or use_codex or automatic:
            config.set_llm_provider(
                automatic or ("anthropic" if use_anthropic else "codex")
            )
            (save_selection or config.save)()
            st.rerun()
    labels = {
        "codex": "Codex / API-key" if codex_key_configured else "Codex / ChatGPT",
        "anthropic": "Claude / Anthropic API",
    }
    st.caption(
        f"AI voor nieuwe plannen: {labels.get(selected, selected or 'Nog niet gekozen')}"
    )
    ready = {"codex": codex_ready, "anthropic": anthropic_key_configured}.get(
        selected, False
    )
    if not ready:
        st.info("Koppel de gekozen AI of kies een beschikbare provider.")
    return ready


def _render_chatgpt_options(auth: CodexAuth, *, active: bool) -> bool:
    st.markdown("### ChatGPT" + (" · Actief" if active else ""))
    try:
        if st.button("Loginstatus vernieuwen", key="ai_refresh"):
            st.session_state.pop("ai_account", None)
        if "ai_account" not in st.session_state:
            st.session_state.ai_account = auth.account()
        account = st.session_state.ai_account
        login = st.session_state.get("ai_login")

        if account:
            st.success(f"Al gekoppeld · {account['email']}")
        else:
            st.caption("Kies hoe je wilt inloggen.")
            for device_auth, key in (
                (False, "ai_start_login"),
                (True, "ai_start_device_login"),
            ):
                if st.button(
                    "Koppelen met apparaatcode"
                    if device_auth
                    else "Koppelen met ChatGPT",
                    key=key,
                    disabled=bool(login),
                ):
                    st.session_state.ai_login = auth.start_login(
                        device_auth=device_auth
                    )
                    st.rerun()

        if account:
            if login:
                login.close()
                st.session_state.pop("ai_login", None)
            if st.button("Uitloggen", key="ai_logout"):
                auth.logout()
                st.session_state.ai_account = None
                st.session_state.pop("proposal", None)
                st.session_state.pop("order_result", None)
                st.rerun()
            return True

        st.caption("Het gebruik valt onder je Codex-tegoed en limieten.")
        if login:
            st.link_button("Open ChatGPT om in te loggen", login.url)
            if login.user_code:
                st.code(login.user_code)
            st.caption("Rond het inloggen af bij OpenAI en klik daarna hieronder.")
            if st.button("Inloggen afronden", key="ai_finish_login"):
                if login.wait(timeout=0):
                    st.session_state.ai_account = auth.account()
                    st.session_state.pop("ai_login", None)
                    st.rerun()
                st.info(
                    "De login is nog niet afgerond. Volg eerst de stappen bij OpenAI."
                )
            if st.button("Annuleren", key="ai_cancel_login"):
                login.close()
                st.session_state.pop("ai_login", None)
                st.rerun()
    except (RuntimeError, ValueError) as exc:
        login = st.session_state.pop("ai_login", None)
        if login:
            login.close()
        st.warning(str(exc))
        if st.button("Opnieuw proberen", key="ai_retry"):
            st.session_state.pop("ai_account", None)
            st.rerun()
    return False
