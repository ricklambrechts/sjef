"""Berekent de echte macro's per ingrediënt en per maaltijd uit Picnic-labels.

Voor elk hoofdingrediënt (met grammen) zoekt dit het bijbehorende Picnic-product,
haalt de voedingswaarde per 100 g op (nutrition_lookup, gecachet) en rekent uit:
    ingrediënt-kcal   = gram/100 × kcal_per_100g
    ingrediënt-eiwit  = gram/100 × eiwit_per_100g
De maaltijd-totalen worden de SOM hiervan (vervangt Claude's schatting); dag-
totalen worden de som van de maaltijden. Ingrediënten zonder voedingstabel
(bv. vers fruit) houden None en de maaltijd valt voor dat deel terug op schatting.
"""

from __future__ import annotations

import logging

from sjef.picnic import nutrition_lookup
from sjef.planning import matcher

log = logging.getLogger(__name__)


def _best_product(picnic, zoekterm: str, max_item_cents: int) -> dict | None:
    term = matcher.clean_search_term(zoekterm) or zoekterm
    try:
        results = picnic.search(term)
    except Exception as exc:
        log.warning("Ingrediënt zoeken mislukt '%s': %s", term, exc)
        return None
    cands = matcher.shortlist(results, term, max_item_cents, top_n=1)
    return cands[0] if cands else None


def _nutrition_map(picnic, zoekterms: set[str], max_item_cents: int) -> dict:
    """{zoekterm: {'per100g': {...}, 'product': naam}} voor unieke zoektermen."""
    out: dict[str, dict] = {}
    for zt in sorted(zoekterms):
        prod = _best_product(picnic, zt, max_item_cents)
        if not prod:
            out[zt] = {"per100g": {}, "product": None}
            continue
        per100g = nutrition_lookup.fetch_nutrition(picnic.api, prod["id"])
        out[zt] = {"per100g": per100g, "product": prod["name"]}
    return out


def _ingredient_total_gram(ing: dict) -> float:
    """Totale gram van een ingrediënt over alle personen (voor weergave/boodschappen)."""
    porties = ing.get("porties")
    if isinstance(porties, list):
        return sum(float(p.get("gram") or 0) for p in porties)
    return float(ing.get("gram") or 0)  # legacy: 1 totaalwaarde


def _person_grams(ing: dict, persons: list[str]) -> dict[str, float]:
    """{persoon: gram} voor dit ingrediënt. Bij legacy (geen porties) wordt het
    totaal gelijk verdeeld over de personen."""
    porties = ing.get("porties")
    if isinstance(porties, list):
        out = {p: 0.0 for p in persons}
        for p in porties:
            name = str(p.get("persoon", "")).strip()
            if name in out:
                out[name] += float(p.get("gram") or 0)
            elif persons:  # onbekende naam -> aan eerste persoon toekennen
                out[persons[0]] += float(p.get("gram") or 0)
        return out
    total = float(ing.get("gram") or 0)
    share = total / len(persons) if persons else 0
    return {p: share for p in persons}


def enrich(
    plan: dict, picnic, max_item_eur: float, persons: list[str] | None = None
) -> dict:
    """Verrijk het plan met echte macro's per ingrediënt en per persoon.

    Zet per ingrediënt: totale gram, bron_product, kcal/eiwit (totaal) en
    per_persoon {naam: {gram, kcal, eiwit_g}}. Per maaltijd en per dag worden de
    totalen per persoon opgeteld in resp. meal['per_persoon'] en day['per_persoon'].
    """
    max_item_cents = int(max_item_eur * 100)
    persons = persons or []

    zoekterms: set[str] = set()
    for day in plan.get("dagen", []):
        for meal in day.get("maaltijden", []):
            for ing in meal.get("ingredienten", []) or []:
                zt = (ing.get("zoekterm") or ing.get("naam") or "").strip()
                if zt:
                    zoekterms.add(zt)
    if not zoekterms:
        return plan

    log.info("Macro's berekenen voor %d unieke ingrediënten...", len(zoekterms))
    nmap = _nutrition_map(picnic, zoekterms, max_item_cents)

    def _blank():
        return {p: {"kcal": 0.0, "eiwit_g": 0.0} for p in persons}

    for day in plan.get("dagen", []):
        day_pp = _blank()
        for meal in day.get("maaltijden", []):
            meal_pp = _blank()
            m_kcal = 0.0
            m_eiwit = 0.0
            computed_any = False
            all_computed = True
            for ing in meal.get("ingredienten", []) or []:
                zt = (ing.get("zoekterm") or ing.get("naam") or "").strip()
                info = nmap.get(zt, {})
                per100g = info.get("per100g") or {}
                ing["bron_product"] = info.get("product")
                total_g = _ingredient_total_gram(ing)
                ing["gram"] = round(total_g)  # totaal, voor weergave/boodschappen
                pg = _person_grams(ing, persons)
                if per100g.get("kcal") is not None and total_g > 0:
                    kpg = per100g["kcal"]
                    epg = per100g.get("eiwit_g", 0) or 0
                    ing["kcal"] = round(total_g / 100 * kpg)
                    ing["eiwit_g"] = round(total_g / 100 * epg, 1)
                    ing["per_persoon"] = {
                        name: {
                            "gram": round(g),
                            "kcal": round(g / 100 * kpg),
                            "eiwit_g": round(g / 100 * epg, 1),
                        }
                        for name, g in pg.items()
                    }
                    for name, g in pg.items():
                        meal_pp[name]["kcal"] += g / 100 * kpg
                        meal_pp[name]["eiwit_g"] += g / 100 * epg
                    m_kcal += ing["kcal"]
                    m_eiwit += total_g / 100 * epg
                    computed_any = True
                else:
                    ing["kcal"] = None
                    ing["eiwit_g"] = None
                    ing["per_persoon"] = None
                    all_computed = False
            if computed_any:
                meal["ingr_kcal"] = round(m_kcal)
                meal["ingr_eiwit"] = round(m_eiwit)
                meal["ingr_volledig"] = all_computed
                meal["per_persoon"] = {
                    p: {"kcal": round(v["kcal"]), "eiwit_g": round(v["eiwit_g"])}
                    for p, v in meal_pp.items()
                }
                for p in persons:
                    day_pp[p]["kcal"] += meal_pp[p]["kcal"]
                    day_pp[p]["eiwit_g"] += meal_pp[p]["eiwit_g"]
        if any(day_pp[p]["kcal"] for p in persons):
            day["per_persoon"] = {
                p: {"kcal": round(v["kcal"]), "eiwit_g": round(v["eiwit_g"])}
                for p, v in day_pp.items()
            }

    return plan
