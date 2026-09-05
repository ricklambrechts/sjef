"""Los proces voor plannen: overleeft een browserrefresh en heeft een tijdslimiet."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from pathlib import Path

from sjef.planning.jobs import MAX_SECONDS, PlanningJobs, update_job


def stop_process():
    # Alleen de door PlanningJobs gestarte, eigen procesgroep beëindigen.
    if os.name == "posix" and os.getpgrp() == os.getpid():
        os.killpg(os.getpgrp(), signal.SIGTERM)
    os._exit(1)


def expire(directory: Path, job_id: str):
    update_job(
        directory,
        job_id,
        status="failed",
        error="Het plannen heeft de tijdslimiet van 20 minuten bereikt. Probeer een kleiner menu.",
    )
    stop_process()


def build(inputs: dict, progress) -> dict:
    from sjef.config import Config, Secrets
    from sjef.picnic.picnic_client import PicnicClient
    from sjef.planning.orchestrator import build_proposal

    progress("Verbinding met Picnic controleren")
    secrets = Secrets.load()
    picnic = PicnicClient(
        username=secrets.picnic_username,
        password=secrets.picnic_password,
        country_code=secrets.picnic_country_code,
        auth_token=secrets.picnic_auth_token,
        dry_run=True,
    )
    return build_proposal(
        Config(raw=inputs["config"]),
        secrets,
        picnic,
        mode=None,
        request=inputs.get("request"),
        extra_items=inputs.get("extra_items"),
        progress=progress,
    )


def run(directory: Path, job_id: str) -> int:
    # Deze eerste transactie wacht totdat de starter de taak heeft opgeslagen.
    update_job(directory, job_id, stage="Planning starten")
    job = PlanningJobs(directory).read()
    if not job or job["id"] != job_id or job["status"] != "running":
        return 1
    timer = threading.Timer(MAX_SECONDS, expire, args=(directory, job_id))
    timer.daemon = True
    timer.start()
    try:
        result = build(
            job["inputs"], lambda stage: update_job(directory, job_id, stage=stage)
        )
        update_job(
            directory, job_id, status="completed", stage="Plan klaar", result=result
        )
        return 0
    except Exception as exc:
        logging.exception("Planning mislukt")
        update_job(
            directory,
            job_id,
            status="failed",
            error=str(exc) or "Het plannen is mislukt. Probeer opnieuw.",
        )
        return 1
    finally:
        timer.cancel()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    sys.exit(run(Path(sys.argv[1]), sys.argv[2]))
