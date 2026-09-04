"""Maaltijdplanner op basis van de Claude API.

Genereert een weekmenu afgestemd op macro-doelen, dieetprofiel en huishouden,
en levert een geconsolideerde boodschappenlijst met zoektermen voor Picnic.

Gebruikt forced tool-use zodat we gegarandeerd geldige JSON terugkrijgen, en
prompt caching op de (statische) system prompt om kosten te drukken.
"""

from __future__ import annotations

import logging

from anthropic import Anthropic

from sjef.config import Config
from sjef.household.nutrition import NUTRITION_PRINCIPLES

log = logging.getLogger(__name__)

# JSON-schema dat Claude MOET invullen (forced tool use).
PLAN_TOOL = {
    "name": "weekmenu",
    "description": "Lever het weekmenu en de boodschappenlijst in dit formaat.",
    "input_schema": {
        "type": "object",
        "properties": {
            "samenvatting": {
                "type": "string",
                "description": "Korte samenvatting van het weekplan (1-3 zinnen).",
            },
            "dagen": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dag": {"type": "string"},
                        "maaltijden": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "naam": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "enum": ["ontbijt", "lunch", "diner", "snack"],
                                    },
                                    "kcal": {"type": "integer"},
                                    "eiwit_g": {"type": "integer"},
                                    "ingredienten": {
                                        "type": "array",
                                        "description": "De hoofdingrediënten van deze maaltijd. Geef per ingrediënt "
                                        "de hoeveelheid in gram/ml PER PERSOON (porties), zodat de macro's per persoon "
                                        "exact berekend kunnen worden.",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "naam": {
                                                    "type": "string",
                                                    "description": "Ingrediënt, bv. 'Magere kwark'.",
                                                },
                                                "zoekterm": {
                                                    "type": "string",
                                                    "description": "Korte, generieke zoekterm voor Picnic.",
                                                },
                                                "porties": {
                                                    "type": "array",
                                                    "description": "Hoeveelheid in gram/ml per persoon. Gebruik exact de "
                                                    "namen van de personen. Eet iemand dit ingrediënt niet, geef 0.",
                                                    "items": {
                                                        "type": "object",
                                                        "properties": {
                                                            "persoon": {
                                                                "type": "string"
                                                            },
                                                            "gram": {"type": "number"},
                                                        },
                                                        "required": ["persoon", "gram"],
                                                    },
                                                },
                                            },
                                            "required": ["naam", "zoekterm", "porties"],
                                        },
                                    },
                                },
                                "required": [
                                    "naam",
                                    "type",
                                    "kcal",
                                    "eiwit_g",
                                    "ingredienten",
                                ],
                            },
                        },
                        "totaal_kcal": {"type": "integer"},
                        "totaal_eiwit_g": {"type": "integer"},
                    },
                    "required": ["dag", "maaltijden", "totaal_kcal", "totaal_eiwit_g"],
                },
            },
            "boodschappenlijst": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {
                            "type": "string",
                            "description": "Productnaam, bv. 'Kipfilet'",
                        },
                        "zoekterm": {
                            "type": "string",
                            "description": "Zoekterm voor de Picnic-app, kort en generiek.",
                        },
                        "hoeveelheid": {
                            "type": "string",
                            "description": "Benodigde hoeveelheid voor de hele week, bv. '1.4 kg' of '12 stuks'.",
                        },
                        "geschat_aantal": {
                            "type": "integer",
                            "description": "Hoeveel verpakkingen er ongeveer nodig zijn.",
                            "minimum": 1,
                        },
                        "categorie": {"type": "string"},
                        "voorraadkast": {
                            "type": "boolean",
                            "description": "True voor lang houdbare basics die mensen meestal al in huis "
                            "hebben: kruiden, specerijen, sauzen, olie, azijn, bouillon, mosterd, honing, "
                            "zout/peper, bakproducten. False voor verse/wekelijkse producten (vlees, vis, "
                            "zuivel, groente, fruit, brood, granen).",
                        },
                    },
                    "required": [
                        "item",
                        "zoekterm",
                        "hoeveelheid",
                        "geschat_aantal",
                        "voorraadkast",
                    ],
                },
            },
        },
        "required": ["samenvatting", "dagen", "boodschappenlijst"],
    },
}


