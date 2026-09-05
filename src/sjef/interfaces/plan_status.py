"""Voortgang en hervatten van een planningstaak in het dashboard."""

import time

import streamlit as st

from sjef.config import ROOT
from sjef.planning.jobs import PlanningJobs
from sjef.planning.progress import step_lines


@st.cache_resource
def planning_jobs() -> PlanningJobs:
    return PlanningJobs(ROOT / "state")


@st.fragment(run_every="2s")
def render_planning_controls(manager: PlanningJobs, *, inputs: dict, ready: bool):
    job = manager.snapshot()
    running = bool(job and job["status"] == "running")
    st.session_state.planning_running = running
    if st.button(
        "🍳 Sjef, maak een plan",
        type="primary",
        key="start_planning",
        disabled=not ready or running,
    ):
        manager.start(inputs)
        st.session_state.pop("proposal", None)
        st.session_state.pop("order_result", None)
        st.rerun()
    for line in step_lines(job):
        st.markdown(line)
    if not job:
        return
    if running:
        elapsed = max(0, int(time.time() - job["started_at"]))
        with st.status(job["stage"], state="running", expanded=True):
            st.caption(f"Bezig sinds {elapsed // 60} min {elapsed % 60:02d} sec")
            st.write(
                "Je kunt de pagina herladen. Sjef werkt verder en toont hier het resultaat zodra het klaar is."
            )
            st.caption("De volledige planning heeft een tijdslimiet van 20 minuten.")
    elif job["status"] == "failed":
        st.error(job["error"])
        if job.get("stage"):
            st.caption(f"Laatste stap: {job['stage']}")
    elif job["status"] == "completed":
        if st.session_state.get("loaded_planning_job") != job["id"]:
            st.session_state.proposal = job["result"]
            st.session_state.loaded_planning_job = job["id"]
            st.session_state.pop("order_result", None)
            st.rerun()
        st.success("Je plan is klaar.")
