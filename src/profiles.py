"""Laadt/bewaart het huishouden-profiel (profiles.yaml) en berekent per persoon
de calorie- en macrodoelen via de voedings-engine.

profiles.yaml bevat PERSOONSGEGEVENS en is git-ignored. Een generieke
profiles.example.yaml staat wel in de repo als sjabloon.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import nutrition

ROOT = Path(__file__).resolve().parent.parent
PROFILES_FILE = ROOT / "profiles.yaml"


@dataclass
class Person:
    raw: dict
    targets: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.raw.get("name", "Onbekend")

    @property
    def active(self) -> bool:
        # Default true: bestaande profielen zonder de vlag blijven meedoen.
        return bool(self.raw.get("actief", True))

    @property
    def goal(self) -> str:
        return self.raw.get("goal", "onderhoud")

    @property
    def diet_profile(self) -> str:
        return self.raw.get("diet_profile", "omnivoor")

    @property
    def exclude(self) -> list[str]:
        return [x for x in (self.raw.get("exclude") or []) if x]

    @property
    def prefer(self) -> list[str]:
        return [x for x in (self.raw.get("prefer") or []) if x]

    def compute(self) -> "Person":
        self.targets = nutrition.compute_targets(
            sex=self.raw.get("sex", ""),
            age=int(self.raw.get("age", 30)),
            height_cm=float(self.raw.get("height_cm", 175)),
            weight_kg=float(self.raw.get("weight_kg", 75)),
            goal=self.goal,
            activity=self.raw.get("activity", "matig"),
            bodyfat_pct=self.raw.get("bodyfat_pct"),
            kcal_override=self.raw.get("kcal_override"),
        )
        return self

    def summary_line(self) -> str:
        t = self.targets
        bf = f", {self.raw['bodyfat_pct']}% vet" if self.raw.get("bodyfat_pct") else ""
        training = self.raw.get("training") or "—"
        notes = self.raw.get("notes") or "—"
        excl = ", ".join(self.exclude) or "geen"
        pref = ", ".join(self.prefer) or "geen"
        return (
            f"{self.name} — {self.raw.get('sex','?')}, {self.raw.get('age','?')} jr, "
            f"{self.raw.get('height_cm','?')} cm, {self.raw.get('weight_kg','?')} kg{bf}; "
            f"doel: {self.goal} ({self.raw.get('activity','matig')}).\n"
            f"  Dagdoel: ~{t['kcal']} kcal, {t['eiwit_g']} g eiwit, "
            f"{t['vet_g']} g vet, {t['koolhydraten_g']} g koolhydraten.\n"
            f"  Dieet: {self.diet_profile}; uitsluiten: {excl}; voorkeur: {pref}.\n"
            f"  Training: {training}. Bijzonderheden: {notes}."
        )


@dataclass
class Profiles:
    raw: dict

    @classmethod
    def load(cls, path: Path | None = None) -> "Profiles | None":
        """Geeft None terug als profiles.yaml niet bestaat (legacy-modus)."""
        path = path or PROFILES_FILE
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not data.get("persons"):
            return None
        return cls(raw=data)

    @staticmethod
    def save(profiles_dict: dict, path: Path | None = None) -> Path:
        path = path or PROFILES_FILE
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(profiles_dict, fh, allow_unicode=True, sort_keys=False)
        return path

    @property
    def days(self) -> int:
        return int(self.raw.get("household", {}).get("days", 7))

    @property
    def shared_meals(self) -> bool:
        return bool(self.raw.get("household", {}).get("shared_meals", True))

    @property
    def household_notes(self) -> str:
        return self.raw.get("household", {}).get("notes", "") or ""

    @property
    def all_persons(self) -> list[Person]:
        """Alle personen, inclusief inactieve (voor de instellingen-weergave)."""
        return [Person(raw=p).compute() for p in self.raw.get("persons", [])]

    @property
    def persons(self) -> list[Person]:
        """Alleen ACTIEVE personen — deze tellen mee in plan/macro's/boodschappen."""
        return [p for p in self.all_persons if p.active]

    def planner_context(self) -> dict:
        """Bouwt de context die de planner nodig heeft (alleen actieve personen)."""
        persons = self.persons
        daily_kcal = sum(p.targets["kcal"] for p in persons)
        daily_protein = sum(p.targets["eiwit_g"] for p in persons)
        return {
            "days": self.days,
            "shared_meals": self.shared_meals,
            "household_notes": self.household_notes,
            "weekly_need": {
                "kcal": daily_kcal * self.days,
                "eiwit_g": daily_protein * self.days,
                "daily_kcal": daily_kcal,
                "daily_eiwit_g": daily_protein,
            },
            "persons": [
                {
                    "name": p.name,
                    "goal": p.goal,
                    "diet_profile": p.diet_profile,
                    "exclude": p.exclude,
                    "prefer": p.prefer,
                    "targets": p.targets,
                    "summary": p.summary_line(),
                }
                for p in persons
            ],
        }
