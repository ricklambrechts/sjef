"""Claude via de Anthropic API volgens het provider-onafhankelijke LLM-contract."""

from dataclasses import dataclass, field

from anthropic import Anthropic, APIError, AuthenticationError, RateLimitError
from jsonschema import Draft202012Validator, ValidationError


@dataclass
class AnthropicLLM:
    api_key: str = field(repr=False)
    model: str = "claude-sonnet-4-6"
    timeout: float = 600

    def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict:
        if not self.api_key:
            raise RuntimeError(
                "Stel ANTHROPIC_API_KEY in .env in om met Claude te plannen."
            )
        Draft202012Validator.check_schema(schema)
        try:
            with (
                Anthropic(
                    api_key=self.api_key, timeout=self.timeout, max_retries=1
                ) as client,
                client.messages.stream(
                    model=self.model,
                    max_tokens=24000,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    tools=[
                        {
                            "name": "structured_result",
                            "description": "Geef het volledige gevraagde resultaat terug.",
                            "input_schema": schema,
                        }
                    ],
                    tool_choice={"type": "tool", "name": "structured_result"},
                ) as stream,
            ):
                message = stream.get_final_message()
        except AuthenticationError:
            raise RuntimeError(
                "Anthropic weigert de API-key. Controleer ANTHROPIC_API_KEY."
            ) from None
        except RateLimitError:
            raise RuntimeError(
                "De gebruikslimiet bij Anthropic is bereikt. Probeer later opnieuw."
            ) from None
        except APIError:
            raise RuntimeError(
                "De aanvraag bij Anthropic is mislukt. Controleer je verbinding, model en API-tegoed."
            ) from None
        if message.stop_reason != "tool_use":
            raise RuntimeError("Claude gaf een onvolledig resultaat. Probeer opnieuw.")
        for block in message.content:
            if block.type == "tool_use" and block.name == "structured_result":
                try:
                    Draft202012Validator(schema).validate(block.input)
                    if not isinstance(block.input, dict):
                        raise RuntimeError("Claude gaf een ongeldig JSON-object.")
                except ValidationError:
                    raise RuntimeError(
                        "Claude gaf een ongeldig resultaat. Probeer opnieuw."
                    ) from None
                return block.input
        raise RuntimeError("Claude gaf geen gestructureerd resultaat. Probeer opnieuw.")
