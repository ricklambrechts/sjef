"""Inloggen met ChatGPT vanuit de terminal."""

from __future__ import annotations

import sys


def ai_login(*, device_auth: bool = False) -> int:
    from sjef.config import Secrets
    from sjef.llm.factory import create_auth

    login = None
    try:
        login = create_auth(Secrets.load()).start_login(device_auth=device_auth)
        print(
            f"Open deze link en log in met je ChatGPT-account:\n{login.url}", flush=True
        )
        if login.user_code:
            print(f"Apparaatcode: {login.user_code}", flush=True)
        if not login.wait(timeout=300):
            print("Inlogtijd verstreken. Probeer opnieuw.", file=sys.stderr)
            return 1
        print("Ingelogd met ChatGPT. Je kunt Sjef nu gebruiken.")
        return 0
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if login:
            login.close()
