"""Leest voedingswaarden (per 100 g/ml) uit een Picnic product-detailrespons.

Picnic's `/pages/product-details-page-root` bevat een voedingswaardetabel in een
PML-component-boom; de officiële library leest die niet uit. `parse_nutrition`
haalt kcal/eiwit/koolhydraten/vet per 100 g eruit.

De tabel ziet er (na strippen) zo uit:
    'Per 100 g' · 'Energie' · '235 kJ /' · 'kcal' · '56 kcal'
    'Koolhydraten' · '2,7g' · 'waarvan suikers' · '2,7g'
    'Vet' · '0,1g' · 'waarvan verzadigd' · '0,0g'
    'Eiwit' · '10g' · 'Zout' · '0,1g'

Daarom: lees pas NÁ de kop 'Per 100 g', neem per voedingsstof de eerste passende
waarde in de paar regels erna (de kcal-waarde staat een paar regels verder).
Verse producten (groente/fruit) hebben vaak geen tabel → lege dict.
"""

from __future__ import annotations

import json
import logging
import re

from sjef.config import ROOT

log = logging.getLogger(__name__)

_CACHE_FILE = ROOT / "state" / "nutrition_cache.json"

# exacte labels in de tabel -> sleutel in ons resultaat
_LABELS = {
    "energie": "kcal",
    "eiwit": "eiwit_g",
    "eiwitten": "eiwit_g",
    "koolhydraten": "koolhydraten_g",
    "vet": "vet_g",
    "vetten": "vet_g",
}


def _num(text: str) -> float | None:
    """'2,7g' -> 2.7 ; '56 kcal' -> 56 ; '0, 0 g' -> 0.0."""
    cleaned = text.replace(" ", "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    return float(m.group(1)) if m else None


def _markdown_strings(raw_pdp) -> list[str]:
    blob = json.dumps(raw_pdp, ensure_ascii=False)
    out = []
    for m in re.findall(r'"markdown"\s*:\s*"([^"]*)"', blob):
        s = re.sub(r"#\(#\w+\)", "", m).strip()  # strip kleur-markup
        if s:
            out.append(s)
    return out


def parse_nutrition(raw_pdp) -> dict:
    """Geef {kcal, eiwit_g, koolhydraten_g, vet_g} per 100 g, of {} als er geen
    voedingswaardetabel is."""
    md = _markdown_strings(raw_pdp)
    start = next((i for i, m in enumerate(md) if "per 100" in m.lower()), None)
    if start is None:
        return {}
    seq = md[start + 1 : start + 30]

    out: dict[str, float] = {}
    for i, m in enumerate(seq):
        key = _LABELS.get(m.strip().lower())
        if not key or key in out:
            continue
        # waarde staat in de eerstvolgende paar regels
        for j in range(i + 1, min(i + 4, len(seq))):
            cand = seq[j]
            if key == "kcal":
                mk = re.search(r"([\d.,\s]+)\s*kcal", cand)
                if mk:
                    v = _num(mk.group(1))
                    if v is not None and 0 <= v <= 950:
                        out["kcal"] = v
                    break
            else:
                if (
                    re.search(r"\d", cand)
                    and "kcal" not in cand.lower()
                    and re.search(r"g\b|g$", cand)
                ):
                    v = _num(cand)
                    if v is not None and 0 <= v <= 100:
                        out[key] = v
                    break
    return out


def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def fetch_nutrition(picnic_api, article_id: str) -> dict:
    """Haal voedingswaarden per 100 g op voor één Picnic-artikel, met schijf-cache.

    Geeft {} terug als het product geen voedingswaardetabel heeft (bv. vers fruit)
    of bij een fout — de rest van het systeem valt dan terug op een schatting.
    """
    cache = _load_cache()
    if article_id in cache:
        return cache[article_id]
    try:
        raw = picnic_api._get(
            f"/pages/product-details-page-root?id={article_id}&show_category_action=true",
            add_picnic_headers=True,
        )
        nutrition = parse_nutrition(raw)
    except Exception as exc:  # netwerk/parse-fout: niet de hele run laten klappen
        log.warning("Voedingswaarden ophalen mislukt voor %s: %s", article_id, exc)
        nutrition = {}
    cache[article_id] = nutrition
    _save_cache(cache)
    return nutrition
