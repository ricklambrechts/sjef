"""Entrypoint voor de supermarkt-agent.

uv run sjef bot              # start de Telegram-bot
uv run sjef plan [modus]     # bouw een voorstel in de terminal (geen bestelling)
uv run sjef selftest         # offline tests van de pure logica (geen credentials nodig)
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from sjef.config import ROOT
from sjef.selftest import run_selftest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("run")


def run_bot() -> None:
    from sjef.config import Config, Secrets
    from sjef.interfaces.telegram_bot import build_application

    # state/ moet bestaan voor token-persistentie en (via launchd) logbestanden.
    (ROOT / "state").mkdir(exist_ok=True)

    config = Config.load()
    secrets = Secrets.load()
    app = build_application(config, secrets)
    log.info("Bot start (dry_run=%s)…", secrets.dry_run)
    app.run_polling()


def run_plan(mode: str | None) -> None:
    from sjef.config import Config, Secrets
    from sjef.interfaces import formatting
    from sjef.picnic.picnic_client import PicnicClient
    from sjef.planning import orchestrator

    config = Config.load()
    secrets = Secrets.load()
    picnic = PicnicClient(
        username=secrets.picnic_username,
        password=secrets.picnic_password,
        country_code=secrets.picnic_country_code,
        auth_token=secrets.picnic_auth_token,
        dry_run=secrets.dry_run,
    )
    proposal = orchestrator.build_proposal(config, secrets, picnic, mode)
    print("\n" + formatting.format_proposal(proposal))
    print("\n(Alleen voorstel — er is niets besteld. Gebruik de bot om te bestellen.)")


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="Sjef: weekmenu's en boodschappen.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("dashboard", help="Start het web-dashboard", add_help=False)
    commands.add_parser(
        "picnic-login", help="Inloggen bij Picnic met 2FA", add_help=False
    )
    commands.add_parser("bot", help="Start de Telegram-bot")
    login_parser = commands.add_parser(
        "ai-login", help="Inloggen met je ChatGPT-account"
    )
    login_parser.add_argument(
        "--device-auth", action="store_true", help="Inloggen met een apparaatcode"
    )
    plan_parser = commands.add_parser(
        "plan", help="Maak een voorstel zonder te bestellen"
    )
    plan_parser.add_argument("mode", nargs="?", help="Bijvoorbeeld cut of bulk")
    commands.add_parser("selftest", help="Voer de offline zelftests uit")
    # Streamlit verwerkt de dashboardopties, inclusief --help.
    if argv[:1] == ["dashboard"]:
        return dashboard(argv[1:])
    if argv[:1] == ["picnic-login"]:
        from sjef.picnic.login_setup import main as login

        return login(argv[1:])
    args = parser.parse_args(argv)
    if args.command == "ai-login":
        from sjef.interfaces.ai_login_cli import ai_login

        return ai_login(device_auth=args.device_auth)
    if args.command == "bot":
        return run_bot()
    if args.command == "plan":
        return run_plan(args.mode)
    if args.command == "selftest":
        return run_selftest()
    parser.print_help()
    return 0


def dashboard(argv: list[str]) -> int:
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(Path(__file__).parent / "interfaces" / "dashboard.py"),
            *argv,
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
