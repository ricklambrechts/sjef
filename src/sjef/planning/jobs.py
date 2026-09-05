"""Eén planningstaak per persoonlijke installatie, onafhankelijk van de browser."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sjef.config import ROOT

TERMINAL = {"completed", "failed"}
MAX_SECONDS = 20 * 60


def overdue(job: dict) -> bool:
    # Herstel ook als de worker/watchdog weg is en het OS het PID hergebruikt.
    return time.time() - job["started_at"] > MAX_SECONDS + 30


@contextmanager
def database(directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(directory / "planning.sqlite", timeout=10)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS job (slot INTEGER PRIMARY KEY, data TEXT NOT NULL)"
        )
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    finally:
        connection.close()


def _read(connection):
    row = connection.execute("SELECT data FROM job WHERE slot=1").fetchone()
    return json.loads(row[0]) if row else None


def _save(connection, job):
    connection.execute(
        "INSERT OR REPLACE INTO job VALUES (1, ?)",
        (json.dumps(job, ensure_ascii=False),),
    )


def save_job(directory: Path, job: dict):
    with database(directory) as connection:
        _save(connection, job)


def update_job(directory: Path, job_id: str, **changes):
    with database(directory) as connection:
        job = _read(connection)
        if job and job["id"] == job_id and job["status"] not in TERMINAL:
            job.update(changes, updated_at=time.time())
            _save(connection, job)


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class PlanningJobs:
    def __init__(self, directory: Path):
        self.directory = directory
        self._lock = threading.Lock()
        self._process = None

    def read(self) -> dict | None:
        with database(self.directory) as connection:
            return _read(connection)

    def snapshot(self) -> dict | None:
        with self._lock:
            if self._process is not None:
                self._process.poll()  # Reap een beëindigd kindproces.
            job = self.read()
            if (
                job
                and job["status"] == "running"
                and (overdue(job) or not process_exists(job["pid"]))
            ):
                update_job(
                    self.directory,
                    job["id"],
                    status="failed",
                    error="Het plannen is onderbroken of heeft de tijdslimiet bereikt. Je kunt een nieuw plan starten.",
                )
                job = self.read()
            return job

    def start(self, inputs: dict) -> dict:
        with self._lock, database(self.directory) as connection:
            if self._process is not None:
                self._process.poll()
            previous = _read(connection)
            if (
                previous
                and previous["status"] == "running"
                and not overdue(previous)
                and process_exists(previous["pid"])
            ):
                return previous
            job = {
                "id": uuid4().hex,
                "status": "running",
                "stage": "Planning starten",
                "started_at": time.time(),
                "updated_at": time.time(),
                "inputs": inputs,
                "result": None,
                "error": None,
            }
            try:
                # De worker wacht op deze database-transactie voordat hij begint.
                with (self.directory / "planning-worker.log").open(
                    "w", encoding="utf-8"
                ) as log:
                    self._process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "sjef.planning.worker",
                            str(self.directory.resolve()),
                            job["id"],
                        ],
                        cwd=ROOT,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
                job["pid"] = self._process.pid
            except OSError:
                job.update(
                    status="failed",
                    error="De planning kon niet worden gestart. Probeer opnieuw.",
                )
            _save(connection, job)
            return job
