"""ChatGPT-login via de officiële Python-SDK."""

from __future__ import annotations

import threading
from concurrent.futures import Future
from contextlib import ExitStack
from urllib.parse import urlparse

from openai_codex import CodexError

from sjef.llm.codex import CodexLLM, sdk_error


class CodexLogin:
    """Houd de SDK-login actief terwijl de gebruiker de browserstappen doorloopt."""

    def __init__(self, client, handle, stack: ExitStack, *, device_auth: bool):
        self.client = client
        self.handle = handle
        self.url = handle.verification_url if device_auth else handle.auth_url
        self.user_code = handle.user_code if device_auth else None
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "auth.openai.com",
            "chatgpt.com",
        }:
            raise RuntimeError("Codex gaf een onverwachte inloglink terug.")
        self.result = Future()

        def finish():
            try:
                with stack:
                    if not handle.wait().success:
                        raise RuntimeError(
                            "Inloggen met ChatGPT is niet gelukt. Probeer opnieuw."
                        )
                self.result.set_result(True)
            except Exception as exc:
                self.result.set_exception(exc)

        threading.Thread(target=finish, daemon=True).start()

    def wait(self, timeout: float = 0) -> bool | None:
        try:
            return self.result.result(timeout=timeout)
        except TimeoutError:
            return None

    def close(self):
        if not self.result.done():
            try:
                self.handle.cancel()
            except (CodexError, OSError):
                pass
            finally:
                self.client.close()


class CodexAuth:
    """Login is provider-specifiek en staat los van het generieke LLM-contract."""

    def __init__(self, llm: CodexLLM):
        self.llm = llm

    def account(self) -> dict | None:
        with self.llm.connect() as client:
            account = client.account().account
            if account is None or account.root.type != "chatgpt":
                return None
            return account.model_dump(mode="json")

    def start_login(self, *, device_auth: bool = False) -> CodexLogin:
        stack = ExitStack()
        try:
            client = stack.enter_context(self.llm.connect())
            handle = (
                client.login_chatgpt_device_code()
                if device_auth
                else client.login_chatgpt()
            )
            return CodexLogin(client, handle, stack, device_auth=device_auth)
        except (CodexError, OSError) as exc:
            stack.close()
            raise sdk_error(exc) from None
        except Exception:
            stack.close()
            raise

    def logout(self):
        with self.llm.connect() as client:
            client.logout()
