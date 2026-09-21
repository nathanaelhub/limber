"""Feature 004 T003 — store support for a live web session (threads, pid-aware recovery, interrupt)."""

import os
import subprocess
import sys
import threading

from src.ptlog.models import ExerciseSetInfo, RepEvent
from src.ptlog.store import SessionStore

KNEE = ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0)


def _status(db, sid):
    with SessionStore(db) as s:
        row = s.conn.execute("SELECT status, interrupted_reason FROM sessions WHERE id = ?", (sid,)).fetchone()
    return row["status"], row["interrupted_reason"]


def _dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_other_thread_can_write_when_flag_is_off(tmp_db):
    store = SessionStore(tmp_db, check_same_thread=False).open()
    sid = store.start_session("unassigned", "webcam", "Default")
    set_id = store.open_set(sid, KNEE)
    errors = []

    def work():
        try:
            store.add_rep(set_id, RepEvent(1, 85.0, 172.0, 87.0, 2.0, 90.0, "2026-03-23T09:00:05", 60))
        except Exception as err:  # noqa: BLE001
            errors.append(err)

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert errors == []
    assert store.end_session(sid).total_reps == 1
    store.close()


def test_running_session_of_living_process_survives_open(tmp_db):
    store = SessionStore(tmp_db).open()
    sid = store.start_session("unassigned", "webcam", "Default", {"pid": os.getpid()})
    assert _status(tmp_db, sid) == ("running", None)
    assert store.end_session(sid).status == "completed"
    store.close()


def test_running_session_of_dead_process_is_recovered(tmp_db):
    store = SessionStore(tmp_db).open()
    sid = store.start_session("unassigned", "webcam", "Default", {"pid": _dead_pid()})
    store.close()
    assert _status(tmp_db, sid) == ("interrupted", "recovered_on_open")


def test_running_session_without_pid_is_recovered(tmp_db):
    store = SessionStore(tmp_db).open()
    sid = store.start_session("unassigned", "webcam", "0", {"camera_id": 0})
    store.close()
    assert _status(tmp_db, sid) == ("interrupted", "recovered_on_open")


def test_start_session_supersedes_even_a_living_owner(tmp_db):
    store = SessionStore(tmp_db).open()
    first = store.start_session("unassigned", "webcam", "Default", {"pid": os.getpid()})
    second = store.start_session("unassigned", "webcam", "Default", {"pid": os.getpid()})
    assert store.load_session(first).status == "interrupted"
    assert store.load_session(first).interrupted_reason == "superseded_by_new_session"
    assert store.load_session(second).status == "running"
    store.close()


def test_interrupt_session(tmp_db):
    store = SessionStore(tmp_db).open()
    sid = store.start_session("unassigned", "webcam", "Default", {"pid": os.getpid()})
    store.interrupt_session(sid, "stream_lost")
    s = store.load_session(sid)
    assert (s.status, s.interrupted_reason) == ("interrupted", "stream_lost")
    done = store.start_session("unassigned", "webcam", "Default", {"pid": os.getpid()})
    store.end_session(done)
    store.interrupt_session(done, "stream_lost")
    assert store.load_session(done).status == "completed"
    store.close()


def test_recorder_marks_every_session_with_its_process(tmp_db):
    """A command-line session must survive another process opening the record (e.g. `sessions list`)."""
    from types import SimpleNamespace
    from src.ptlog.recorder import SessionRecorder
    cfg = SimpleNamespace(name="Knee Extension", side="left", target_reps=10, up_angle=170, down_angle=90)
    store = SessionStore(tmp_db).open()
    rec = SessionRecorder(store)
    sid = rec.start(None, "webcam", "0", cfg, exercise_key="knee_extension", extras={"camera_id": 0})
    assert store.load_session(sid).source_extras == {"camera_id": 0, "pid": os.getpid()}
    video = SessionRecorder(store)
    assert _status(tmp_db, sid) == ("running", None)
    vid = video.start(None, "video", "clip.mp4", cfg, exercise_key="knee_extension")
    assert store.load_session(vid).source_extras == {"pid": os.getpid()}
    store.close()


# ----------------------------------------------------------------------------- feature 007: one running session per patient

def test_another_patients_session_is_not_interrupted(tmp_db):
    """FR-012: two people exercise at once (two patients at home, or home and clinic)."""
    store = SessionStore(tmp_db).open()
    store.add_patient("P-017")
    store.add_patient("P-018")
    a = store.start_session("P-017", "webcam", "home", {"pid": os.getpid()})
    b = store.start_session("P-018", "webcam", "home", {"pid": os.getpid()})
    assert store.load_session(a).status == "running" and store.load_session(b).status == "running"
    a2 = store.start_session("P-017", "webcam", "Default", {"pid": os.getpid()})     # same patient: still superseded
    assert store.load_session(a).status == "interrupted"
    assert store.load_session(a).interrupted_reason == "superseded_by_new_session"
    assert store.load_session(b).status == "running" and store.load_session(a2).status == "running"
    assert store.end_session(b).status == "completed"
    store.close()
