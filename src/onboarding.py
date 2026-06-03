"""Pure onboarding-engine voor het opbouwen van een huishouden-profiel.

Los van Telegram zodat het volledig offline testbaar is. De bot is een dunne
wrapper: hij toont `current_question()` en geeft antwoorden door aan `submit()`.

Flow: per persoon een reeks velden; daarna 'nog iemand?'; tot slot huishoud-
brede vragen (dagen, gedeelde gerechten, notities). Resultaat is een dict dat
1-op-1 in profiles.yaml past.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .nutrition import ACTIVITY_FACTORS, GOAL_KCAL_FACTOR


@dataclass
class Field:
    key: str
    question: str
    kind: str = "text"          # text | int | float | choice | bool
    choices: list[str] | None = None
    optional: bool = False
    help: str = ""


# Velden per persoon, in volgorde.
PERSON_FIELDS: list[Field] = [
    Field("name", "Wat is de naam van deze persoon?"),
    Field("sex", "Geslacht?", kind="choice", choices=["man", "vrouw"]),
    Field("age", "Leeftijd (jaren)?", kind="int"),
    Field("height_cm", "Lengte in cm?", kind="float"),
    Field("weight_kg", "Gewicht in kg?", kind="float"),
    Field(
        "bodyfat_pct",
        "Lichaamsvetpercentage? (schatting mag, of typ 'skip')",
        kind="float",
        optional=True,
    ),
    Field("goal", "Doel?", kind="choice", choices=list(GOAL_KCAL_FACTOR.keys())),
    Field(
        "activity",
        "Activiteitsniveau?",
        kind="choice",
        choices=list(ACTIVITY_FACTORS.keys()),
        help="zittend=weinig · licht=1-3x/wk · matig=3-5x/wk · actief=6-7x/wk · zeer_actief=2x/dag",
    ),
    Field(
        "training",
        "Trainingsschema? (vrije tekst, bv. 'fitness 3-4x, soms hardlopen')",
        optional=True,
    ),
    Field(
        "diet_profile",
        "Dieetprofiel?",
        kind="choice",
        choices=["omnivoor", "vegetarisch", "pescotarisch", "veganistisch"],
    ),
    Field(
        "exclude",
        "Dingen die NOOIT in het menu mogen? (komma-gescheiden, of 'geen')",
        optional=True,
    ),
    Field(
        "prefer",
        "Voorkeuren / dingen die je graag eet? (komma-gescheiden, of 'geen')",
        optional=True,
    ),
    Field(
        "notes",
        "Bijzonderheden? (bv. insulineresistent, snackt 's avonds — of 'skip')",
        optional=True,
    ),
]

# Huishoud-brede velden, na alle personen.
HOUSEHOLD_FIELDS: list[Field] = [
    Field("days", "Voor hoeveel dagen moeten de boodschappen zijn?", kind="int"),
    Field(
        "shared_meals",
        "Eten jullie dezelfde gerechten (andere porties)?",
        kind="bool",
        choices=["ja", "nee"],
    ),
    Field(
        "notes",
        "Huishoud-brede opmerkingen voor de planner? (of 'skip')",
        optional=True,
    ),
]

# Speciaal veld tussen personen door.
_ANOTHER = Field(
    "_another",
    "Nog een persoon toevoegen?",
    kind="bool",
    choices=["ja", "nee"],
)


def _parse(field: Field, raw: str):
    """Valideer en converteer een antwoord. Geeft (waarde, foutmelding-of-None)."""
    text = (raw or "").strip()
    low = text.lower()

    if field.optional and low in ("skip", "geen", "nee", "-", ""):
        if field.key in ("exclude", "prefer"):
            return [], None
        return None, None

    if not text:
        return None, "Dit veld is verplicht. Geef een antwoord."

    if field.kind == "int":
        try:
            v = int(round(float(text.replace(",", "."))))
        except ValueError:
            return None, "Geef een geheel getal."
        if v <= 0:
            return None, "Geef een positief getal."
        return v, None

    if field.kind == "float":
        try:
            v = float(text.replace(",", "."))
        except ValueError:
            return None, "Geef een getal."
        if v <= 0:
            return None, "Geef een positief getal."
        return v, None

    if field.kind == "choice":
        if low not in [c.lower() for c in field.choices]:
            return None, f"Kies uit: {', '.join(field.choices)}."
        # Geef de canonieke variant terug.
        return next(c for c in field.choices if c.lower() == low), None

    if field.kind == "bool":
        if low in ("ja", "j", "yes", "y", "true"):
            return True, None
        if low in ("nee", "n", "no", "false"):
            return False, None
        return None, "Antwoord met ja of nee."

    if field.key in ("exclude", "prefer"):
        return [p.strip() for p in text.split(",") if p.strip()], None

    return text, None


@dataclass
class OnboardingFlow:
    """Statefulle, maar Telegram-onafhankelijke onboarding."""

    persons: list[dict] = field(default_factory=list)
    household: dict = field(default_factory=dict)
    _current: dict = field(default_factory=dict)
    _stage: str = "person"     # person | another | household
    _idx: int = 0
    done: bool = False

    # ---- vragen ----
    def current_field(self) -> Field | None:
        if self.done:
            return None
        if self._stage == "person":
            return PERSON_FIELDS[self._idx]
        if self._stage == "another":
            return _ANOTHER
        if self._stage == "household":
            return HOUSEHOLD_FIELDS[self._idx]
        return None

    def current_question(self) -> str | None:
        f = self.current_field()
        if not f:
            return None
        q = f.question
        if f.help:
            q += f"\n({f.help})"
        if f.kind == "choice":
            q += f"\nOpties: {', '.join(f.choices)}"
        person_no = len(self.persons) + 1
        if self._stage == "person":
            q = f"👤 Persoon {person_no} — {q}"
        return q

    # ---- antwoord verwerken ----
    def submit(self, raw: str) -> tuple[bool, str | None]:
        """Verwerk een antwoord. Geeft (ok, foutmelding-of-None).

        Bij ok=True is de flow doorgeschoven; check daarna current_question()
        en .done.
        """
        f = self.current_field()
        if f is None:
            return False, "Onboarding is al klaar."

        value, err = _parse(f, raw)
        if err:
            return False, err

        if self._stage == "person":
            self._current[f.key] = value
            self._idx += 1
            if self._idx >= len(PERSON_FIELDS):
                self.persons.append(self._current)
                self._current = {}
                self._idx = 0
                self._stage = "another"
            return True, None

        if self._stage == "another":
            if value:  # ja -> nieuwe persoon
                self._stage = "person"
                self._idx = 0
            else:       # nee -> huishoud-vragen
                self._stage = "household"
                self._idx = 0
            return True, None

        if self._stage == "household":
            self.household[f.key] = value
            self._idx += 1
            if self._idx >= len(HOUSEHOLD_FIELDS):
                self.done = True
            return True, None

        return False, "Onbekende fase."

    # ---- resultaat ----
    def to_profiles_dict(self) -> dict:
        if not self.done:
            raise RuntimeError("Onboarding nog niet afgerond.")
        return {
            "household": {
                "days": self.household.get("days", 7),
                "shared_meals": self.household.get("shared_meals", True),
                "notes": self.household.get("notes") or "",
            },
            "persons": self.persons,
        }
