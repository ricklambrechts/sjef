"""Codex via ChatGPT-login of API-key met de officiële Python-SDK."""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from jsonschema import Draft202012Validator, ValidationError
from openai_codex import ApprovalMode, Codex, CodexConfig, CodexError, Sandbox
from openai_codex.types import TurnStatus

from sjef.config import ROOT

LOGIN_REQUIRED = (
    "Kies ‘Inloggen met ChatGPT’ in het dashboard of voer ‘sjef ai-login’ uit."
)


def strict_schema(value):
    """Kopieer het schema; Codex vereist gesloten objecten met verplichte velden."""
    if isinstance(value, list):
        return [strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: strict_schema(item) for key, item in value.items()}
    if result.get("type") == "object":
        result["additionalProperties"] = False
        result["required"] = list(result.get("properties", {}))
    return result


def sdk_error(exc: Exception) -> RuntimeError:
    if isinstance(exc, FileNotFoundError):
        return RuntimeError("De Codex-runtime ontbreekt. Voer ‘uv sync’ opnieuw uit.")
    if isinstance(exc, TimeoutError):
        return RuntimeError(
            "Codex antwoordde niet op tijd. Probeer opnieuw of verklein je verzoek."
        )
    detail = str(exc).lower()
    if any(word in detail for word in ("usage limit", "rate limit", "quota", "429")):
        return RuntimeError(
            "Je ChatGPT/Codex-gebruikslimiet is bereikt. Probeer het later opnieuw."
        )
    if any(
        word in detail
        for word in (
            "401",
            "unauthorized",
            "login",
            "not authenticated",
            "refresh token",
        )
    ):
        return RuntimeError(LOGIN_REQUIRED)
    return RuntimeError(
        "Codex-aanroep mislukt. Controleer je login, verbinding en modelinstelling."
    )


@dataclass
class CodexLLM:
    model: str | None = None
    home: Path = field(default_factory=lambda: ROOT / "state" / "codex")
    timeout: float = 600
    api_key: str = field(default="", repr=False)

    @contextmanager
    def connect(self):
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        # De SDK voegt env aan os.environ toe. Overschrijf gevoelige waarden
        # daarom expliciet met lege strings; we veranderen os.environ zelf niet.
        env = {
            key: ""
            for key in os.environ
            if key.startswith(("ANTHROPIC_", "PICNIC_", "TELEGRAM_"))
            or key in {"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"}
        }
        env["CODEX_HOME"] = str(self.home.resolve())
        expired = threading.Event()
        with TemporaryDirectory(prefix="sjef-codex-") as workdir:
            if self.api_key:
                # API-auth mag de opgeslagen ChatGPT-login niet vervangen.
                api_home = Path(workdir) / "auth"
                api_home.mkdir(mode=0o700)
                env["CODEX_HOME"] = str(api_home)
            client = None
            timer = None
            try:
                client = Codex(
                    CodexConfig(
                        cwd=workdir,
                        env=env,
                        client_name="sjef",
                        client_title="Sjef",
                        config_overrides=(
                            'forced_login_method="api"'
                            if self.api_key
                            else 'forced_login_method="chatgpt"',
                            'model_provider="openai"',
                            'cli_auth_credentials_store="file"',
                            "features.shell_tool=false",
                            "features.shell_snapshot=false",
                            'web_search="disabled"',
                            "project_doc_max_bytes=0",
                        ),
                    )
                )

                def expire():
                    expired.set()
                    client.close()

                timer = threading.Timer(self.timeout, expire)
                timer.daemon = True
                timer.start()
                yield client
                if expired.is_set():
                    raise TimeoutError()
            except (CodexError, OSError, TimeoutError) as exc:
                error = sdk_error(TimeoutError() if expired.is_set() else exc)
                if self.api_key and str(error) == LOGIN_REQUIRED:
                    error = RuntimeError(
                        "Codex weigert de API-key. Controleer CODEX_API_KEY in .env."
                    )
                raise error from None
            finally:
                if timer:
                    timer.cancel()
                if client is not None:
                    client.close()

    def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict:
        output_schema = strict_schema(schema)
        Draft202012Validator.check_schema(output_schema)
        with self.connect() as client:
            if self.api_key:
                client.login_api_key(self.api_key)
            else:
                account = client.account().account
                if account is None or account.root.type != "chatgpt":
                    raise RuntimeError(LOGIN_REQUIRED)
            thread = client.thread_start(
                model=self.model,
                model_provider="openai",
                base_instructions=system,
                ephemeral=True,
                sandbox=Sandbox.read_only,
                approval_mode=ApprovalMode.deny_all,
            )
            response = thread.run(prompt, output_schema=output_schema)
            if response.status != TurnStatus.completed:
                raise CodexError(
                    response.error.message if response.error else "Turn mislukt"
                )
            try:
                result = json.loads(response.final_response or "")
                Draft202012Validator(output_schema).validate(result)
                if not isinstance(result, dict):
                    raise ValueError("Geen object")
            except (ValueError, ValidationError):
                raise RuntimeError(
                    "Codex gaf een ontbrekend of ongeldig JSON-resultaat. Probeer opnieuw."
                ) from None
            return result
