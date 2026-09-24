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


def test_tracker_page_queue(seeded_env):
    at = _tracker_page(seeded_env, "Queue")
    assert at.warning or at.info or at.success
    assert any("threshold" in c.value.lower() for c in at.caption)   # the control moved to Settings (feature 005)


def test_tracker_page_discharged_and_patient_controls(seeded_env):
    from src.ptlog.store import SessionStore
    at = _tracker_page(seeded_env, "Discharged")
    assert at.info or at.dataframe
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "patients"
    at.run()
    assert not at.exception and "Discharge patient" in {b.label for b in at.button}
    with SessionStore(seeded_env).open() as store:
        store.discharge("P-017", reason="goals met")
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "patients"
    at.run()
    assert not at.exception and "Reactivate" in {b.label for b in at.button}
    at = _tracker_page(seeded_env, "Discharged")
    assert at.dataframe and any("goals met" in str(f.value.to_dict()) for f in at.dataframe)


def test_tracker_page_export(seeded_env):
    at = _tracker_page(seeded_env, "Export")
    assert "Roster (CSV)" in {b.label for b in at.get("download_button")}


# ----------------------------------------------------------------------------- feature 004: live session page

class _StubState:
    def __init__(self, playing):
        self.playing = playing


class _StubCtx:
    def __init__(self, playing=False, processor=None):
        self.state = _StubState(playing)
        self.video_processor = processor


@pytest.fixture
def stub_webrtc(monkeypatch):
    """Replace the WebRTC component so the live page renders headlessly."""
    import streamlit_webrtc
    holder = {"ctx": _StubCtx(), "calls": []}

    def fake_streamer(**kwargs):
        holder["calls"].append(kwargs)
        return holder["ctx"]

    monkeypatch.setattr(streamlit_webrtc, "webrtc_streamer", fake_streamer)
    return holder


def _live_page(extra_state=None):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "live"
    at.session_state["patient_id"] = "P-017"
    for k, v in (extra_state or {}).items():
        at.session_state[k] = v
    return at.run()


def test_live_page_controls_come_from_the_configuration(seeded_env, stub_webrtc):
    from analyze import load_config
    at = _live_page()
    assert not at.exception, [e.value for e in at.exception]
    exercise = next(s for s in at.selectbox if s.key == "exercise_select")
    assert list(exercise.options) == [c.name for c in load_config().values()]
    assert any(s.key == "camera_select" for s in at.selectbox)
    assert any(n.label == "Target Reps" for n in at.number_input)
    labels = [b.label for b in at.button]
    assert not any("Save Session" in label for label in labels)
    assert any("Save Screenshot" in label for label in labels)
    assert stub_webrtc["calls"], "the stream component must be created"


def test_live_page_shows_stored_summary_and_opens_the_session(seeded_env, stub_webrtc):
    with SessionStore(seeded_env).open() as store:
        sid = store.list_sessions("P-017")[0].id
    at = _live_page({"live_session_id": sid})
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.success)
    assert f"Session {sid}" in text and "3 reps" in text
    at.button(key="live_open_session").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["current_page"] == "sessions"
    assert at.session_state["sessions_open"] == sid


class _FakeProcessor:
    def __init__(self):
        self.session_id, self.patient_id, self.exercise_key = 41, "P-017", "squat"
        self.error, self.last_frame, self.requests, self.configured = None, None, [], None

    def configure(self, *args):
        self.configured = args

    def request_switch(self, key):
        self.requests.append(("switch", key))

    def request_reset(self):
        self.requests.append(("reset",))


def test_live_page_while_playing_offers_switch_and_reset(seeded_env, stub_webrtc):
    proc = _FakeProcessor()
    stub_webrtc["ctx"] = _StubCtx(playing=True, processor=proc)
    at = _live_page()
    assert not at.exception, [e.value for e in at.exception]
    assert proc.configured[:2] == ("P-017", "knee_extension")
    assert any("Recording session 41 for P-017" in c.value for c in at.caption)
    assert at.session_state["live_session_id"] == 41
    at.button(key="live_switch").click().run()
    at.button(key="live_reset").click().run()
    assert proc.requests == [("switch", "knee_extension"), ("reset",)]


