"""Feature 004 — LiveSession: the real engine plus the recorder, driven by synthetic poses (no camera, no model)."""

import os
import time
from datetime import datetime, timedelta

import numpy as np
import pytest

from src.form_assessment import FeedbackPriority, FormFeedback, FormStatus, OverallFormAssessment
from src.live_session import LiveSession
from src.ptlog.models import PatientNotFoundError
from src.ptlog.store import SessionStore
from tests.fixtures.poses import FakeInfer, rep_cycle

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


class QuietAnalyzer:
    """Analyzer stub: always excellent form, so no form events."""

    def __init__(self, status=FormStatus.EXCELLENT, messages=()):
        self.status, self.messages, self.resets = status, list(messages), 0

    def analyze_frame(self, keypoints, frame_num=0):
        return OverallFormAssessment(overall_score=95.0, status=self.status, feedback_messages=[
            FormFeedback(message=m, priority=FeedbackPriority.WARNING, body_part="knee") for m in self.messages])

    def reset(self):
        self.resets += 1


@pytest.fixture
def store(tmp_db):
    s = SessionStore(tmp_db, check_same_thread=False).open()
    s.add_patient("P-017", label="Post-op knee")
    yield s
    s.close()


def make_live(store, angles=(), patient="P-017", exercise="knee_extension", target=10, analyzer=None, **kw):
    infer = FakeInfer(angles)
    analyzer = analyzer or QuietAnalyzer()
    live = LiveSession(store, patient, exercise, target, "Default", infer,
                       form_analyzer_factory=lambda base: analyzer, **kw)
    return live, infer


def run(live, n):
    for _ in range(n):
        live.process(FRAME)


class TestStart:
    def test_creates_running_webcam_session_with_one_set(self, store):
        live, _ = make_live(store, target=12)
        sid = live.start()
        s = store.load_session(sid)
        assert (s.status, s.source, s.source_ref, s.patient_id) == ("running", "webcam", "Default", "P-017")
        assert s.source_extras == {"camera_id": "Default", "imgsz": 320, "frame_skip": 1, "origin": "web",
                                   "pid": os.getpid()}
        assert len(s.sets) == 1
        assert (s.sets[0].exercise_key, s.sets[0].exercise_name, s.sets[0].target_reps) == (
            "knee_extension", "Knee Extension", 12)
        assert live.start() == sid            # idempotent
        assert live.session_id == sid and live.exercise_name == "Knee Extension"

    def test_unknown_exercise_and_patient(self, store):
        with pytest.raises(ValueError):
            make_live(store, exercise="moonwalk")
        live, _ = make_live(store, patient="P-404")
        with pytest.raises(PatientNotFoundError):
            live.start()

    def test_no_patient_records_under_unassigned(self, store):
        live, _ = make_live(store, patient=None)
        assert store.load_session(live.start()).patient_id == "unassigned"

    def test_process_before_start_passes_frame_through(self, store):
        live, infer = make_live(store, rep_cycle())
        out = live.process(FRAME)
        assert out is FRAME and infer.calls == 0


class TestReps:
    def test_three_cycles_store_three_reps_equal_to_the_engine(self, store):
        angles = rep_cycle() * 3
        live, _ = make_live(store, angles)
        sid = live.start()
        run(live, len(angles))
        engine = live.tracker.session.rep_metrics
        stored = store.load_session(sid).sets[0].reps
        assert len(engine) == 3 and len(stored) == 3
        for e, r in zip(engine, stored):
            assert r.rep_number == e.rep_number
            assert r.rom == pytest.approx(round(float(e.rom), 1))
            assert r.duration_seconds == pytest.approx(round(float(e.duration_seconds), 2))
            assert r.form_score == pytest.approx(round(float(e.form_score), 1))
        assert live.metrics["rep_count"] == 3

    def test_process_returns_annotated_frame_and_keeps_it(self, store):
        live, _ = make_live(store, rep_cycle())
        live.start()
        out = live.process(FRAME)
        assert out.shape == FRAME.shape and out is not FRAME
        assert out.any(), "the engine panel must be drawn on the frame (FR-002)"
        assert live.last_frame is out

    def test_infer_may_return_keypoints_and_a_plotted_frame(self, store):
        from tests.fixtures.poses import keypoints_for_angle
        plotted = np.full_like(FRAME, 7)
        live = LiveSession(store, "P-017", "knee_extension", 10, "Default",
                           lambda f: (keypoints_for_angle(170.0), plotted),
                           form_analyzer_factory=lambda b: QuietAnalyzer(), draw=False)
        live.start()
        assert (live.process(FRAME) == 7).all()


