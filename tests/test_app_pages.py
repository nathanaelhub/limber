"""T035/T044 — every store-backed web page renders headlessly without an exception.

Uses Streamlit's AppTest, so no browser, camera, or model is needed. The live-session page is
excluded because it opens a WebRTC stream.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.ptlog.models import ExerciseSetInfo, FormEvent, RepEvent
from src.ptlog.store import SessionStore
from tests.fixtures.golden.sequence import FixedClock

REPO_ROOT = Path(__file__).resolve().parent.parent
APP = REPO_ROOT / "interfaces" / "app.py"
KNEE = ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0)


@pytest.fixture
def seeded_env(tmp_db, monkeypatch):
    monkeypatch.setenv("PTASSIST_DB", str(tmp_db))
    clock = FixedClock(datetime.now() - timedelta(days=3))
    with SessionStore(tmp_db, clock=clock).open() as store:
        store.add_patient("P-017", label="Post-op knee")
        for day in (3, 1):
            base = datetime.now() - timedelta(days=day)
            clock.set(base)
            sid = store.start_session("P-017", "video", "clip.mp4")
            set_id = store.open_set(sid, KNEE)
            for n in range(1, 4):
                store.add_rep(set_id, RepEvent(n, 10.2, 88.6, 78.4 + day, 3.1, 90.0 + n,
                                               (base + timedelta(seconds=n)).isoformat(), 60 * n))
            store.add_form_event(set_id, FormEvent("warning", "warning", "Keep your back straight",
                                                   (base + timedelta(seconds=5)).isoformat(), 150))
            clock.set(base + timedelta(seconds=10))
            store.end_session(sid)
    return tmp_db


PAGES = ["home", "patients", "sessions", "obs_logs", "review", "tracker", "video", "learn"]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(seeded_env, page):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = page
    at.session_state["patient_id"] = "P-017"
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_sessions_page_shows_event_log_and_exports(seeded_env):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "sessions"
    at.session_state["patient_id"] = "P-017"
    at.run()
    assert not at.exception
    code_blocks = [c.value for c in at.code]
    assert any("REP 1 | ROM" in c and "SESSION END" in c for c in code_blocks)
    labels = {b.label for b in at.get("download_button")}
    assert {"PTA-Log text", "Observation JSON", "CSV report", "Session text log"} <= labels


def test_patients_page_lists_registry(seeded_env):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "patients"
    at.run()
    assert not at.exception
    frames = at.dataframe
    assert frames and "P-017" in frames[0].value["ID"].tolist()


def test_sidebar_patient_selector_lists_store_patients(seeded_env):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "home"
    at.run()
    assert not at.exception
    sel = at.sidebar.selectbox[0]
    assert [o.split(" · ")[0] for o in sel.options] == ["unassigned", "P-017"]


def _review_page(seeded_env, section):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "review"
    at.session_state["patient_id"] = "P-017"
    at.session_state["review_tab"] = section
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_review_page_trends_tab(seeded_env):
    at = _review_page(seeded_env, "Trends")
    frames = at.dataframe
    assert frames and "avg ROM (degrees)" in list(frames[0].value.columns)


def test_review_page_session_tab(seeded_env):
    at = _review_page(seeded_env, "Session review")
    options = [tuple(s.options) for s in at.selectbox]
    assert ("continue", "progress", "regress", "hold") in options
    assert any("REVIEW" in m.value for m in at.markdown)


def test_review_page_flags_tab(seeded_env):
    at = _review_page(seeded_env, "Flags")
    assert at.warning or at.success


def test_review_page_settings_gap_input(seeded_env):
    at = _review_page(seeded_env, "Goals & settings")
    assert any("gap" in n.label.lower() for n in at.number_input)


def test_review_page_compare_tab(seeded_env):
    at = _review_page(seeded_env, "Compare")
    session_selects = [s for s in at.selectbox if s.label.lower().startswith("session")]
    assert len(session_selects) >= 2
    assert at.dataframe


def test_review_page_goal_form(seeded_env):
    at = _review_page(seeded_env, "Goals & settings")
    labels = [n.label.lower() for n in at.number_input]
    assert any("rom" in l for l in labels) and any("reps" in l for l in labels)
    buttons = {b.label for b in at.button}
    assert "Set goal" in buttons and "Clear goal" in buttons


def test_review_page_export_tab(seeded_env):
    at = _review_page(seeded_env, "Export")
    labels = {b.label for b in at.get("download_button")}
    assert {"Review report (text)", "Review data (CSV)"} <= labels


def _tracker_page(seeded_env, section):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "tracker"
    at.session_state["patient_id"] = "P-017"
    at.session_state["tracker_tab"] = section
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_tracker_page_roster(seeded_env):
    at = _tracker_page(seeded_env, "Roster")
    frames = at.dataframe
    assert frames and any("pending reviews (count)" in str(c).lower() for c in frames[0].value.columns)


def test_patients_page_program_form(seeded_env):
    from datetime import date
    from src.ptlog.store import SessionStore
    with SessionStore(seeded_env).open() as store:
        store.assign_program("P-017", "knee_rehab", "Knee Rehabilitation",
                             ["knee_extension", "knee_extension_right", "partial_squat", "seated_hip_flexion", "seated_hip_flexion_right"],
                             3, date.today())
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "patients"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    options = [tuple(s.options) for s in at.selectbox]
    assert any({"Knee Rehabilitation", "Shoulder Mobility", "Hip Strengthening", "General Conditioning", "Custom"} <= set(o) for o in options)
    assert any("sessions per week" in n.label.lower() for n in at.number_input)
    assert at.date_input
    assert "Assign program" in {b.label for b in at.button}
    assert any("Knee Rehabilitation" in str(f.value.to_dict()) for f in at.dataframe)


def test_tracker_page_adherence(seeded_env):
    from datetime import date, timedelta
    from src.ptlog.store import SessionStore
    at = _tracker_page(seeded_env, "Adherence")
    assert any("no program" in i.value.lower() for i in at.info)
    with SessionStore(seeded_env).open() as store:
        store.assign_program("P-017", "custom", "Custom", ["knee_extension"], 3, date.today() - timedelta(days=10))
    at = _tracker_page(seeded_env, "Adherence")
    assert at.dataframe
