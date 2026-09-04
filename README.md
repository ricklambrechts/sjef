# 🧑‍🍳 Sjef — jouw AI-keukenmaatje

> _(intern projectmap: `supermarkt-agent`)_

Sjef stelt **elke week een weekmenu** samen op jouw macro-doelen (calorieën +
eiwit) en dieetvoorkeuren, matcht de boodschappen bij **Picnic**, berekent de
echte macro's per persoon uit de productlabels, en zet — **na jouw goedkeuring** —
het mandje klaar.

Het maaltijdplan komt van de **Claude API**; de boodschappen lopen via de
(onofficiële) Picnic-API.

**Twee interfaces, kies wat je wilt:**
- 🖥️ **Web-dashboard** (Streamlit) — de complete voorkant: plannen, menu + macro's
  bekijken, boodschappen bewerken, instellingen beheren, goedkeuren. **Standalone
  bruikbaar.**
- 💬 **Telegram-bot** (optioneel) — voor een wekelijks seintje en snelle goedkeuring
  onderweg. Niet nodig om Sjef te gebruiken.

---

## ⚠️ Belangrijk om te weten

- **Onofficiële Picnic-API.** Er is geen publieke Picnic-API. Deze agent gebruikt
  `python-picnic-api2`, dat de endpoints van de mobiele app aanspreekt. Dat kan
  zonder waarschuwing breken en valt buiten Picnic's voorwaarden. Prima voor
  persoonlijk gebruik, niet voor commercieel.
- **Er gaat echt geld doorheen.** Daarom:
  - `DRY_RUN=true` staat standaard aan → er wordt **nooit** echt besteld, alleen
    gesimuleerd. Zet pas op `false` als je het vertrouwt.
  - Alleen jouw eigen Telegram-user-id mag de bot bedienen.
  - Bestellen gebeurt in **twee stappen** (slot kiezen → expliciet bevestigen).
  - Een harde uitgavenlimiet (`max_order_eur`) blokkeert te dure bestellingen.
- **Betaling** loopt via je bestaande Picnic-incasso/iDEAL-mandaat; er is geen
  losse betaalstap in de API.

---

## Setup

