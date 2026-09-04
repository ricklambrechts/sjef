"""Tekstopmaak voor het voorstel (gedeeld door CLI en Telegram-bot).

De boodschappenlijst is plain text (productnamen kunnen Markdown breken). Het
menu wordt als monospace-tabel in een code block getoond (alleen daar gebruiken
we Markdown, met gesaneerde inhoud zodat het niet stuk kan).

`proposal_messages()` levert een lijst berichten op die elk binnen Telegram's
limiet passen, zodat ALLE producten worden getoond (niets afgekapt).
"""

from __future__ import annotations

TG_LIMIT = 3900  # veilig onder Telegram's 4096-tekenlimiet


def euro(cents: int) -> str:
    return f"€{cents / 100:.2f}"


def _san(text) -> str:
    """Verwijder tekens die een Markdown code block kunnen breken."""
    return str(text or "").replace("`", "'")


# ----------------------------------------------------------------- secties
def _overview_lines(proposal: dict) -> list[str]:
    plan = proposal["plan"]
    macros = proposal["macros"]
    lines = []
    persons = proposal.get("persons")
    if persons:
        lines.append("🍽️ WEEKMENU — huishouden")
        for p in persons:
            t = p["targets"]
            lines.append(
                f"  • {p['name']} ({p['goal']}): ~{t['kcal']} kcal / {t['eiwit_g']}g eiwit"
            )
    else:
        lines.append(f"🍽️ WEEKMENU — modus: {proposal['mode']}")
        lines.append(
            f"Doel: ~{macros['kcal_per_day']} kcal / {macros['protein_per_day']}g eiwit p.p.p.d."
        )
    if proposal.get("request"):
        lines.append(f"Verzoek: {proposal['request']}")
    if plan.get("samenvatting"):
        lines.append("")
        lines.append(plan["samenvatting"])
    return lines


_TYPE_EMOJI = {"ontbijt": "🥣", "lunch": "🥪", "diner": "🍽️", "snack": "🍎"}
_TYPE_ORDER = ["ontbijt", "lunch", "diner", "snack"]


def _strip_type_prefix(naam, meal_type: str) -> str:
    """Haal een dubbel maaltijdtype-woord vooraan de naam weg, bv.
    'Snack Niels: kwark' onder type 'snack' -> 'Niels: kwark'."""
    s = str(naam or "").strip()
    if s.lower().startswith(meal_type.lower() + " "):
        s = s[len(meal_type) + 1 :].lstrip()
    return s


def _menu_lines(proposal: dict) -> list[str]:
    """Menu als leesbare, mobielvriendelijke lijst (plain text, loopt netjes mee
    met de schermbreedte). Per dag gegroepeerd per maaltijd; gelijke gerechten
    voor beide personen worden samengevoegd met hun porties."""
    days = proposal["plan"].get("dagen", [])
    persons = [p["name"] for p in (proposal.get("persons") or [])]
    out: list[str] = ["📋 MENU"]
    for day in days:
        out.append("")
        out.append(
            f"📅 {day.get('dag', '?')} — samen ~{day.get('totaal_kcal', '?')} kcal / "
            f"{day.get('totaal_eiwit_g', '?')}g eiwit"
        )
        meals = day.get("maaltijden", [])
        by_type: dict[str, list[dict]] = {}
        for m in meals:
            by_type.setdefault(str(m.get("type", "overig")).lower(), []).append(m)
        ordered = [t for t in _TYPE_ORDER if t in by_type] + [
            t for t in by_type if t not in _TYPE_ORDER
        ]
        for t in ordered:
            group = by_type[t]
            emoji = _TYPE_EMOJI.get(t, "•")
            names = [_strip_type_prefix(g.get("naam", ""), t) for g in group]
            label = t.capitalize()
            if len(group) > 1 and len(set(names)) == 1:
                # zelfde gerecht, verschillende porties -> samenvoegen
                macros = []
                for i, g in enumerate(group):
                    who = f"{persons[i]} " if i < len(persons) else ""
                    macros.append(f"{who}{g.get('kcal', '?')}/{g.get('eiwit_g', '?')}g")
                out.append(f"{emoji} {label}: {names[0]}")
                out.append(f"      {' · '.join(macros)}")
            else:
                for i, g in enumerate(group):
                    out.append(f"{emoji} {label}: {names[i]}")
                    out.append(
                        f"      {g.get('kcal', '?')} kcal · {g.get('eiwit_g', '?')}g eiwit"
                    )
    return out


def _shopping_lines(proposal: dict) -> list[str]:
    lines = [f"🛒 BOODSCHAPPEN ({len(proposal['matched'])} producten):"]
    for m in proposal["matched"]:
        qty = f" ({m['unit_quantity']})" if m.get("unit_quantity") else ""
        cnt = f"{m['count']}× " if m["count"] > 1 else ""
        lines.append(f"  {cnt}{m['name']}{qty} — {euro(m['line_total_cents'])}")
    if proposal.get("unmatched"):
        lines.append("")
        lines.append("⚠️ NIET GEVONDEN (handmatig toevoegen):")
        for u in proposal["unmatched"]:
            lines.append(f"  · {u['item']}")
    lines.append("")
    lines.append(f"💶 TOTAAL: {euro(proposal['total_cents'])}")
    if proposal.get("over_budget"):
        lines.append("🚫 BOVEN je ingestelde budgetlimiet!")
    return lines


def _chunk(lines: list[str], limit: int = TG_LIMIT) -> list[str]:
    """Bundel regels tot berichten die onder de limiet blijven."""
    messages: list[str] = []
    current: list[str] = []
    cur_len = 0
    for ln in lines:
        if current and cur_len + len(ln) + 1 > limit:
            messages.append("\n".join(current))
            current, cur_len = [], 0
        current.append(ln)
        cur_len += len(ln) + 1
    if current:
        messages.append("\n".join(current))
    return messages


# ----------------------------------------------------------------- publiek
def proposal_messages(proposal: dict) -> list[dict]:
    """Lijst van te versturen berichten: {'text': str, 'markdown': bool}.

    Splitst over meerdere berichten zodat ALLE producten worden getoond en
    niets wordt afgekapt.
    """
    messages: list[dict] = []
    for chunk in _chunk(_overview_lines(proposal)):
        messages.append({"text": chunk, "markdown": False})
    for chunk in _chunk(_menu_lines(proposal)):
        messages.append({"text": chunk, "markdown": False})
    for chunk in _chunk(_shopping_lines(proposal)):
        messages.append({"text": chunk, "markdown": False})
    return messages


def format_proposal(proposal: dict) -> str:
    """Eén string met ALLES (overview + menu + boodschappen). Voor CLI/tests."""
    lines = list(_overview_lines(proposal))
    if proposal["plan"].get("dagen"):
        lines.append("")
        lines += _menu_lines(proposal)
    lines.append("")
    lines += _shopping_lines(proposal)
    return "\n".join(lines)