def build_system_prompt(include_principles: bool = True) -> str:
    base = (
        "Je bent een Nederlandse voedingscoach en meal-prep-planner. "
        "Je stelt realistische, lekkere en gevarieerde weekmenu's samen die nauwkeurig "
        "aansluiten op opgegeven calorie- en eiwitdoelen. Je houdt je strikt aan dieet"
        "restricties en uitsluitingen. Producten kies je zo dat ze bij de Nederlandse "
        "supermarkt Picnic te vinden zijn; zoektermen houd je kort en generiek en zoals "
        "Picnic producten benoemt (bv. 'kipfilet', niet 'biologische scharrelkipfilet 500g'; "
        "voor ingeblikte tomaten 'tomatenblokjes' of 'passata', niet 'gehakte tomaten'). "
        "Je consolideert de "
        "boodschappenlijst (geen dubbele items) en schat realistische verpakkingsaantallen "
        "voor het hele huishouden over de hele periode. Vergeet kook-basics niet die de "
        "recepten nodig hebben (ui, knoflook, kruiden, olie e.d.). Als de gebruiker "
        "expliciet om niet-eten producten vraagt (huishoudelijk zoals wc-papier, "
        "schoonmaak, toiletartikelen), voeg die dan ook toe aan de boodschappenlijst."
    )
    if include_principles:
        base += "\n\n" + NUTRITION_PRINCIPLES
    return base


def _budget_block(target_eur: float | None, cost_conscious: bool) -> list[str]:
    """Gedeelde budget- en kostenbewust-instructie voor beide prompt-modi."""
    lines: list[str] = []
    if target_eur:
        lines.append(
            f"BUDGET: mik op een TOTALE boodschappenlijst rond of onder €{int(target_eur)} "
            f"voor de hele periode. Kies realistische, niet-overdreven hoeveelheden — "
            f"niet meer dan nodig voor de porties en het aantal personen."
        )
    if cost_conscious:
        lines.append(
            "KOSTENBEWUST EIWIT: haal het eiwit NADRUKKELIJK uit een mix, met een groot "
            "deel uit GOEDKOPE NIET-VLEES bronnen: magere kwark, skyr, Griekse yoghurt, "
            "eieren, cottage cheese, peulvruchten (linzen, kikkererwten, zwarte bonen), "
            "tofu/tempeh/edamame, magere zuivel, volkoren granen en havermout. Mik op "
            "ruwweg de helft van het dag-eiwit uit deze betaalbare bronnen. Gebruik vlees "
            "en vis als AANVULLING, niet als enige eiwitbron, en kies dan betaalbaar "
            "(kipfilet/kipdij, mager of half-om-half gehakt, tonijn uit blik). Beperk dure "
            "premium (verse zalm, biologisch) tot hooguit 1-2 keer per week. Zo blijven de "
            "eiwitdoelen haalbaar binnen het budget."
        )
    if lines:
        lines.append("")
    return lines


def build_profiles_prompt(
    ctx: dict,
    request: str | None = None,
    budget_target_eur: float | None = None,
    cost_conscious: bool = False,
) -> str:
    """User prompt voor de profielen-modus: meerdere personen, elk eigen doel."""
    lines = [
        f"Maak een COMPLEET weekmenu + boodschappenlijst voor een huishouden voor "
        f"{ctx['days']} dagen, inclusief ontbijt, lunch, diner én gezonde snacks per dag.",
        f"Aantal personen: {len(ctx['persons'])}.",
        "",
        "PERSONEN MET ELK HUN EIGEN DAGDOELEN (respecteer deze afzonderlijk):",
    ]
    for i, p in enumerate(ctx["persons"], 1):
        lines.append(f"{i}. {p['summary']}")
    lines.append("")

    if ctx.get("household_notes"):
        lines.append(f"Huishoud-brede aandachtspunten: {ctx['household_notes']}")
        lines.append("")

    if ctx.get("shared_meals"):
        lines += [
            "AANPAK: kook waar mogelijk DEZELFDE gerechten voor iedereen maar met "
            "AANGEPASTE PORTIES per persoon. Het calorieverschil (bv. wie cut) haal je uit "
            "de TOTALE calorieën — NIET door koolhydraten weg te laten. Houd voor wie "
            "afvalt de koolhydraten op peil voor energie en training (ruim rond "
            "trainingsmomenten); stuur het tekort vooral via portiegrootte en wat minder "
            "vet/extra's. Wie bulkt krijgt grotere porties en meer calorieën. "
            "Waar de doelen te ver uiteenlopen mag je per persoon aparte componenten "
            "(zoals snacks of bijgerechten) kiezen. Geef in de maaltijdnamen kort aan "
            "voor wie de portie/variant is.",
        ]
    else:
        lines += [
            "AANPAK: stel per persoon een passend menu samen dat bij de eigen doelen past.",
        ]
    lines.append("")

    need = ctx.get("weekly_need")
    if need:
        lines += [
            f"TOTALE BEHOEFTE VOOR HET HELE HUISHOUDEN OVER {ctx['days']} DAGEN: "
            f"~{need['kcal']} kcal en ~{need['eiwit_g']} g eiwit "
            f"(samen ~{need['daily_kcal']} kcal en ~{need['daily_eiwit_g']} g eiwit per dag).",
            "BELANGRIJK: de boodschappenlijst moet hier qua totaal ONGEVEER op uitkomen. "
            "Tel het geleverde eiwit van alle producten samen op tot ongeveer de "
            f"~{need['eiwit_g']} g die nodig is — koop NIET fors meer in (max ~15% marge). "
            "Vermijd dubbele/overlappende eiwitbronnen die samen ver boven de behoefte komen.",
            "",
        ]

    lines += _budget_block(budget_target_eur, cost_conscious)

    if request:
        lines += [
            "SPECIFIEK VERZOEK VOOR DEZE WEEK — dit heeft VOORRANG op de standaard "
            "structuur; reken porties/hoeveelheden hierop door:",
            request.strip(),
            "",
        ]

    lines += [
        "Zorg dat de dagtotalen per persoon dicht bij hun eigen doelen liggen (binnen ~10%). "
        "Consolideer alle benodigde producten in één gezamenlijke boodschappenlijst voor het "
        "hele huishouden over de hele periode, met realistische verpakkingsaantallen. "
        "Markeer per product 'voorraadkast': true voor lang houdbare basics die men vaak al "
        "in huis heeft (kruiden, specerijen, sauzen, olie, azijn, bouillon, mosterd, honing, "
        "zout/peper), en false voor verse/wekelijkse producten.",
        "Geef bij ELKE maaltijd de hoofdingrediënten met een korte generieke zoekterm en "
        "de hoeveelheid in gram/ml PER PERSOON (porties), met exact de namen "
        f"{', '.join(p['name'] for p in ctx['persons'])}. Voorbeeld: havermout — "
        f"{ctx['persons'][0]['name']} 80 g, {ctx['persons'][-1]['name']} 60 g. Stem de "
        "porties zo af dat ELKE persoon zijn eigen dagdoel (kcal én eiwit) haalt. Deze "
        "hoeveelheden worden gebruikt om de echte macro's per persoon te berekenen, dus "
        "wees realistisch en consistent met de genoemde kcal/eiwit.",
        "Lever het resultaat via de tool 'weekmenu'.",
    ]
    return "\n".join(lines)


