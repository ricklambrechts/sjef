import threading
from concurrent.futures import ThreadPoolExecutor

from sjef.planning import jobs


def test_running_job_is_recovered_by_new_manager_and_not_duplicated(
    tmp_path, monkeypatch
):
    launched = []

    class Process:
        pid = 123

        def poll(self):
            return None

    def launch(*args, **kwargs):
        launched.append(args)
        return Process()

    monkeypatch.setattr(jobs.subprocess, "Popen", launch)
    monkeypatch.setattr(jobs, "process_exists", lambda pid: True)
    manager = jobs.PlanningJobs(tmp_path)
    barrier = threading.Barrier(2)

    def start():
        barrier.wait()
        return manager.start({"request": "soep"})["id"]

    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(lambda _: start(), range(2)))
    assert ids[0] == ids[1]
    assert len(launched) == 1
    restored = jobs.PlanningJobs(tmp_path).snapshot()
    assert restored["id"] == ids[0]
    assert restored["status"] == "running"


def test_completed_result_survives_new_manager(tmp_path):
    job = {
        "id": "one",
        "status": "running",
        "stage": "Menu",
        "started_at": 1,
        "pid": 123,
    }
    jobs.save_job(tmp_path, job)
    jobs.update_job(
        tmp_path, "one", status="completed", result={"plan": {"samenvatting": "Soep"}}
    )
    restored = jobs.PlanningJobs(tmp_path).snapshot()
    assert restored["status"] == "completed"
    assert restored["result"]["plan"]["samenvatting"] == "Soep"


def test_dead_worker_is_reported_instead_of_infinite_spinner(tmp_path, monkeypatch):
    jobs.save_job(
        tmp_path, {"id": "one", "status": "running", "started_at": 1, "pid": 999}
    )
    monkeypatch.setattr(jobs, "process_exists", lambda pid: False)
    snapshot = jobs.PlanningJobs(tmp_path).snapshot()
    assert snapshot["status"] == "failed"
    assert "onderbroken" in snapshot["error"]


def test_old_worker_cannot_overwrite_new_job(tmp_path):
    jobs.save_job(tmp_path, {"id": "new", "status": "running"})
    jobs.update_job(tmp_path, "old", status="completed", result={})
    assert jobs.PlanningJobs(tmp_path).read()["id"] == "new"


def test_overdue_job_with_reused_live_pid_does_not_block(tmp_path, monkeypatch):
    jobs.save_job(
        tmp_path, {"id": "old", "status": "running", "started_at": 1, "pid": 123}
    )
    monkeypatch.setattr(jobs, "process_exists", lambda pid: True)
    manager = jobs.PlanningJobs(tmp_path)
    snapshot = manager.snapshot()
    assert snapshot["status"] == "failed"
    assert "tijdslimiet" in snapshot["error"]


def test_real_background_process_persists_its_result(tmp_path, monkeypatch):
    # Vervang alleen het netwerkwerk in het kindproces; gebruik de echte
    # processtart, database-transactie, worker en terugkoppeling.
    real_popen = jobs.subprocess.Popen
    script = """
import sys
from pathlib import Path
from sjef.planning import worker

def build(inputs, progress):
    progress("Menu genereren")
    return {"plan": {"samenvatting": inputs["request"]}}

worker.build = build
sys.exit(worker.run(Path(sys.argv[1]), sys.argv[2]))
"""

    def launch(args, **kwargs):
        assert args[1:3] == ["-m", "sjef.planning.worker"]
        return real_popen([args[0], "-c", script, *args[-2:]], **kwargs)

    monkeypatch.setattr(jobs.subprocess, "Popen", launch)
    manager = jobs.PlanningJobs(tmp_path)
    started = manager.start({"request": "Soep"})
    assert manager._process.wait(timeout=10) == 0
    result = jobs.PlanningJobs(tmp_path).snapshot()
    assert result["id"] == started["id"]
    assert result["status"] == "completed"
    assert result["result"]["plan"]["samenvatting"] == "Soep"
