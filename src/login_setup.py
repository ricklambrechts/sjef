"""Interactieve of twee-fasige Picnic-login (incl. 2FA).

Interactief (mens):
    python -m src.login_setup

Twee-fasig (handig als iemand anders de tweede stap doet, bv. een agent):
    python -m src.login_setup --start              # logt in, triggert SMS
    python -m src.login_setup --verify 123456      # voltooit met de SMS-code

In beide gevallen wordt de definitieve auth-token in state/picnic_auth_token.txt
gezet. De pending-token uit fase 1 staat tijdelijk in state/.pending_2fa_token.txt
en wordt na succesvolle verify verwijderd.
"""
from __future__ import annotations

import argparse
import sys

from python_picnic_api2 import PicnicAPI
from python_picnic_api2.session import Picnic2FAError, Picnic2FARequired

from .config import Secrets
from .picnic_client import TOKEN_FILE

PENDING_FILE = TOKEN_FILE.parent / ".pending_2fa_token.txt"


def _save_final_token(api: PicnicAPI) -> None:
    token = api.session.auth_token
    if not token:
        raise SystemExit("Geen auth-token ontvangen na login.")
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()
    print(f"✅ Ingelogd. Token opgeslagen in: {TOKEN_FILE}")


def _phase_start(s: Secrets, channel: str = "SMS") -> None:
    """Fase 1: log in, trigger SMS, sla pending session-token op."""
    api = PicnicAPI(country_code=s.picnic_country_code)
    try:
        api.login(s.picnic_username, s.picnic_password)
    except Picnic2FARequired:
        api.generate_2fa_code(channel=channel)
        pending = api.session.auth_token
        if not pending:
            raise SystemExit("Geen pending-token ontvangen — kan fase 2 niet doen.")
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_FILE.write_text(pending, encoding="utf-8")
        print(f"📨 {channel}-code verstuurd. Voer 'm in met:")
        print(f"   python -m src.login_setup --verify <code>")
        return
    # Geen 2FA nodig → klaar.
    _save_final_token(api)


def _phase_verify(s: Secrets, code: str) -> None:
    """Fase 2: hervat met pending-token, verifieer code, sla definitieve token op."""
    if not PENDING_FILE.exists():
        raise SystemExit("Geen pending sessie gevonden. Draai eerst --start.")
    pending = PENDING_FILE.read_text(encoding="utf-8").strip()
    if not pending:
        raise SystemExit("Pending-token leeg. Draai --start opnieuw.")
    api = PicnicAPI(auth_token=pending, country_code=s.picnic_country_code)
    try:
        api.verify_2fa_code(code)
    except Picnic2FAError as e:
        raise SystemExit(f"❌ 2FA-code afgewezen: {e}")
    _save_final_token(api)


def _phase_interactive(s: Secrets) -> None:
    api = PicnicAPI(country_code=s.picnic_country_code)
    try:
        api.login(s.picnic_username, s.picnic_password)
    except Picnic2FARequired:
        channel = input("2FA vereist. Kanaal [SMS/EMAIL] (default SMS): ").strip() or "SMS"
        api.generate_2fa_code(channel=channel.upper())
        print(f"{channel} verstuurd.")
        code = input("Voer de 2FA-code in: ").strip()
        api.verify_2fa_code(code)
    _save_final_token(api)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Picnic-login + 2FA.")
    parser.add_argument("--start", action="store_true", help="Fase 1: login + trigger SMS")
    parser.add_argument("--verify", metavar="CODE", help="Fase 2: voltooi met de SMS-code")
    parser.add_argument("--channel", default="SMS", choices=["SMS", "EMAIL"])
    args = parser.parse_args(argv)

    s = Secrets.load()
    if not (s.picnic_username and s.picnic_password):
        raise SystemExit("Zet eerst PICNIC_USERNAME en PICNIC_PASSWORD in .env")

    if args.start:
        _phase_start(s, channel=args.channel)
    elif args.verify:
        _phase_verify(s, code=args.verify.strip())
    else:
        _phase_interactive(s)


if __name__ == "__main__":
    main(sys.argv[1:])