def _running_live_session(db, age_seconds):
    import os
    start = datetime.now() - timedelta(seconds=age_seconds)
    with SessionStore(db, clock=FixedClock(start)).open() as store:
        sid = store.start_session("P-017", "webcam", "Default", {"pid": os.getpid(), "origin": "web"})
        set_id = store.open_set(sid, KNEE)
        store.add_rep(set_id, RepEvent(1, 85.0, 172.0, 87.0, 2.0, 91.0, start.isoformat(), 60))
    return sid


def test_live_page_interrupts_a_session_whose_stream_was_lost(seeded_env, stub_webrtc):
    sid = _running_live_session(seeded_env, age_seconds=120)
    at = _live_page({"live_session_id": sid})
    assert not at.exception, [e.value for e in at.exception]
    with SessionStore(seeded_env).open() as store:
        s = store.load_session(sid)
    assert (s.status, s.interrupted_reason, s.total_reps) == ("interrupted", "stream_lost", 1)
    assert any("interrupted" in w.value for w in at.warning)


def test_live_page_leaves_a_session_that_is_still_finishing(seeded_env, stub_webrtc):
    sid = _running_live_session(seeded_env, age_seconds=1)
    at = _live_page({"live_session_id": sid})
    assert not at.exception, [e.value for e in at.exception]
    with SessionStore(seeded_env).open() as store:
        assert store.load_session(sid).status == "running"


def test_live_page_screenshot_without_a_frame(seeded_env, stub_webrtc):
    at = _live_page()
    at.button(key="live_screenshot").click().run()
    assert not at.exception
    assert any("No frame to save" in i.value for i in at.info)


def test_live_page_screenshot_saves_the_current_frame(seeded_env, stub_webrtc, tmp_path, monkeypatch):
    import numpy as np
    from src.ptlog import exports
    monkeypatch.setattr(exports, "default_export_dir", lambda: tmp_path / "exports")
    proc = _FakeProcessor()
    proc.last_frame = np.full((60, 80, 3), 128, dtype=np.uint8)
    stub_webrtc["ctx"] = _StubCtx(playing=True, processor=proc)
    at = _live_page()
    at.button(key="live_screenshot").click().run()
    assert not at.exception, [e.value for e in at.exception]
    (png,) = list((tmp_path / "exports").glob("P-017_*.png"))
    assert any(png.name in s.value for s in at.success)


# ----------------------------------------------------------------------------- feature 005: attention thresholds

def test_review_page_thresholds_editor(seeded_env):
    at = _review_page(seeded_env, "Goals & settings")
    assert not at.exception, [e.value for e in at.exception]
    table = at.dataframe[0].value
    assert list(table["Threshold"])[:3] == ["Practice gap", "Form drop", "ROM regression"]
    assert set(table["Origin"]) == {"default"}
    at.number_input(key="threshold_rom_regression").set_value(5)
    at.button(key="thresholds_save").click().run()
    assert not at.exception, [e.value for e in at.exception]
    with SessionStore(seeded_env).open() as store:
        assert store.get_patient_thresholds("P-017") == {"rom_regression": 5}     # only the changed value is stored
    at.button(key="thresholds_reset_all").click().run()
    with SessionStore(seeded_env).open() as store:
        assert store.get_patient_thresholds("P-017") == {}


def test_tracker_adherence_states_the_threshold(seeded_env):
    from datetime import date, timedelta
    with SessionStore(seeded_env).open() as store:
        store.assign_program("P-017", "custom", "Custom", ["knee_extension"], 3, date.today() - timedelta(days=10))
        store.set_patient_threshold("P-017", "adherence", 50)
    at = _tracker_page(seeded_env, "Adherence")
    assert not at.exception
    assert any("Attention threshold: 50% (patient)" in m.value for m in at.markdown)


def test_tracker_installation_thresholds_editor(seeded_env):
    at = _tracker_page(seeded_env, "Settings")
    assert not at.exception, [e.value for e in at.exception]
    at.number_input(key="install_threshold_form_drop").set_value(8)
    at.button(key="install_thresholds_save").click().run()
    assert not at.exception, [e.value for e in at.exception]
    with SessionStore(seeded_env).open() as store:
        assert store.get_installation_thresholds() == {"form_drop": 8}
        assert store.effective_thresholds("P-017").origin("form_drop") == "installation"
    at.button(key="install_thresholds_restore").click().run()
    with SessionStore(seeded_env).open() as store:
        assert store.get_installation_thresholds() == {}