class TestPartialFormNoPerson:
    def test_early_reversal_stores_a_partial_rep(self, store):
        # Knee extension starts flexed (~88), must reach ~170; turning back at 130 is a partial rep.
        start, part = 88.0, 130.0
        angles = ([start] * 8 + list(np.linspace(start, part, 6)) + [part] * 6
                  + list(np.linspace(part, start, 6)) + [start] * 10)
        live, _ = make_live(store, angles)
        sid = live.start()
        run(live, len(angles))
        engine = live.tracker.session.partial_rep_metrics
        stored = store.load_session(sid).sets[0].partial_reps
        assert len(engine) >= 1 and len(stored) == len(engine)
        assert stored[0].reason == engine[0].reason
        assert store.load_session(sid).sets[0].reps == []

    def test_form_warning_is_recorded_throttled_and_shown(self, store):
        analyzer = QuietAnalyzer(FormStatus.WARNING, ["Keep knee aligned", "Slow down", "Third message"])
        angles = [172.0] * 100
        ticks = iter(range(10 ** 6))
        clock = lambda: datetime(2026, 3, 23, 9, 0, 0) + timedelta(seconds=0.1 * next(ticks))  # noqa: E731
        live, _ = make_live(store, angles, analyzer=analyzer, clock=clock)
        sid = live.start()
        run(live, len(angles))
        events = store.load_session(sid).sets[0].form_events
        assert len(events) == 2                       # frames 1 and 61 (60-frame throttle)
        assert events[0].message == "Keep knee aligned" and events[0].status == "warning"
        assert live.metrics["form_status"] == "warning"
        assert live.metrics["form_messages"] == ["Keep knee aligned", "Slow down"]

    def test_no_person_records_nothing(self, store):
        live, _ = make_live(store, [None] * 40)
        sid = live.start()
        run(live, 40)
        s = store.load_session(sid)
        assert s.sets[0].reps == [] and s.sets[0].partial_reps == [] and s.sets[0].form_events == []
        assert store.conn.execute("SELECT COUNT(*) FROM frame_samples").fetchone()[0] == 0


class TestEnd:
    def test_end_completes_with_the_engine_summary_and_is_idempotent(self, store):
        angles = rep_cycle() * 2
        live, infer = make_live(store, angles)
        sid = live.start()
        run(live, len(angles))
        done = live.end()
        engine = live.tracker.session
        assert done.id == sid and done.status == "completed" and live.ended
        assert done.total_reps == engine.total_reps == 2
        assert done.avg_rom == pytest.approx(engine.avg_rom, abs=0.1)
        assert done.avg_form_score == pytest.approx(engine.avg_form_score, abs=0.1)
        assert live.end().id == sid
        calls = infer.calls
        assert live.process(FRAME) is FRAME and infer.calls == calls

    def test_end_before_start_returns_none(self, store):
        live, _ = make_live(store)
        assert live.end() is None


class _NullRecorder:
    session_id = 1

    def start(self, *a, **k):
        return 1

    def observe(self, *a, **k):
        pass

    def end(self, *a, **k):
        return None


def test_recording_adds_under_two_ms_per_frame(store):
    """FR-011 / SC-004: 300 frames with recording on versus off."""
    angles = (rep_cycle() * 9)[:300]

    def timed(live):
        live.start()
        t0 = time.perf_counter()
        run(live, 300)
        return (time.perf_counter() - t0) / 300

    on, _ = make_live(store, angles, draw=False)
    off, _ = make_live(store, angles, draw=False)
    off.recorder = _NullRecorder()
    t_off = timed(off)
    t_on = timed(on)
    on.end()
    assert (t_on - t_off) * 1000 < 2.0, f"recording cost {(t_on - t_off) * 1000:.2f} ms/frame"
