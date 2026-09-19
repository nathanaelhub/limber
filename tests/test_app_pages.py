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


PAGES = ["home", "patients", "sessions", "obs_logs", "review", "video", "learn"]


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
