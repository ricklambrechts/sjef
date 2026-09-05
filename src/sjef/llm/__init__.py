"""Provider-onafhankelijk contract voor de taalmodellen van Sjef."""

from typing import Protocol


class LLM(Protocol):
    """Providers verzorgen transport/authenticatie en leveren een JSON-object.

    Het resultaat moet aan het opgegeven JSON-schema voldoen. Een mislukte
    aanroep of ongeldige uitvoer geeft een exception, nooit een leeg succes.
    Modelkeuze en credentials horen bij de provider, niet bij de planner.
    """

    def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict: ...