Installeer eerst [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/groeimetai/sjef.git
cd sjef
uv sync

cp .env.example .env             # geheimen (zie tabel hieronder)
cp config.example.yaml config.yaml   # voorkeuren & limieten
cp profiles.example.yaml profiles.yaml   # of stel profielen in via het dashboard
```

`.env`, `config.yaml` en `profiles.yaml` zijn **git-ignored** — jouw gegevens
worden dus nooit per ongeluk gedeeld.

### `.env` invullen
| Variabele | Verplicht? | Hoe kom je eraan |
|---|---|---|
| `PICNIC_USERNAME` / `PICNIC_PASSWORD` | ✅ | je Picnic-inlog |
| `ANTHROPIC_API_KEY` | ✅ | console.anthropic.com → API keys |
| `TELEGRAM_BOT_TOKEN` | ⬜ optioneel | alleen voor de bot: [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_ALLOWED_USER_ID` | ⬜ optioneel | alleen voor de bot: je id via [@userinfobot](https://t.me/userinfobot) |
| `DRY_RUN` | — | laat op `true` tot je het vertrouwt |

Wil je **alleen het dashboard**? Dan heb je de twee Telegram-velden niet nodig.

### Eenmalig inloggen bij Picnic (2FA)
```bash
uv run sjef picnic-login
```
Dit handelt de SMS-code af en slaat een auth-token op in `state/`, zodat je
daarna zonder 2FA werkt.

### Persoonlijke voorkeuren
Stel personen, macro-doelen, huishouden en budget in **via het dashboard**
(tab ⚙️ Instellingen) — of bewerk `config.yaml` / `profiles.yaml` met de hand.

---

## Gebruik

```bash
uv run sjef dashboard        # web-dashboard (http://localhost:8501)
uv run sjef plan bulk        # voorstel in de terminal (bestelt niets)
uv run sjef bot              # Telegram-bot (optioneel)
uv run sjef selftest         # offline logica-tests (geen credentials nodig)
```

Bekijk alle commando’s met `uv run sjef --help` en de opties per commando met
bijvoorbeeld `uv run sjef picnic-login --help`.

### Web-dashboard
De overzichtelijke voorkant om alles te zien, te bewerken en goed te keuren:
- menu per dag in een tabel, boodschappenlijst met **aanpasbare aantallen** en
  verwijderbare regels (totaal werkt live mee);
- veld voor **losse extra's** per bestelling (bv. wc-papier, afwasmiddel) die
  gegarandeerd worden toegevoegd;
- bezorgslot kiezen en **goedkeuren & bestellen** (respecteert DRY_RUN).

Telegram blijft voor de wekelijkse notificatie + snelle approve onderweg; het
dashboard is voor het rustige overzicht en bewerken. Beide delen dezelfde backend.

In Telegram:
- `/plan` — weekmenu op de standaard-modus
- `/plan cut` / `/plan bulk` — kies de macro-modus voor deze week
- `/plan 4x avondeten voor 4 personen, 2 lunches voor 2, 3 gezonde snacks` —
  **vrije opdracht**: beschrijf in gewone taal wat je wilt, met wisselende
  porties per maaltijd. De macro-doelen blijven als richtlijn gelden.
- de bot toont het menu + boodschappen + totaalprijs → kies een bezorgslot →
  bevestig → (in live-modus) besteld
- `/status` — lopende bezorgingen

### Profielen (meerdere personen, eigen doelen)
De agent ondersteunt een huishouden met meerdere personen die elk een eigen doel
hebben (bv. de één cut, de ander bulk). Uit lengte/gewicht/leeftijd/activiteit
berekent hij automatisch per persoon de dagelijkse calorie- en macrodoelen
(Mifflin-St Jeor → TDEE → doel-aanpassing). Je hoeft dus niet zelf met kcal te
rekenen.

- `/setup` — de bot stelt je vraag voor vraag de gegevens en slaat ze op in
  `profiles.yaml`. Ideaal als je de agent deelt: een nieuwe gebruiker vult zo
  zijn eigen data in zonder een bestand te bewerken.
- `/profiles` — toont de huidige profielen + berekende dagdoelen.
- `profiles.yaml` is **git-ignored** (privé). Alleen `profiles.example.yaml` (een
  generiek sjabloon) zit in de repo — zo deel je de agent zonder je eigen data.

De planner houdt per persoon rekening met de doelen, kookt waar mogelijk dezelfde
gerechten met aangepaste porties, en past universele voedingsprincipes toe
(eiwit eerst, volume eten, lage glycemische load bij insulineresistentie,
koolhydraat-timing rond training). Die kennislaag staat in `src/sjef/household/nutrition.py`.

### Budget & kosten
In `config.yaml` staan twee budget-mechanismen:
- `budget.target_eur` — streefbedrag dat de planner meekrijgt (mikt hieronder).
- `budget.cost_conscious: true` — laat de planner eiwit halen uit een mix met een
  groot deel goedkope niet-vlees bronnen (kwark, skyr, eieren, peulvruchten, tofu),
  vlees/vis als aanvulling. Dit is de grootste echte besparing.
- `limits.max_order_eur` — harde bovengrens. De **budget-trimstap**
  (`matcher.trim_to_budget`) snoeit een te ruim mandje deterministisch terug tot
  onder dit bedrag (duurste over-ingekochte regels eerst), en toont wat eraf ging.

Realistische richtlijn: volledige hoog-eiwit voeding (alle maaltijden) voor 2
personen kost ~€240/week. Zet de harde limiet niet té laag — de trim is blind voor
macro's (Picnic levert geen voedingswaarde bij het zoeken), dus een te lage cap
snijdt in je eiwit i.p.v. alleen in de overinkoop.

### Autonome wekelijkse run
Zet in `config.yaml` onder `weekly.auto`: `enabled: true`, plus `weekday`,
`time`, `mode` en eventueel een vast `request`. De bot maakt dan elke week op dat
tijdstip zelf een voorstel en stuurt het naar je in Telegram — **je keurt altijd
eerst goed; er wordt nooit automatisch besteld.**

Dit vereist dat de bot draait. Op macOS kun je hiervoor de meegeleverde
LaunchAgent gebruiken. De installatie- en beheerinstructies staan in
[deploy/com.supermarkt-agent.plist](deploy/com.supermarkt-agent.plist).
Je Mac moet op het geplande tijdstip wakker zijn en je moet ingelogd zijn.

### Betalen — hoe het echt werkt
Picnic heeft **geen betaallink per bestelling**. Betaling loopt via het
SEPA-incasso/iDEAL-mandaat dat je één keer in de Picnic-app instelt; bij het
bevestigen van de order schrijft Picnic automatisch af. **Jouw goedkeuring in
Telegram is dus de betaalautorisatie.** Je ziet vóór akkoord altijd de volledige
geïtemiseerde lijst + totaalbedrag, zodat je precies weet wat er afgeschreven wordt.

---

## Architectuur

```
src/sjef/
  cli.py               projectcommando’s
  config.py            configuratie en secrets
  selftest.py          offline controles van de pure logica
  interfaces/
    dashboard.py       Streamlit-dashboard
    telegram_bot.py    Telegram-bot en wekelijkse planning
    formatting.py      opmaak van menu’s en boodschappen
  picnic/
    picnic_client.py   Picnic-API en bestellen
    login_setup.py     inloggen met 2FA
    nutrition_lookup.py  voedingswaarden van Picnic-producten
  planning/
    planner.py         weekmenu genereren met Claude
    matcher.py         boodschappen aan producten koppelen
    orchestrator.py    voorstellen opbouwen en bestellingen uitvoeren
    meal_macros.py     macro’s per maaltijd berekenen
  household/
    profiles.py        huishoudprofielen laden en bewaren
    nutrition.py       voedingsdoelen en voedingskennis
    onboarding.py      vragen voor het instellen van profielen
deploy/
  com.supermarkt-agent.plist   launchd LaunchAgent die de bot draaiend houdt
```

**Twee strikt gescheiden fasen** zodat er nooit per ongeluk besteld wordt:
1. `build_proposal` — genereert en matcht, **wijzigt niets** bij Picnic.
2. `place_order` — vult mandje, boekt slot, bevestigt. Alleen na goedkeuring,
   met `DRY_RUN`- en budget-vangnetten.

---

## Ontwikkelen

Installeer de dependencies en controleer je wijzigingen:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run sjef selftest
```

## Wat is getest

- Python 3.13+ is vereist voor de Picnic-library met 2FA-ondersteuning.
- CI draait de tests met pytest en de offline selftests op Python 3.13 en 3.14.
- `uv run sjef selftest` dekt de pure logica: config-laden, productkeuze-heuristiek,
  plan-validatie, slot-parsing en opmaak — **zonder** netwerk of credentials.
- De live-paden (Picnic-login/zoeken/bestellen, Claude-call, Telegram) vereisen
  je eigen accounts en zijn daarom niet automatisch getest. Begin met `DRY_RUN=true`
  en `uv run sjef plan` om het end-to-end te zien zonder te bestellen.

## Bekend aandachtspunt
Het exacte order-bevestig-endpoint (`/cart/checkout/order/{id}/confirm`) en waar
het `order_id` in de cart-respons staat, kan per Picnic-versie verschillen. Als
er na het boeken van een slot geen `order_id` wordt gevonden, meldt de bot dat je
in de **app** moet bevestigen. Controleer dit bij de eerste echte bestelling.