def build_user_prompt(
    config: Config, mode: str, macros: dict, request: str | None = None
) -> str:
    exclude = ", ".join(config.diet_exclude) or "geen"
    prefer = ", ".join(config.diet_prefer) or "geen specifieke"
    lines = [
        f"Maak een weekmenu voor standaard {config.people} perso(o)n(en) voor {config.days} dagen.",
        f"Dieetprofiel: {config.diet_profile}.",
        f"Doel-modus: {mode}.",
        f"Macro-doelen PER PERSOON PER DAG: ~{macros['kcal_per_day']} kcal en ~{macros['protein_per_day']} g eiwit.",
        f"Uitsluiten (nooit gebruiken): {exclude}.",
        f"Voorkeuren (graag gebruiken): {prefer}.",
    ]
    if request:
        lines += [
            "",
            "SPECIFIEK VERZOEK VOOR DEZE WEEK — volg dit qua structuur, "
            "aantal maaltijden en porties/aantal personen per maaltijd. Dit heeft "
            "VOORRANG op de standaard aantallen hierboven. Reken de boodschappen-"
            "hoeveelheden door op de gevraagde porties:",
            request.strip(),
            "",
            "Gebruik de macro-doelen als richtlijn voor gezonde verhoudingen, maar "
            "de gevraagde structuur is leidend.",
        ]
    else:
        lines += [
            "",
            "Zorg dat de dagtotalen dicht bij de macro-doelen liggen (binnen ~10%).",
        ]
    budget = _budget_block(config.budget_target_eur, config.cost_conscious)
    if budget:
        lines += [""] + budget
    lines.append("Lever het resultaat via de tool 'weekmenu'.")
    return "\n".join(lines)


