# AI koppelen

## Codex met een API-key

Vul `CODEX_API_KEY` in `.env` in en herstart het dashboard. Bij **Koppel je AI**
verschijnt **Codex — API-key ingesteld**; accountlogin is dan niet nodig.
Sjef controleert alleen of een sleutel aanwezig is. De planner gebruikt
`codex.login_api_key(...)`; een ongeldige sleutel geeft tijdens het plannen een fout.
De sleutel krijgt voorrang op je ChatGPT-login, die apart bewaard blijft.
Maak `CODEX_API_KEY` leeg en herstart om weer je ChatGPT-login te gebruiken.
De authenticatiemethode wordt vastgezet via de officiële
[`forced_login_method`-instelling](https://developers.openai.com/codex/config-reference/).

## Inloggen met ChatGPT

Start `uv run sjef dashboard` en klik in de zijbalk op **Koppel je AI**.
Kies **Koppelen met ChatGPT** of **Koppelen met apparaatcode**. Open de getoonde
link, log bij OpenAI in met je eigen account en klik op **Inloggen afronden**.
Als je al ingelogd bent, zie je één ChatGPT-status. De twee inlogopties
verschijnen alleen wanneer je niet ingelogd bent.
Je kunt de loginstatus vernieuwen of uitloggen.

Bij **Anthropic / Claude API** zie je of `ANTHROPIC_API_KEY` aanwezig is in
`.env`. De sleutel wordt niet getoond, gewijzigd of op geldigheid getest.
Klik op **Gebruik Claude** of **Gebruik Codex** om te wisselen tussen beschikbare
providers. Met één beschikbare provider kiest Sjef die automatisch; met meerdere
providers kies je bij het eerste gebruik zelf. Een eerder gekozen provider wordt
niet stilzwijgend vervangen als de koppeling wegvalt. Claude gebruikt je Anthropic API-key voor zowel menu's als productkeuzes;
dit gebruik wordt via je Anthropic API-account afgerekend.
De keuze wordt in `config.yaml` opgeslagen en geldt ook voor CLI en Telegram.
Een lopend plan houdt zijn oorspronkelijke provider. Een nieuwe keuze geldt voor
het volgende plan. Sjef schakelt bij fouten niet automatisch naar een andere provider.
Je ChatGPT-account moet toegang tot Codex hebben; het gebruik valt onder je
beschikbare Codex-tegoed en gebruikslimieten. Sjef gebruikt geen API-keyfallback.

Inloggen vanuit de terminal kan ook:

```bash
uv run sjef ai-login
# Als de browsercallback niet werkt, bijvoorbeeld op een eigen server:
uv run sjef ai-login --device-auth
```

De officiële [`openai-codex` Python-SDK](https://github.com/openai/codex/tree/main/sdk/python)
installeert de bijpassende Codex-runtime automatisch via `uv sync`. Een aparte
npm-installatie is niet nodig. Codex beheert OAuth en tokenvernieuwing; Sjef vraagt
nooit om je ChatGPT-wachtwoord. De login staat in de git-ignored map
`state/codex/`, apart van je eventuele Codex-installatie voor programmeerwerk.
Behandel deze map als geheim. Dashboard, CLI en Telegram gebruiken dezelfde login.

Dit is een **persoonlijke installatie per gebruiker of huishouden**. Een gedeelde
website voor onafhankelijke gebruikers wordt nog niet ondersteund: ook Picnic,
profielen en configuratie zijn per installatie opgeslagen. Browserlogin werkt
op de computer waarop Sjef draait; kies apparaatcode als je elders inlogt.

**Na bijwerken:** voer `uv sync` uit en herstart het dashboard. Stel modellen in
met `CODEX_MODEL` en `ANTHROPIC_MODEL`; `PLANNER_MODEL` wordt niet meer gebruikt.
Je bestaande `ANTHROPIC_API_KEY` blijft bruikbaar.
