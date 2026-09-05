"""De vaste volgorde van planningsstappen, gekoppeld aan de opgeslagen fase."""

STEPS = (
    ("Verbinding met Picnic", "Picnic verbinden"),
    ("Weekmenu genereren", "Weekmenu samenstellen"),
    ("Voedingswaarden ophalen", "Voedingswaarden en koolhydraten berekenen"),
    ("Boodschappen zoeken", "Boodschappen zoeken"),
    ("Passende producten", "Producten en aantallen kiezen"),
    ("Budget controleren", "Budget controleren"),
    ("Bezorgmomenten ophalen", "Bezorgmomenten ophalen"),
)


def step_lines(job: dict | None) -> list[str]:
    status = job["status"] if job else None
    stage = job.get("stage", "") if job else ""
    current = next(
        (i for i, (prefix, _) in enumerate(STEPS) if stage.startswith(prefix)), 0
    )
    lines = []
    for i, (_, label) in enumerate(STEPS):
        marker = "○"
        if status == "completed" or (status and i < current):
            marker = "✅"
        elif status and i == current:
            marker = "❌" if status == "failed" else "🔄"
        lines.append(f"{marker} {label}")
    return lines
