"""Knoopt planner, matcher en Picnic-client aan elkaar.

Twee fasen, bewust gescheiden zodat er nooit per ongeluk besteld wordt:
  1. build_proposal()  -> genereert plan + matcht producten + leest slots.
                          Wijzigt NIETS bij Picnic.
  2. place_order()      -> vult mandje, boekt slot, bevestigt order.
                          Wordt alleen aangeroepen na expliciete goedkeuring,
                          en respecteert dry_run + max_order_eur.
"""
from __future__ import annotations

import logging
from datetime import datetime

from .config import Config, Secrets
from .profiles import Profiles
from . import matcher, meal_macros, planner

log = logging.getLogger(__name__)


def euro(cents: int) -> str:
    return f"€{cents / 100:.2f}"


# --------------------------------------------------------------- fase 1
def build_proposal(
    config: Config,
    secrets: Secrets,
    picnic,
    mode: str | None,
    request: str | None = None,
    extra_items: list[str] | None = None,
) -> dict:
    mode = (mode or config.default_mode).lower()
    macros = config.macros_for(mode)

    # Profielen-modus als profiles.yaml bestaat; anders legacy single-mode.
    profiles = Profiles.load()
    if profiles and not profiles.persons:
        raise ValueError(
            "Geen actieve personen — zet minstens één persoon op 'actief' in de instellingen."
        )
    profiles_ctx = profiles.planner_context() if profiles else None

    log.info(
        "Weekmenu genereren (profielen=%s, mode=%s, vrij verzoek=%s)...",
        bool(profiles_ctx),
        mode,
        bool(request),
    )
    plan = planner.generate_plan(
        config,
        mode,
        api_key=secrets.anthropic_api_key,
        model=secrets.planner_model,
        request=request,
        profiles_ctx=profiles_ctx,
    )

    # Echte macro's per ingrediënt + per persoon uit Picnic-labels.
    person_names = [p["name"] for p in profiles_ctx["persons"]] if profiles_ctx else []
    try:
        plan = meal_macros.enrich(plan, picnic, config.max_item_eur, persons=person_names)
    except Exception as exc:
        log.warning("Macro-verrijking mislukt (%s); menu houdt de schattingen.", exc)

    # Vaste staples toevoegen aan de lijst (als ze er nog niet in staan).
    shopping = list(plan.get("boodschappenlijst", []))
    existing_terms = {i.get("zoekterm", "").lower() for i in shopping}
    for term, count in config.staples.items():
        if term.lower() not in existing_terms:
            shopping.append(
                {"item": term, "zoekterm": term, "hoeveelheid": "", "geschat_aantal": int(count)}
            )

    # Losse extra's voor deze bestelling (bv. wc-papier, schoonmaak). Worden
    # gegarandeerd toegevoegd (niet afhankelijk van de planner).
    for raw in extra_items or []:
        term = str(raw).strip()
        if term and term.lower() not in existing_terms:
            existing_terms.add(term.lower())
            shopping.append(
                {"item": term, "zoekterm": term, "hoeveelheid": "", "geschat_aantal": 1}
            )

    # Per-persoon overzicht voor weergave (alleen in profielen-modus).
    persons_display = None
    if profiles_ctx:
        persons_display = [
            {"name": p["name"], "goal": p["goal"], "targets": p["targets"]}
            for p in profiles_ctx["persons"]
        ]

    log.info("Producten zoeken bij Picnic (%d items)...", len(shopping))
    with_candidates, no_result = matcher.gather_candidates(
        picnic, shopping, config.max_item_eur
    )

    # Claude kiest per item het beste product (pakgrootte/prijs-per-kilo);
    # valt terug op de heuristische shortlist-keuze als de call faalt.
    try:
        log.info("Claude kiest beste producten (%d items)...", len(with_candidates))
        choices = planner.choose_products(
            with_candidates, api_key=secrets.anthropic_api_key, model=secrets.planner_model
        )
        match = matcher.assemble_from_choices(with_candidates, choices)
    except Exception as exc:
        log.warning("Productkeuze via Claude mislukt (%s); heuristische fallback.", exc)
        match = matcher.assemble_heuristic(with_candidates)

    match["unmatched"] = match.get("unmatched", []) + no_result

    # Harde budget-trimstap: garandeer dat het mandje onder de limiet blijft.
    trimmed: list[dict] = []
    raw_total = matcher.cart_total_cents(match["matched"])
    max_cents = int(config.max_order_eur * 100)
    if raw_total > max_cents:
        log.info("Mandje €%.2f boven limiet; trimmen naar €%.2f", raw_total / 100, max_cents / 100)
        match["matched"], trimmed = matcher.trim_to_budget(match["matched"], max_cents)

    total = matcher.cart_total_cents(match["matched"])

    slots = parse_slots(picnic.get_delivery_slots())

    return {
        "mode": mode,
        "macros": macros,
        "persons": persons_display,
        "request": request,
        "plan": plan,
        "matched": match["matched"],
        "unmatched": match["unmatched"],
        "trimmed": trimmed,
        "raw_total_cents": raw_total,
        "total_cents": total,
        "slots": slots,
        "over_budget": total > config.max_order_eur * 100,
    }


