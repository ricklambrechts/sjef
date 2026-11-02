import os
import time

from streamlit.testing.v1 import AppTest

from sjef.planning.jobs import save_job


def page(directory):
    app = AppTest.from_string("""
import streamlit as st
from sjef.planning.jobs import PlanningJobs
from sjef.interfaces.plan_status import render_planning_controls
render_planning_controls(PlanningJobs(st.session_state.directory),
    inputs={"config": {}, "request": None, "extra_items": []}, ready=True)
if st.session_state.get("proposal"):
    st.write(st.session_state.proposal["plan"]["samenvatting"])
""")
    app.session_state.directory = directory
    return app.run()


def test_fresh_browser_session_shows_running_job(tmp_path):
    save_job(
        tmp_path,
        {
            "id": "job",
            "status": "running",
            "pid": os.getpid(),
            "stage": "Weekmenu genereren met AI",
            "started_at": time.time() - 65,
        },
    )
    for _ in range(2):
        app = page(tmp_path)
        assert not app.exception
        assert app.button(key="start_planning").disabled
        assert any("Weekmenu samenstellen" in item.value for item in app.markdown)
        assert any("1 min" in caption.value for caption in app.caption)
        text = "\n".join(item.value for item in app.markdown)
        assert "✅ Picnic verbinden" in text
        assert "Stap 2 van 7" in text
        assert "Budget controleren" in text


def test_completed_result_is_loaded_after_refresh(tmp_path):
    save_job(
        tmp_path,
        {
            "id": "job",
            "status": "completed",
            "started_at": time.time(),
            "result": {"plan": {"samenvatting": "Een week soep"}},
        },
    )
    app = page(tmp_path)
    assert not app.exception
    assert app.session_state.proposal["plan"]["samenvatting"] == "Een week soep"
    # Een rerun mag lokale bewerkingen aan het voorstel niet overschrijven.
    app.session_state.proposal = {"plan": {"samenvatting": "Aangepast menu"}}
    app.run()
    assert app.session_state.proposal["plan"]["samenvatting"] == "Aangepast menu"


def test_failed_job_shows_error_and_allows_retry(tmp_path):
    save_job(
        tmp_path,
        {
            "id": "job",
            "status": "failed",
            "started_at": time.time(),
            "stage": "Weekmenu genereren met AI",
            "error": "De tijdslimiet is bereikt",
        },
    )
    app = page(tmp_path)
    assert not app.exception
    assert "tijdslimiet" in app.error[0].value
    assert any("❌ Weekmenu samenstellen" in item.value for item in app.markdown)
    assert not app.button(key="start_planning").disabled