def generate_plan(
    config: Config,
    mode: str,
    api_key: str,
    model: str,
    request: str | None = None,
    profiles_ctx: dict | None = None,
) -> dict:
    """Roept Claude aan en geeft het gevalideerde plan-dict terug.

    `request` is een optionele vrije-tekst-opdracht (bv. '4x avondeten voor 4
    personen, 2 lunches voor 2, 3 gezonde snacks').

    `profiles_ctx` (indien aanwezig) schakelt over op de profielen-modus:
    meerdere personen met elk hun eigen berekende doelen. Anders de legacy
    single-mode op basis van config.macro_modes.
    """
    if profiles_ctx:
        user_prompt = build_profiles_prompt(
            profiles_ctx,
            request,
            budget_target_eur=config.budget_target_eur,
            cost_conscious=config.cost_conscious,
        )
    else:
        macros = config.macros_for(mode)
        user_prompt = build_user_prompt(config, mode, macros, request)

    client = Anthropic(api_key=api_key)
    # Streaming: nodig bij een hoog max_tokens (de SDK weigert anders een
    # non-streaming request die >10 min zou kunnen duren). Ruim budget omdat de
    # output met ingrediënten per maaltijd groter is; je betaalt alleen wat echt
    # gebruikt wordt.
    with client.messages.stream(
        model=model,
        max_tokens=24000,
        system=[
            {
                "type": "text",
                "text": build_system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[PLAN_TOOL],
        tool_choice={"type": "tool", "name": "weekmenu"},
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == "max_tokens":
        raise RuntimeError(
            "Het menu werd te lang en is afgekapt vóór de boodschappenlijst af was. "
            "Verklein het verzoek (minder dagen/maaltijden) of verhoog max_tokens."
        )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "weekmenu":
            return validate_plan(block.input)
    raise RuntimeError("Claude gaf geen geldig weekmenu terug.")


def validate_plan(plan: dict) -> dict:
    """Lichte sanity-checks zodat downstream code geen verrassingen krijgt."""
    if not isinstance(plan, dict):
        raise ValueError("Plan is geen object")
    items = plan.get("boodschappenlijst")
    if not items:
        raise ValueError("Plan bevat geen boodschappenlijst")
    for it in items:
        it.setdefault("geschat_aantal", 1)
        if int(it["geschat_aantal"]) < 1:
            it["geschat_aantal"] = 1
    return plan


# ---------------------------------------------------------------------------
# Productkeuze: laat Claude per item het beste Picnic-product kiezen uit een
# shortlist (betere keuzes dan puur 'goedkoopst': let op pakgrootte vs. de
# benodigde weekhoeveelheid, prijs-per-kilo en naam-relevantie).
# ---------------------------------------------------------------------------
CHOOSE_TOOL = {
    "name": "productkeuzes",
    "description": "Kies per boodschap het beste Picnic-product uit de kandidaten.",
    "input_schema": {
        "type": "object",
        "properties": {
            "keuzes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Index van het boodschap-item.",
                        },
                        "product_id": {
                            "type": ["string", "null"],
                            "description": "Gekozen product-id, of null als geen kandidaat past.",
                        },
                        "aantal": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Hoeveel verpakkingen kopen voor de benodigde weekhoeveelheid.",
                        },
                    },
                    "required": ["index", "product_id", "aantal"],
                },
            }
        },
        "required": ["keuzes"],
    },
}


def _candidate_block(items_with_candidates: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items_with_candidates):
        need = f" (nodig: {item['hoeveelheid']})" if item.get("hoeveelheid") else ""
        lines.append(
            f"[{i}] {item['planned_item']}{need} — geschat {item['geschat_aantal']} verpakking(en):"
        )
        for c in item["candidates"]:
            uq = c.get("unit_quantity", "?")
            lines.append(
                f"    id={c['id']} | {c['name']} | {uq} | €{c['price_cents'] / 100:.2f}"
            )
    return "\n".join(lines)


def choose_products(
    items_with_candidates: list[dict], api_key: str, model: str
) -> list[dict]:
    """Laat Claude per item het beste product + aantal kiezen. Eén batch-call."""
    if not items_with_candidates:
        return []
    system = (
        "Je kiest voor een boodschappenbestelling per item het beste product uit een "
        "lijst kandidaten van de Nederlandse supermarkt Picnic. Let op: (1) kies een "
        "redelijke pakgrootte — vermijd mini-verpakkingen als er veel nodig is, en let "
        "op prijs per kilo/liter; (2) bepaal hoeveel verpakkingen nodig zijn voor de "
        "benodigde weekhoeveelheid. "
        "CORRECTHEID GAAT VOOR: kies het product dat het item ZELF is, niet een gerecht, "
        "saus, snack of ander product dat het item slechts als ingrediënt bevat. "
        "Voorbeelden: voor 'honing' kies een POT honing (ook 'Bloemenhoning'), NIET "
        "'handzeep met honing'; voor 'knoflook' verse knoflook of 'Bio knoflook', NIET "
        "'tomatenblokjes met knoflook'; voor 'ui' verse uien ('Gele uien'), NIET "
        "'aardappel met ui'; voor 'paprika' verse paprika, NIET paprika-chips. "
        "Merk- en bio-varianten van het juiste product zijn prima. Pas als er ECHT geen "
        "product is dat het item zelf is (alleen afgeleide producten), kies product_id=null."
    )
    user = (
        "Kies per item (op index) het beste product en het aantal verpakkingen.\n\n"
        + _candidate_block(items_with_candidates)
    )
    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        tools=[CHOOSE_TOOL],
        tool_choice={"type": "tool", "name": "productkeuzes"},
        messages=[{"role": "user", "content": user}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "productkeuzes":
            return block.input.get("keuzes", [])
    return []