# ----------------------------------------------------------------------------- feature 006

def test_review_thresholds_for_one_exercise_and_history(seeded_env):
    at = _review_page(seeded_env, "Goals & settings")
    scope = next(s for s in at.selectbox if s.key == "thresholds_scope")
    assert list(scope.options) == ["Whole patient", "Knee Extension"]
    scope.set_value("Knee Extension").run()
    assert not at.exception, [e.value for e in at.exception]
    keys = [n.key for n in at.number_input if (n.key or "").startswith("threshold_")]
    assert len(keys) == 6 and not any("adherence" in k or "practice_gap" in k for k in keys)
    at.number_input(key="threshold_Knee Extension_rom_regression").set_value(5)
    at.button(key="thresholds_save").click().run()
    assert not at.exception, [e.value for e in at.exception]
    with SessionStore(seeded_env).open() as store:
        assert store.get_exercise_thresholds("P-017") == {"Knee Extension": {"rom_regression": 5}}
        assert store.get_patient_thresholds("P-017") == {}
    history = next(d.value for d in at.dataframe if "Change" in d.value.columns)
    assert list(history["Applies to"]) == ["Knee Extension"] and "default → 5 degrees" in history["Change"][0]


def test_tracker_settings_shows_installation_history(seeded_env):
    with SessionStore(seeded_env).open() as store:
        store.set_installation_threshold("adherence", 50)
    at = _tracker_page(seeded_env, "Settings")
    assert not at.exception, [e.value for e in at.exception]
    assert any("Change" in d.value.columns and "default → 50 percent" in d.value["Change"][0] for d in at.dataframe)


# ----------------------------------------------------------------------------- feature 007 US6: therapist sign-in

THERAPIST_PASSWORD = "correct horse battery"


def _with_password(db):
    from src.portal import admin
    with SessionStore(db).open() as store:
        admin.set_password(store, THERAPIST_PASSWORD)


def _visible_text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [b.label for b in at.button]
    parts += [str(d.value) for d in at.dataframe] + [str(o) for s in at.selectbox for o in s.options]
    return " ".join(parts)


def test_therapist_app_shows_only_a_sign_in_when_a_password_is_set(seeded_env):
    _with_password(seeded_env)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "sessions"
    at.session_state["patient_id"] = "P-017"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(t.key == "therapist_password" for t in at.text_input)
    text = _visible_text(at)
    assert "P-017" not in text and "Post-op knee" not in text and not at.dataframe
    assert not any("Tracker" in b.label or "Review" in b.label for b in at.button)


def test_password_opens_the_app_and_sign_out_closes_it(seeded_env):
    _with_password(seeded_env)
    at = AppTest.from_file(str(APP), default_timeout=180).run()
    at.text_input(key="therapist_password").set_value("wrong password!!").run()
    at.button(key="therapist_signin").click().run()
    assert any("did not work" in e.value for e in at.error) and not any("Tracker" in b.label for b in at.button)
    at.text_input(key="therapist_password").set_value(THERAPIST_PASSWORD).run()
    at.button(key="therapist_signin").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Tracker" in b.label for b in at.button)
    at.button(key="therapist_signout").click().run()
    assert any(t.key == "therapist_password" for t in at.text_input)


def test_a_pass_from_the_front_page_opens_the_app_once(seeded_env):
    from src.portal import admin
    _with_password(seeded_env)
    with SessionStore(seeded_env).open() as store:
        a_pass = admin.issue_pass(store)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.query_params["pass"] = a_pass
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Tracker" in b.label for b in at.button) and "pass" not in at.query_params
    again = AppTest.from_file(str(APP), default_timeout=180)
    again.query_params["pass"] = a_pass
    again.run()
    assert any(t.key == "therapist_password" for t in again.text_input)          # single use


def test_without_a_password_the_app_opens_as_before(seeded_env):
    at = AppTest.from_file(str(APP), default_timeout=180).run()
    assert any("Tracker" in b.label for b in at.button) and not any(t.key == "therapist_password" for t in at.text_input)


# ----------------------------------------------------------------------------- feature 007 US5: home access on the Patients page

