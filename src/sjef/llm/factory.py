"""De enige plek waar Sjef een concrete LLM-provider kiest."""

from sjef.config import Secrets
from sjef.llm import LLM
from sjef.llm.codex import CodexLLM
from sjef.llm.codex_auth import CodexAuth


def create_llm(secrets: Secrets, *, provider: str | None) -> LLM:
    if provider is None:
        raise ValueError(
            "Kies eerst een AI-provider via ‘Koppel je AI’ in het dashboard."
        )
    if provider == "codex":
        return CodexLLM(
            model=secrets.codex_model or None, api_key=secrets.codex_api_key
        )
    if provider == "anthropic":
        from sjef.llm.anthropic import AnthropicLLM

        return AnthropicLLM(
            api_key=secrets.anthropic_api_key, model=secrets.anthropic_model
        )
    raise ValueError(
        f"Onbekende AI-provider: {provider}. Beschikbaar: codex, anthropic."
    )


def create_auth(secrets: Secrets) -> CodexAuth:
    return CodexAuth(CodexLLM(model=secrets.codex_model or None))
