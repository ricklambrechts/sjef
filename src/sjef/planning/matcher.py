"""Koppelt boodschappenlijst-items aan echte Picnic-producten via zoekopdrachten.

De keuzeheuristiek (`pick_best`) is een pure functie zonder netwerk, zodat hij
los te testen is. `match_shopping_list` doet de daadwerkelijke API-calls.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def clean_search_term(term: str) -> str:
    """Maak een zoekterm geschikt voor Picnic: haal verduidelijkingen tussen
    haakjes weg en alles na een komma. 'Paprika (mix)' -> 'paprika';
    'Rode linzen (voor soep)' -> 'rode linzen'; 'Eiwitpoeder (whey, naturel)'
    -> 'eiwitpoeder'. Zo vinden we veel meer en betere kandidaten.
    """
    t = re.sub(r"\(.*?\)", "", term or "")
    t = t.split(",")[0]
    return " ".join(t.split()).strip()


def flatten_results(results) -> list[dict]:
    """Picnic's search() geeft een lijst van groepen terug, elk met de echte
    producten onder 'items'. Sommige losse entries zijn al een product. Deze
    functie levert een platte lijst van product-dicts op.
    """
    flat: list[dict] = []
    for entry in results or []:
        if not isinstance(entry, dict):
            continue
        items = entry.get("items")
        if isinstance(items, list):
            flat.extend(i for i in items if isinstance(i, dict))
        elif entry.get("id"):  # entry is zelf al een product
            flat.append(entry)
    return flat


def normalize_candidate(raw: dict) -> dict | None:
    """Haal id, naam en prijs(cents) uit een Picnic-zoekresultaat.

    Picnic varieert de veldnamen; we proberen de bekende varianten en slaan
    resultaten zonder id of prijs over.
    """
    if not isinstance(raw, dict):
        return None
    pid = raw.get("id") or raw.get("sole_article_id") or raw.get("article_id")
    name = raw.get("name") or raw.get("title")
    price = (
        raw.get("display_price")
        if raw.get("display_price") is not None
        else raw.get("price")
    )
    if not pid or not name or price is None:
        return None
    return {
        "id": str(pid),
        "name": str(name),
        "price_cents": int(price),
        "unit_quantity": raw.get("unit_quantity", ""),
    }


def shortlist(
    results, search_term: str, max_item_cents: int, top_n: int = 10
) -> list[dict]:
    """Eerste top_n bruikbare kandidaten in PICNIC'S EIGEN zoekvolgorde.

    Picnic's zoekrelevantie is semantisch goed (zoek 'ui' -> 'Gele uien' eerst,
    'honing' -> echte honing eerst). We respecteren die volgorde i.p.v. te
    hersorteren met een eigen woord-heuristiek (die juist chips/sauzen/zeep met
    het woord naar boven haalde). Claude maakt daarna de correcte eindkeuze.
    Alleen filteren op een geldige prijs onder het per-item plafond.
    """
    out: list[dict] = []
    for raw in flatten_results(results):
        cand = normalize_candidate(raw)
        if cand is None:
            continue
        if cand["price_cents"] <= 0 or cand["price_cents"] > max_item_cents:
            continue
        out.append(cand)
        if len(out) >= top_n:
            break
    return out


def _fallback_terms(term: str) -> list[str]:
    """Alternatieve zoektermen als de exacte term niets oplevert. Picnic kent
    soms een bijvoeglijk naamwoord niet ('gehakte tomaten'); het hoofdwoord
    ('tomaten') of de laatste twee woorden werken dan vaak wel."""
    words = term.split()
    alts: list[str] = []
    if len(words) >= 2:
        alts.append(" ".join(words[-2:]))  # laatste twee woorden
        alts.append(words[-1])  # hoofdwoord (meestal achteraan)
    # dedup met behoud van volgorde, en niet de oorspronkelijke term herhalen
    seen = {term.lower()}
    out = []
    for a in alts:
        if a and a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


def gather_candidates(
    picnic, shopping_list: list[dict], max_item_eur: float, top_n: int = 10
) -> tuple[list[dict], list[dict]]:
    """Zoek per item kandidaten op. Geeft (items_met_kandidaten, geen_resultaat).

    items_met_kandidaten: [{planned_item, zoekterm, hoeveelheid, geschat_aantal,
    candidates: [normalized...]}]. Probeert fallback-zoektermen als de exacte
    term niets oplevert.
    """
    max_item_cents = int(max_item_eur * 100)
    with_candidates: list[dict] = []
    no_result: list[dict] = []
    for item in shopping_list:
        raw_term = item.get("zoekterm") or item.get("item", "")
        term = clean_search_term(raw_term) or raw_term

        cands: list[dict] = []
        used_term = term
        for candidate_term in [term, *_fallback_terms(term)]:
            try:
                results = picnic.search(candidate_term)
            except Exception as exc:
                log.warning("Zoeken naar '%s' mislukt: %s", candidate_term, exc)
                continue
            found = shortlist(results, candidate_term, max_item_cents, top_n)
            if found:
                cands = found
                used_term = candidate_term
                break

        if not cands:
            no_result.append(
                {"item": item.get("item", raw_term), "reason": "geen geschikte match"}
            )
            continue
        with_candidates.append(
            {
                "planned_item": item.get("item", raw_term),
                "zoekterm": used_term,
                "hoeveelheid": item.get("hoeveelheid", ""),
                "geschat_aantal": max(1, int(item.get("geschat_aantal", 1))),
                "voorraadkast": bool(item.get("voorraadkast", False)),
                "candidates": cands,
            }
        )
    return with_candidates, no_result


def pick_best(
    results: list[dict], search_term: str, max_item_cents: int
) -> dict | None:
    """Kies het beste product: hoogste naam-overlap, daarna laagste prijs.

    Slaat producten over die duurder zijn dan `max_item_cents` (sanity-check
    tegen verkeerde matches). Geeft None als er niets bruikbaars is.
    """
    want = _tokens(search_term)
    scored: list[tuple[int, int, dict]] = []
    for raw in flatten_results(results):
        cand = normalize_candidate(raw)
        if cand is None:
            continue
        if cand["price_cents"] <= 0 or cand["price_cents"] > max_item_cents:
            continue
        overlap = len(want & _tokens(cand["name"]))
        # Sorteersleutel: meer overlap eerst (negatief voor oplopende sort),
        # daarna goedkoopste.
        scored.append((-overlap, cand["price_cents"], cand))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]))
    return scored[0][2]


def match_shopping_list(picnic, shopping_list: list[dict], max_item_eur: float) -> dict:
    """Zoek elk item op bij Picnic en kies het beste product.

    Geeft terug: {"matched": [...], "unmatched": [...]}.
    Elk matched-item: id, name, count, unit_price_cents, line_total_cents, search_term.
    """
    max_item_cents = int(max_item_eur * 100)
    matched: list[dict] = []
    unmatched: list[dict] = []

    for item in shopping_list:
        term = item.get("zoekterm") or item.get("item", "")
        count = max(1, int(item.get("geschat_aantal", 1)))
        try:
            results = picnic.search(term)
        except Exception as exc:  # netwerk / API-fout: niet de hele run laten klappen
            log.warning("Zoeken naar '%s' mislukt: %s", term, exc)
            unmatched.append({"item": item.get("item", term), "reason": str(exc)})
            continue

        best = pick_best(results, term, max_item_cents)
        if best is None:
            unmatched.append(
                {"item": item.get("item", term), "reason": "geen geschikte match"}
            )
            continue

        matched.append(
            {
                "id": best["id"],
                "name": best["name"],
                "unit_quantity": best["unit_quantity"],
                "count": count,
                "unit_price_cents": best["price_cents"],
                "line_total_cents": best["price_cents"] * count,
                "search_term": term,
                "planned_item": item.get("item", term),
            }
        )

    return {"matched": matched, "unmatched": unmatched}


def _matched_entry(item: dict, cand: dict, count: int) -> dict:
    count = max(1, int(count))
    return {
        "id": cand["id"],
        "name": cand["name"],
        "unit_quantity": cand.get("unit_quantity", ""),
        "count": count,
        "unit_price_cents": cand["price_cents"],
        "line_total_cents": cand["price_cents"] * count,
        "search_term": item["zoekterm"],
        "planned_item": item["planned_item"],
        "voorraadkast": bool(item.get("voorraadkast", False)),
    }


def assemble_from_choices(
    items_with_candidates: list[dict], choices: list[dict]
) -> dict:
    """Bouw matched/unmatched uit Claude's keuzes.

    choices: [{index, product_id, aantal}]. product_id=None -> unmatched.
    Valt per item terug op de beste kandidaat als de index/id niet klopt.
    """
    by_index = {int(c["index"]): c for c in choices if "index" in c}
    matched: list[dict] = []
    unmatched: list[dict] = []
    for i, item in enumerate(items_with_candidates):
        choice = by_index.get(i)
        cands = {c["id"]: c for c in item["candidates"]}
        if choice and choice.get("product_id") in cands:
            cand = cands[choice["product_id"]]
            count = choice.get("aantal", item["geschat_aantal"])
            matched.append(_matched_entry(item, cand, count))
        elif choice and choice.get("product_id") is None:
            # Claude vond bewust geen passend product (bv. alleen afgeleide
            # producten zoals saus/zeep). Eerlijk als 'niet gevonden' melden i.p.v.
            # iets verkeerds bestellen.
            unmatched.append(
                {"item": item["planned_item"], "reason": "geen geschikte match"}
            )
        else:
            # Geen/ongeldige keuze -> heuristische fallback: beste kandidaat.
            matched.append(
                _matched_entry(item, item["candidates"][0], item["geschat_aantal"])
            )
    return {"matched": matched, "unmatched": unmatched}


def assemble_heuristic(items_with_candidates: list[dict]) -> dict:
    """Fallback zonder Claude: kies per item de beste (eerste) shortlist-kandidaat."""
    matched = [
        _matched_entry(item, item["candidates"][0], item["geschat_aantal"])
        for item in items_with_candidates
    ]
    return {"matched": matched, "unmatched": []}


def cart_total_cents(matched: list[dict]) -> int:
    return sum(m["line_total_cents"] for m in matched)


def trim_to_budget(
    matched: list[dict], max_cents: int
) -> tuple[list[dict], list[dict]]:
    """Snoei het mandje deterministisch tot het totaal <= max_cents is.

    Strategie: verlaag steeds het aantal van de duurste regel met aantal>1
    (zo verdwijnt eerst de overinkoop). Zijn alle aantallen 1, dan valt de
    duurste losse regel af. Geeft (nieuw_mandje, trim_overzicht) terug, waarbij
    trim_overzicht per geraakt product {name, removed_count, removed_cents} bevat.
    """
    items = [dict(m) for m in matched]
    removed: dict[str, dict] = {}

    def total() -> int:
        return sum(m["line_total_cents"] for m in items)

    guard = 0
    while total() > max_cents and items and guard < 100000:
        guard += 1
        reducible = [m for m in items if m["count"] > 1]
        if reducible:
            m = max(reducible, key=lambda x: x["line_total_cents"])
            m["count"] -= 1
            m["line_total_cents"] = m["unit_price_cents"] * m["count"]
            entry = removed.setdefault(
                m["id"], {"name": m["name"], "removed_count": 0, "removed_cents": 0}
            )
            entry["removed_count"] += 1
            entry["removed_cents"] += m["unit_price_cents"]
        else:
            m = max(items, key=lambda x: x["line_total_cents"])
            items.remove(m)
            entry = removed.setdefault(
                m["id"], {"name": m["name"], "removed_count": 0, "removed_cents": 0}
            )
            entry["removed_count"] += m["count"]
            entry["removed_cents"] += m["line_total_cents"]
    return items, list(removed.values())