def _patients_page(db, monkeypatch, patient="P-017"):
    monkeypatch.setenv("PTASSIST_PORTAL_KEY", "ab" * 32)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "patients"
    at.session_state["patient_id"] = patient
    return at.run()


def test_patients_page_issues_a_code_once_and_revokes_it(seeded_env, monkeypatch):
    import re
    at = _patients_page(seeded_env, monkeypatch)
    assert not at.exception, [e.value for e in at.exception]
    assert any("Home access" in m.value for m in at.markdown) and any("none" in c.value.lower() for c in at.caption)
    at.button(key="home_access_issue").click().run()
    assert not at.exception, [e.value for e in at.exception]
    shown = [c.value for c in at.code]
    assert len(shown) == 1 and re.fullmatch(r"[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}", shown[0])
    assert any("only once" in w.value.lower() and "study" in w.value.lower() for w in at.warning)
    with SessionStore(seeded_env).open() as store:
        assert store.portal_status("P-017").state == "active"
    at = _patients_page(seeded_env, monkeypatch)                     # a fresh visit never shows the code again
    assert not at.code and any("active until" in c.value for c in at.caption)
    at.button(key="home_access_revoke").click().run()
    with SessionStore(seeded_env).open() as store:
        assert store.portal_status("P-017").state == "revoked"
        assert [a.event for a in store.portal_audit_list("P-017")][:2] == ["code_revoked", "code_created"]


# ----------------------------------------------------------------------------- feature 008: the therapist's inbox

def _seed_messages(db):
    from src.portal import messages
    with SessionStore(db).open() as store:
        store.add_patient("P-021")
        for pid in ("P-017", "P-021"):
            messages.set_enabled(store, pid, True)
        messages.send(store, "P-017", "patient", "My knee was sore after the stairs")
        messages.send(store, "P-017", "patient", "Should I skip tomorrow?")
        messages.send(store, "P-021", "patient", "All good here")


def _inbox(db, patient=None):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = "inbox"
    if patient:
        at.session_state["inbox_open"] = patient
    return at.run()


def test_inbox_lists_conversations_and_the_sidebar_counts_unread(seeded_env):
    _seed_messages(seeded_env)
    home = AppTest.from_file(str(APP), default_timeout=180).run()
    assert any("Inbox" in b.label and "3" in b.label for b in home.button)          # visible from every page
    at = _inbox(seeded_env)
    assert not at.exception, [e.value for e in at.exception]
    table = at.dataframe[0].value
    assert list(table["Patient"]) == ["P-021", "P-017"] and list(table["Unread"]) == [1, 2]
    assert "All good here" in list(table["Latest message"])[0]
    assert any("Inbox" in b.label and "3" in b.label for b in at.button)


def test_opening_a_thread_marks_it_read_and_a_reply_is_stored(seeded_env):
    from src.portal import messages
    _seed_messages(seeded_env)
    at = _inbox(seeded_env, "P-017")
    assert not at.exception, [e.value for e in at.exception]
    shown = " ".join(x.value for x in at.text)                         # message text is rendered as plain text
    assert "sore after the stairs" in shown and "All good here" not in shown
    with SessionStore(seeded_env).open() as store:
        assert messages.unread_count(store, "P-017", "therapist") == 0 and messages.unread_count(store, "P-021", "therapist") == 1
    at.text_area(key="inbox_reply").set_value("Rest tomorrow, then half the reps.").run()
    at.button(key="inbox_send").click().run()
    assert not at.exception, [e.value for e in at.exception]
    with SessionStore(seeded_env).open() as store:
        thread = messages.thread(store, "P-017", viewer="patient", mark_read=False)
        assert [(m.sender, m.body) for m in thread][-1] == ("therapist", "Rest tomorrow, then half the reps.")
    assert at.text_area(key="inbox_reply").value == ""                  # emptied, so it cannot be sent twice
    at.button(key="inbox_send").click().run()
    with SessionStore(seeded_env).open() as store:
        assert len(messages.thread(store, "P-017", viewer="patient", mark_read=False)) == 3


