"""Laadt configuratie (config.yaml) en geheimen (.env) in een typed object."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


@dataclass
class Secrets:
    """Geheimen uit .env. Worden nooit gelogd."""

    picnic_username: str | None
    picnic_password: str | None
    picnic_country_code: str
    picnic_auth_token: str | None
    anthropic_api_key: str | None
    planner_model: str
    telegram_bot_token: str | None
    telegram_allowed_user_id: int | None
    dry_run: bool

    @classmethod
    def load(cls) -> Secrets:
        load_dotenv(ROOT / ".env")
        allowed = os.getenv("TELEGRAM_ALLOWED_USER_ID")
        return cls(
            picnic_username=os.getenv("PICNIC_USERNAME"),
            picnic_password=os.getenv("PICNIC_PASSWORD"),
            picnic_country_code=os.getenv("PICNIC_COUNTRY_CODE", "NL"),
            picnic_auth_token=os.getenv("PICNIC_AUTH_TOKEN") or None,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            planner_model=os.getenv("PLANNER_MODEL", "claude-sonnet-4-6"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_allowed_user_id=int(allowed)
            if allowed and allowed.strip()
            else None,
            dry_run=_as_bool(os.getenv("DRY_RUN"), default=True),
        )


@dataclass
class Config:
    """Niet-geheime voorkeuren uit config.yaml."""

    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or (ROOT / "config.yaml")
        with open(path, encoding="utf-8") as fh:
            return cls(raw=yaml.safe_load(fh) or {})

    def save(self, path: Path | None = None) -> Path:
        """Schrijf de huidige config terug naar config.yaml.

        Let op: YAML-commentaar gaat hierbij verloren (we dumpen de waarden).
        """
        path = path or (ROOT / "config.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self.raw, fh, allow_unicode=True, sort_keys=False)
        return path

    def dry_run(self, env_default: bool = True) -> bool:
        """Effectieve dry-run-stand. Komt uit config.yaml (safety.dry_run) als die
        gezet is; anders de .env-waarde (env_default). Zo kunnen dashboard én bot
        dezelfde schakelaar gebruiken, maar blijft .env een veilige fallback."""
        val = self.raw.get("safety", {}).get("dry_run")
        return env_default if val is None else bool(val)

    def set_dry_run(self, value: bool) -> None:
        self.raw.setdefault("safety", {})["dry_run"] = bool(value)

    # -- handige accessors --
    @property
    def people(self) -> int:
        return int(self.raw.get("household", {}).get("people", 1))

    @property
    def days(self) -> int:
        return int(self.raw.get("household", {}).get("days", 7))

    @property
    def diet_profile(self) -> str:
        return self.raw.get("diet", {}).get("profile", "omnivoor")

    @property
    def diet_exclude(self) -> list[str]:
        return [x for x in self.raw.get("diet", {}).get("exclude", []) if x]

    @property
    def diet_prefer(self) -> list[str]:
        return [x for x in self.raw.get("diet", {}).get("prefer", []) if x]

    @property
    def macro_modes(self) -> dict:
        return self.raw.get("macro_modes", {})

    @property
    def default_mode(self) -> str:
        return self.raw.get("weekly", {}).get("default_mode", "onderhoud")

    @property
    def staples(self) -> dict[str, int]:
        return self.raw.get("weekly", {}).get("staples", {}) or {}

    @property
    def _auto(self) -> dict:
        return self.raw.get("weekly", {}).get("auto", {}) or {}

    @property
    def auto_enabled(self) -> bool:
        return bool(self._auto.get("enabled", False))

    @property
    def auto_weekday(self) -> int:
        return int(self._auto.get("weekday", 5))

    @property
    def auto_time(self) -> tuple[int, int]:
        """(uur, minuut) uit 'HH:MM'."""
        raw = str(self._auto.get("time", "09:00"))
        try:
            h, m = raw.split(":")
            return int(h), int(m)
        except ValueError:
            return 9, 0

    @property
    def auto_mode(self) -> str:
        return self._auto.get("mode") or self.default_mode

    @property
    def auto_request(self) -> str | None:
        req = (self._auto.get("request") or "").strip()
        return req or None

    @property
    def max_order_eur(self) -> float:
        return float(self.raw.get("limits", {}).get("max_order_eur", 120))

    @property
    def max_item_eur(self) -> float:
        return float(self.raw.get("limits", {}).get("max_item_eur", 25))

    @property
    def budget_target_eur(self) -> float | None:
        v = self.raw.get("budget", {}).get("target_eur")
        return float(v) if v else None

    @property
    def cost_conscious(self) -> bool:
        return bool(self.raw.get("budget", {}).get("cost_conscious", False))

    @property
    def preferred_weekday(self):
        return self.raw.get("picnic", {}).get("preferred_weekday")

    def macros_for(self, mode: str | None) -> dict:
        """Geeft {kcal_per_day, protein_per_day} voor de gekozen mode."""
        mode = (mode or self.default_mode).lower()
        modes = self.macro_modes
        if mode not in modes:
            raise KeyError(
                f"Onbekende macro-mode '{mode}'. Beschikbaar: {', '.join(modes)}"
            )
        return modes[mode]
