# Een andere LLM toevoegen

Implementeer `sjef.llm.LLM`: één methode
`generate_json(*, system: str, prompt: str, schema: dict) -> dict`. De provider
verzorgt modelkeuze, authenticatie, transport en validatie tegen het JSON-schema.
Bij een fout moet hij een exception geven. Registreer de provider in
`llm/factory.py` en voeg hem toe aan de providerkeuze in het dashboard; de planner hoeft niet te veranderen.
Het is een Python `Protocol`: overerving is niet verplicht. Een eventuele
interactieve login is provider-specifiek en staat los van dit contract.
