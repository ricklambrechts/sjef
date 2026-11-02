"""Voortgang en hervatten van een planningstaak in het dashboard."""

import time
from html import escape

import streamlit as st

from sjef.config import ROOT
from sjef.planning.jobs import PlanningJobs
from sjef.planning.progress import STEPS, step_lines


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
    if not job:
        return
    current = next(
        (
            i
            for i, (prefix, _) in enumerate(STEPS)
            if job.get("stage", "").startswith(prefix)
        ),
        0,
    )
    completed = job["status"] == "completed"
    failed = job["status"] == "failed"
    title = "Je plan is klaar" if completed else STEPS[current][1]
    subtitle = (
        "Alle stappen afgerond" if completed else f"Stap {current + 1} van {len(STEPS)}"
    )
    segments = []
    for i, (_, label) in enumerate(STEPS):
        state = "done" if completed or i < current else "pending"
        if not completed and i == current:
            state = "failed" if failed else "active"
        segments.append(f'<span class="{state}" title="{escape(label)}"></span>')
    with st.container(border=True):
        st.markdown(
            "<style>"
            ".sjef-progress-title {font-size:1.15rem;font-weight:650;color:#243d2e;}"
            ".sjef-progress-subtitle {color:#626e65;font-size:.85rem;margin-bottom:.3rem;}"
            ".sjef-progress {display:flex;gap:6px;margin:14px 0;}"
            ".sjef-progress span {flex:1;height:6px;border-radius:4px;background:#e9e7df;}"
            ".sjef-progress .done {background:#397751;}"
            ".sjef-progress .active {background:#be8c2d;}"
            ".sjef-progress .failed {background:#b54235;}"
            "</style>"
            f'<div role="status"><div class="sjef-progress-subtitle">{subtitle}</div>'
            f'<div class="sjef-progress-title">{escape(title)}</div></div>'
            f'<div class="sjef-progress" aria-hidden="true">{"".join(segments)}</div>',
            unsafe_allow_html=True,
        )
        if running:
            elapsed = max(0, int(time.time() - job["started_at"]))
            st.caption(f"Bezig sinds {elapsed // 60} min {elapsed % 60:02d} sec")
            st.caption("Je kunt de pagina herladen. Sjef werkt verder.")
        with st.expander("Details"):
            for line in step_lines(job):
                st.markdown(line)
            if running:
                st.caption(
                    "De volledige planning heeft een tijdslimiet van 20 minuten."
                )
    if job["status"] == "failed":
        st.error(job["error"])
        if job.get("stage"):
            st.caption(f"Laatste stap: {job['stage']}")
    elif job["status"] == "completed":
        if st.session_state.get("loaded_planning_job") != job["id"]:
            st.session_state.proposal = job["result"]
            st.session_state.loaded_planning_job = job["id"]
            st.session_state.pop("order_result", None)
            st.rerun()