def parse_slots(raw: dict) -> list[dict]:
    """Normaliseer de bezorgslot-respons tot [{slot_id, start, end, label}]."""
    slots = []
    candidates = []
    if isinstance(raw, dict):
        candidates = raw.get("delivery_slots") or raw.get("slots") or []
    for s in candidates:
        if not isinstance(s, dict):
            continue
        sid = s.get("slot_id") or s.get("id")
        start = s.get("window_start") or s.get("start")
        end = s.get("window_end") or s.get("end")
        if not sid:
            continue
        slots.append(
            {
                "slot_id": str(sid),
                "start": start,
                "end": end,
                "label": _slot_label(start, end),
                "available": s.get("is_available", True),
            }
        )
    return slots


def _slot_label(start, end) -> str:
    def fmt(x):
        if not x:
            return "?"
        try:
            dt = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
            return dt.strftime("%a %d-%m %H:%M")
        except (ValueError, TypeError):
            return str(x)

    return f"{fmt(start)} – {fmt(end)[-5:] if end else '?'}"


# --------------------------------------------------------------- fase 2
def place_order(config: Config, picnic, proposal: dict, slot_id: str) -> dict:
    """Plaats de bestelling. Alleen aanroepen na expliciete goedkeuring.

    Respecteert dry_run (in de PicnicClient) en de harde uitgavenlimiet hier.
    """
    total = proposal["total_cents"]
    if total > config.max_order_eur * 100:
        return {
            "ok": False,
            "reason": f"Totaal {euro(total)} boven limiet {euro(int(config.max_order_eur*100))}. "
            f"Pas max_order_eur aan of verklein de bestelling.",
        }
    if not proposal["matched"]:
        return {"ok": False, "reason": "Geen producten om te bestellen."}

    log.info("Mandje leegmaken en opnieuw vullen...")
    picnic.clear_cart()
    for m in proposal["matched"]:
        picnic.add_product(m["id"], m["count"])

    log.info("Bezorgslot boeken: %s", slot_id)
    cart = picnic.set_delivery_slot(slot_id)

    order_id = picnic.extract_order_id(cart or {})
    confirm_result = None
    if order_id:
        log.info("Order bevestigen: %s", order_id)
        confirm_result = picnic.confirm_order(order_id)
    else:
        # Geen echt order-id (cart heeft alleen het label 'shopping_cart'):
        # mandje is gevuld en slot geboekt, maar de order is NIET geplaatst.
        # In de praktijk vereist Picnic de laatste bevestiging/betaling in de app.
        log.warning("Geen geldig order-id; order niet automatisch geplaatst — afronden in de app.")

    return {
        "ok": True,
        "dry_run": picnic.dry_run,
        "order_id": order_id,
        # Zonder echt order-id is er NIET besteld (ook niet in live-modus):
        # de gebruiker moet in de Picnic-app afrekenen.
        "needs_app_confirm": order_id is None and not picnic.dry_run,
        "total_cents": total,
        "slot_id": slot_id,
        "confirm_result": confirm_result,
    }
