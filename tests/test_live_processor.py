"""Feature 004 — LiveVideoProcessor: the WebRTC callback object, driven without a browser or the model."""

import numpy as np
import pytest

from src.ptlog.store import SessionStore
from tests.fixtures.poses import FakeInfer, rep_cycle

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


@pytest.fixture
def app_module(tmp_db, monkeypatch):
    monkeypatch.setenv("PTASSIST_DB", str(tmp_db))
    import interfaces.app as app
    return app


@pytest.fixture
def db(tmp_db):
    with SessionStore(tmp_db).open() as store:
        store.add_patient("P-017", label="Post-op knee")
    return tmp_db


def test_frames_pass_through_until_configured(app_module, db):
    proc = app_module.LiveVideoProcessor(infer=FakeInfer(rep_cycle()))
    assert proc.process_image(FRAME) is FRAME
    assert proc.session_id is None and proc.live is None


def test_first_frame_starts_the_session_and_on_ended_completes_it(app_module, db):
    angles = rep_cycle() * 2
    proc = app_module.LiveVideoProcessor(infer=FakeInfer(angles))
    proc.configure("P-017", "knee_extension", 8, "Front Camera")
    for _ in angles:
        out = proc.process_image(FRAME)
    assert proc.session_id is not None and proc.last_frame is out and proc.error is None
    # a page rerun opens the record while the stream runs: the session must stay running (research D11)
    with SessionStore(db).open() as other:
        assert other.load_session(proc.session_id).status == "running"
    proc.on_ended()
    proc.on_ended()                                   # safe to call twice
    with SessionStore(db).open() as store:
        s = store.load_session(proc.session_id)
    assert (s.status, s.total_reps, s.patient_id, s.source_ref) == ("completed", 2, "P-017", "Front Camera")
    assert s.sets[0].target_reps == 8


def test_patient_is_fixed_once_the_session_exists(app_module, db):
    proc = app_module.LiveVideoProcessor(infer=FakeInfer(rep_cycle()))
    proc.configure("P-017", "knee_extension", 10, "Default")
    proc.process_image(FRAME)
    proc.configure("unassigned", "knee_extension", 10, "Default")   # sidebar changed mid-stream
    assert proc.patient_id == "P-017"
    proc.on_ended()


def test_unknown_patient_reports_an_error_and_keeps_streaming(app_module, db):
    proc = app_module.LiveVideoProcessor(infer=FakeInfer(rep_cycle()))
    proc.configure("P-404", "knee_extension", 10, "Default")
    assert proc.process_image(FRAME) is FRAME
    assert "P-404" in proc.error and proc.session_id is None


def test_switch_and_reset_requests_apply_on_the_next_frame(app_module, db):
    angles = rep_cycle() * 2
    infer = FakeInfer(angles)
    proc = app_module.LiveVideoProcessor(infer=infer)
    proc.configure("P-017", "knee_extension", 10, "Default")
    for _ in angles:
        proc.process_image(FRAME)
    proc.request_reset()
    proc.request_switch("squat")
    with SessionStore(db).open() as store:
        assert store.load_session(proc.session_id).control_events == []     # nothing until a frame arrives
    infer.extend([172.0])
    proc.process_image(FRAME)
    proc.request_switch("squat")                                            # already on squat: no second switch
    infer.extend([172.0])
    proc.process_image(FRAME)
    proc.on_ended()
    with SessionStore(db).open() as store:
        s = store.load_session(proc.session_id)
    assert [e.kind for e in s.control_events] == ["reset", "switch"]
    assert [x.exercise_key for x in s.sets] == ["knee_extension", "squat"]
    assert proc.exercise_key == "squat"
