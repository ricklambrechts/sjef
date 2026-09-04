"""Universele voedings-engine: TDEE/macro-berekening + kennislaag.

Geen persoonsgegevens, geen netwerk — pure functies en tekst. Veilig om te
delen. Persoonlijke data leeft in profiles.yaml (git-ignored).

Formules:
  * BMR via Mifflin-St Jeor.
  * TDEE = BMR * activiteitsfactor.
  * Doel-aanpassing: cut -20%, onderhoud 0%, bulk +12%.
  * Eiwit op basis van vetvrije massa indien bekend, anders lichaamsgewicht.
  * Vet ~0.9 g/kg; resterende calorieën -> koolhydraten.
"""

from __future__ import annotations

# Activiteitsfactoren (standaard Mifflin/Harris-Benedict-conventie).
ACTIVITY_FACTORS = {
    "zittend": 1.2,  # weinig beweging, bureauwerk
    "licht": 1.375,  # 1-3x/week sport
    "matig": 1.55,  # 3-5x/week sport
    "actief": 1.725,  # 6-7x/week sport
    "zeer_actief": 1.9,  # zwaar werk of 2x/dag trainen
}

GOAL_KCAL_FACTOR = {"cut": 0.80, "onderhoud": 1.00, "bulk": 1.12}

# Eiwit g per kg vetvrije massa (als bodyfat% bekend is). Ruim voldoende voor
# spierbehoud/-groei; bewust niet extreem hoog (scheelt fors in kosten zonder
# resultaatverlies — onderzoek toont weinig meerwaarde boven ~2.2 g/kg LBM).
PROTEIN_PER_KG_LBM = {"cut": 2.2, "onderhoud": 2.0, "bulk": 2.2}
# Eiwit g per kg lichaamsgewicht (fallback zonder bodyfat%).
PROTEIN_PER_KG_BW = {"cut": 2.0, "onderhoud": 1.6, "bulk": 1.8}

FAT_PER_KG_BW = 0.8  # gezond minimum vet; lager houden geeft ruimte voor
#                      koolhydraten (energie/training) bij een caloriedoel


def _round(value: float, base: int) -> int:
    return int(base * round(value / base))


def bmr_mifflin(sex: str, age: int, height_cm: float, weight_kg: float) -> float:
    """Basaal metabolisme (Mifflin-St Jeor)."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    s = (sex or "").strip().lower()
    if s in ("man", "male", "m"):
        return base + 5
    if s in ("vrouw", "female", "f", "v"):
        return base - 161
    # Onbekend geslacht: gemiddelde van beide correcties.
    return base - 78


def compute_targets(
    *,
    sex: str,
    age: int,
    height_cm: float,
    weight_kg: float,
    goal: str,
    activity: str,
    bodyfat_pct: float | None = None,
    kcal_override: float | None = None,
) -> dict:
    """Bereken dagelijkse calorie- en macrodoelen voor één persoon.

    `kcal_override` zet een vast caloriedoel (i.p.v. de berekende TDEE×doel).
    Handig als iemand bewust strakker wil sturen. Eiwit blijft op niveau, vet op
    het gezonde minimum, en koolhydraten vullen de rest (energie/training).

    Geeft een dict met kcal, eiwit_g, vet_g, koolhydraten_g en de tussenwaarden
    (bmr, tdee) voor transparantie.
    """
    goal = (goal or "onderhoud").strip().lower()
    activity = (activity or "matig").strip().lower()
    if goal not in GOAL_KCAL_FACTOR:
        raise ValueError(
            f"Onbekend doel '{goal}' (kies: {', '.join(GOAL_KCAL_FACTOR)})"
        )
    if activity not in ACTIVITY_FACTORS:
        raise ValueError(
            f"Onbekend activiteitsniveau '{activity}' (kies: {', '.join(ACTIVITY_FACTORS)})"
        )

    bmr = bmr_mifflin(sex, age, height_cm, weight_kg)
    tdee = bmr * ACTIVITY_FACTORS[activity]
    target = float(kcal_override) if kcal_override else tdee * GOAL_KCAL_FACTOR[goal]

    # Veiligheidsbodem: nooit onder BMR plannen (te agressief cutten).
    if target < bmr:
        target = bmr

    # Eiwit
    if bodyfat_pct and 0 < bodyfat_pct < 60:
        lbm = weight_kg * (1 - bodyfat_pct / 100)
        protein_g = PROTEIN_PER_KG_LBM[goal] * lbm
    else:
        protein_g = PROTEIN_PER_KG_BW[goal] * weight_kg

    # Vet
    fat_g = FAT_PER_KG_BW * weight_kg

    # Koolhydraten = restcalorieën
    carb_kcal = target - (protein_g * 4) - (fat_g * 9)
    carb_g = max(0.0, carb_kcal / 4)

    return {
        "kcal": _round(target, 50),
        "eiwit_g": _round(protein_g, 5),
        "vet_g": _round(fat_g, 5),
        "koolhydraten_g": _round(carb_g, 5),
        "bmr": _round(bmr, 10),
        "tdee": _round(tdee, 50),
    }


# ---------------------------------------------------------------------------
# Universele voedingskennis die de planner als richtlijn meekrijgt. Bewust
# generiek en deelbaar; geen persoonsgegevens.
# ---------------------------------------------------------------------------
NUTRITION_PRINCIPLES = """\
VOEDINGSPRINCIPES (pas toe bij het samenstellen van het menu):

Eiwit eerst — bouw elke maaltijd rond een eiwitbron (≥25-40 g per hoofdmaaltijd).
Verdeel eiwit over de dag voor spierbehoud, zeker tijdens een cut.

Volume eten (verzadiging zonder veel calorieën) — gebruik vezel- en waterrijke
producten: groente, salades, soepen, bessen, aardappel, peulvruchten, magere
zuivel zoals kwark/skyr. Belangrijk voor wie cut: vol gevoel bij weinig kcal.

Insulineresistentie / avondsnacken — geef voorrang aan lage glycemische load:
volkoren boven wit, peulvruchten, eiwit + vezel + gezond vet combineren om
bloedsuikerpieken te dempen. Voor avondsnacken: plan bewust slimme, eiwit- en
vezelrijke snacks (kwark + noten + bessen, groente + hummus, eieren, edamame)
zodat trek wordt opgevangen zonder snelle suikers.

Koolhydraat-timing voor een actieve leefstijl — leg de meeste koolhydraten rond
de trainingsmomenten (ervoor/erna) voor energie en herstel; daarbuiten meer
nadruk op eiwit, groente en gezonde vetten. Bij krachttraining 3-5x/week zijn
voldoende koolhydraten nodig voor herstel en prestatie — knijp ze niet te hard af.

Gezonde vetten — onverzadigd (olijfolie, noten, avocado, vette vis) voor
hormoonhuishouding en verzadiging; houd het vet boven het ingestelde minimum.

Praktisch & lekker — gevarieerd, herhaalbaar voor meal-prep, en het mag niet als
straf voelen: gebruik smaakmakers, kruiden en bevredigende texturen.
"""