def test_reply_with_identifying_text_asks_first(seeded_env):
    from src.portal import messages
    _seed_messages(seeded_env)
    at = _inbox(seeded_env, "P-017")
    at.text_area(key="inbox_reply").set_value("Call Jane Smith at the front desk").run()
    at.button(key="inbox_send").click().run()
    assert any("name" in w.value for w in at.warning)
    with SessionStore(seeded_env).open() as store:
        assert len(messages.thread(store, "P-017", "therapist", mark_read=False)) == 2
    at.button(key="inbox_send_anyway").click().run()
    with SessionStore(seeded_env).open() as store:
        assert messages.thread(store, "P-017", "therapist", mark_read=False)[-1].warned is True


def test_thread_shows_context_and_can_turn_messaging_off_and_remove(seeded_env):
    from src.portal import messages
    _seed_messages(seeded_env)
    at = _inbox(seeded_env, "P-017")
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Latest session" in text and "3 reps" in text                   # context beside the thread
    with SessionStore(seeded_env).open() as store:
        first_id = messages.thread(store, "P-017", "therapist", mark_read=False)[0].id
    at.button(key=f"inbox_remove_{first_id}").click().run()
    with SessionStore(seeded_env).open() as store:
        assert messages.thread(store, "P-017", "therapist", mark_read=False)[0].removed is True
    at.toggle(key="inbox_enabled").set_value(False).run()
    with SessionStore(seeded_env).open() as store:
        assert messages.is_enabled(store, "P-017") is False


# ----------------------------------------------------------------------------- feature 010: From the patient

def test_review_from_the_patient_tab(seeded_env):
    with SessionStore(seeded_env).open() as store:
        for i, pain in enumerate((2, 3, 2, 8)):
            store.entry_add("P-017", "checkin", {"pain": pain, "area": "knee", "stiffness": "mild", "swelling": "none",
                                                 "note": "Jane Smith was here" if i == 3 else ""},
                            float(pain), (datetime.now() - timedelta(days=4 - i)).isoformat(), f"c{i}", "standalone",
                            None, warned=(i == 3), time_adjusted=False)
    at = _review_page(seeded_env, "From the patient")
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Pain" in text and "0-10" in text
    table = next(d.value for d in at.dataframe if "Pain" in d.value.columns)
    assert list(table["Pain"]) == [8, 2, 3, 2] and "privacy warning" in str(table.to_dict()).lower()
    assert any("pain_rising" in w.value or "pain_high" in w.value for w in list(at.warning) + list(at.markdown))
    with SessionStore(seeded_env).open() as store:
        target = store.entries("P-017", newest_first=True)[0].id
    at.button(key=f"entry_remove_note_{target}").click().run()
    with SessionStore(seeded_env).open() as store:
        assert store.entries("P-017", newest_first=True)[0].note_removed is True


# ----------------------------------------------------------------------------- feature 011: clips for the PT

def _seed_clip(db, tmp_path, caption="Knee catching"):
    from src.portal import uploads
    from tests.fixtures import media as media_fx
    import hashlib
    clip = media_fx.make_video(tmp_path / "c.mp4", seconds=2.0)
    data = clip.read_bytes()
    with SessionStore(db).open() as store:
        up = uploads.begin(store, store.media_dir, "P-017", "clip", len(data), hashlib.sha256(data).hexdigest(), chunk_bytes=len(data))
        uploads.put_part(store, store.media_dir, "P-017", up.id, 0, data)
        return uploads.finish(store, store.media_dir, "P-017", up.id, caption=caption)


def test_review_tab_plays_reviews_and_deletes_a_clip(seeded_env, tmp_path):
    m = _seed_clip(seeded_env, tmp_path)
    at = _review_page(seeded_env, "From the patient")
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(x.value for x in list(at.markdown) + list(at.caption) + list(at.text))
    assert "Knee catching" in text and "waiting for review" in text.lower()
    assert at.get("video"), "the clip is shown with a player"      # AppTest has no .video accessor; get() finds it by type
    at.button(key=f"media_review_{m.id}").click().run()
    with SessionStore(seeded_env).open() as store:
        assert store.media_get(m.id).reviewed_at is not None
    at.button(key=f"media_delete_{m.id}").click().run()
    with SessionStore(seeded_env).open() as store:
        gone = store.media_get(m.id)
        assert gone.deleted_by == "therapist" and not (store.media_dir / "P-017" / f"{m.id}.mp4").exists()
