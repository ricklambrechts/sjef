import os

from sjef.planning import jobs, worker


def setup_job(tmp_path):
    jobs.save_job(
        tmp_path,
        {
            "id": "job",
            "status": "running",
            "pid": os.getpid(),
            "inputs": {"config": {}, "request": "soep", "extra_items": []},
        },
    )


def test_worker_persists_progress_and_result(tmp_path, monkeypatch):
    setup_job(tmp_path)
    stages = []

    def build(inputs, progress):
        progress("Menu maken")
        stages.append(jobs.PlanningJobs(tmp_path).read()["stage"])
        return {"plan": {"samenvatting": "Soep"}}

    monkeypatch.setattr(worker, "build", build)
    assert worker.run(tmp_path, "job") == 0
    assert stages == ["Menu maken"]
    result = jobs.PlanningJobs(tmp_path).snapshot()
    assert result["status"] == "completed"
    assert result["result"]["plan"]["samenvatting"] == "Soep"


def test_worker_persists_failure(tmp_path, monkeypatch):
    setup_job(tmp_path)

    def build(inputs, progress):
        raise RuntimeError("Je ChatGPT/Codex-gebruikslimiet is bereikt.")

    monkeypatch.setattr(worker, "build", build)
    assert worker.run(tmp_path, "job") == 1
    result = jobs.PlanningJobs(tmp_path).snapshot()
    assert result["status"] == "failed"
    assert "gebruikslimiet" in result["error"]


def test_timeout_persists_error_before_stopping_worker(tmp_path, monkeypatch):
    setup_job(tmp_path)
    stopped = []
    monkeypatch.setattr(worker, "stop_process", lambda: stopped.append(True))
    worker.expire(tmp_path, "job")
    assert jobs.PlanningJobs(tmp_path).read()["status"] == "failed"
    assert "tijdslimiet" in jobs.PlanningJobs(tmp_path).read()["error"]
    assert stopped == [True]
    jobs.update_job(tmp_path, "job", status="completed", result={})
    assert jobs.PlanningJobs(tmp_path).read()["status"] == "failed"
