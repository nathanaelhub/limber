"""T011 — SessionRecorder turns engine outputs into canonical events without touching engine internals."""

import logging
import re
from pathlib import Path

import pytest

from analyze import ExerciseConfig, ExerciseSession, PartialRepMetrics, RepMetrics
from src.form_assessment import FeedbackPriority, FormFeedback, FormStatus, OverallFormAssessment
from src.ptlog.models import PatientNotFoundError
from src.ptlog.recorder import SessionRecorder
from src.ptlog.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parent.parent

KNEE = ExerciseConfig(name="Knee Extension", keypoints=[11, 13, 15], up_angle=170, down_angle=90,
                      form_tolerance=15, target_reps=10, side="left")
SQUAT = ExerciseConfig(name="Squat", keypoints=[11, 13, 15], up_angle=170, down_angle=90,
                       form_tolerance=15, target_reps=10, side="bilateral")


class FakeTracker:
    """Stands in for ExerciseTracker using only its public outputs."""

    def __init__(self, config):
        self.config = config
        self.session = ExerciseSession(exercise_name=config.name, start_time="2026-03-23T09:15:00",
                                       target_reps=config.target_reps)
        self.current_state = "neutral"
        self.rep_count = 0

    def complete_rep(self, min_angle=10.2, max_angle=88.6, rom=78.4, duration=3.1, form=95.0):
        self.rep_count += 1
        self.session.rep_metrics.append(RepMetrics(
            rep_number=self.rep_count, min_angle=min_angle, max_angle=max_angle, rom=rom,
            duration_seconds=duration, form_score=form, timestamp="2026-03-23T09:15:08"))

    def partial(self, reason="reversed_early", rom=40.2):
        self.session.partial_rep_metrics.append(PartialRepMetrics(
            exercise=self.config.name, min_angle=95.0, max_angle=95.0 + rom, rom=rom,
            duration_seconds=1.3, reason=reason, timestamp="2026-03-23T09:15:12"))


def metrics_for(tracker, angle):
    return {"exercise": tracker.config.name, "rep_count": tracker.rep_count,
            "target_reps": tracker.config.target_reps, "current_angle": round(angle or 0, 1),
            "state": tracker.current_state, "feedback": "", "warnings": []}


def assessment(status="warning", priority=FeedbackPriority.WARNING, message="Keep your back straight", body_part="trunk"):
    return OverallFormAssessment(
        overall_score=55.0, status=FormStatus(status),
        feedback_messages=[FormFeedback(message=message, priority=priority, body_part=body_part)])


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        yield s


@pytest.fixture
def recorder(store, fake_clock):
    return SessionRecorder(store, clock=fake_clock)


def count(store, table, where="1=1"):
    return store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


class TestStart:
    def test_start_creates_session_and_first_set(self, recorder, store):
        sid = recorder.start("unassigned", "webcam", "0", KNEE, exercise_key="knee_extension",
                             extras={"camera_id": 0, "imgsz": 320, "frame_skip": 1})
        assert recorder.session_id == sid
        s = store.conn.execute("SELECT status, source, source_ref FROM sessions WHERE id = ?", (sid,)).fetchone()
        assert tuple(s) == ("running", "webcam", "0")
        st = store.conn.execute("SELECT * FROM exercise_sets WHERE session_id = ?", (sid,)).fetchone()
        assert (st["exercise_key"], st["exercise_name"], st["side"], st["target_reps"], st["up_angle"], st["down_angle"]) == \
               ("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0)

    def test_start_none_patient_uses_unassigned(self, recorder, store):
        sid = recorder.start(None, "video", "clip.mp4", KNEE)
        assert store.conn.execute("SELECT patient_id FROM sessions WHERE id = ?", (sid,)).fetchone()[0] == "unassigned"

    def test_start_unknown_patient_raises(self, recorder):
        with pytest.raises(PatientNotFoundError):
            recorder.start("ghost", "webcam", "0", KNEE)

    def test_exercise_key_derived_from_name_when_absent(self, recorder, store):
        sid = recorder.start(None, "webcam", "0", ExerciseConfig(name="Knee Extension (Right)", keypoints=[12, 14, 16],
                                                                   up_angle=170, down_angle=90, form_tolerance=15,
                                                                   target_reps=10, side="right"))
        key = store.conn.execute("SELECT exercise_key FROM exercise_sets WHERE session_id = ?", (sid,)).fetchone()[0]
        assert key == "knee_extension_right"


class TestObserveReps:
    def test_new_rep_stored_with_observing_frame(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        recorder.observe(t, metrics_for(t, 120.0), 120.0, 30, None)
        t.complete_rep()
        recorder.observe(t, metrics_for(t, 91.0), 91.0, 60, None)
        recorder.observe(t, metrics_for(t, 92.0), 92.0, 61, None)   # no new rep
        rows = store.conn.execute("SELECT rep_number, rom, form_score, frame_num FROM reps").fetchall()
        assert [tuple(r) for r in rows] == [(1, 78.4, 95.0, 60)]

    def test_engine_float32_values_are_stored_rounded_like_legacy_loggers(self, recorder, store):
        import numpy as np
        recorder.start(None, "video", "clip.mp4", KNEE)
        t = FakeTracker(KNEE)
        t.complete_rep(min_angle=np.float32(round(36.4, 1)), max_angle=np.float32(round(108.2, 1)),
                       rom=np.float32(round(71.8, 1)), duration=np.float32(1.234), form=np.float32(round(53.4, 1)))
        recorder.observe(t, metrics_for(t, 91.0), 91.0, 36, None)
        row = store.conn.execute("SELECT min_angle, max_angle, rom, duration_seconds, form_score FROM reps").fetchone()
        assert tuple(row) == (36.4, 108.2, 71.8, 1.23, 53.4)

    def test_partial_rep_stored(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        t.partial("reversed_early", rom=40.2)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 150, None)
        row = store.conn.execute("SELECT reason, rom, frame_num FROM partial_reps").fetchone()
        assert tuple(row) == ("reversed_early", 40.2, 150)

    def test_long_no_keypoint_stretch_stores_nothing_and_ends_cleanly(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        for frame in range(1, 301):
            recorder.observe(t, metrics_for(t, None), None, frame, None)
        session = recorder.end(t.session)
        for table in ("reps", "partial_reps", "form_events", "frame_samples"):
            assert count(store, table) == 0
        assert session.status == "completed"
        assert session.total_reps == 0
        assert session.avg_form_score is None


class TestSamples:
    def test_every_15th_frame_with_angle_is_buffered_then_flushed_on_event(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        for frame in range(1, 46):
            recorder.observe(t, metrics_for(t, 100.0 + frame), 100.0 + frame, frame, None)
        assert recorder.pending_sample_count == 3
        assert count(store, "frame_samples") == 0
        t.complete_rep()
        recorder.observe(t, metrics_for(t, 91.0), 91.0, 50, None)   # event flushes the buffer
        assert recorder.pending_sample_count == 0
        frames = [r[0] for r in store.conn.execute("SELECT frame_num FROM frame_samples ORDER BY frame_num")]
        assert frames == [15, 30, 45]

    def test_no_sample_when_angle_is_none(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        recorder.observe(t, metrics_for(t, None), None, 15, None)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 16, None)
        assert recorder.pending_sample_count == 0

    def test_buffer_flushes_after_one_second(self, recorder, store, fake_clock):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 15, None)
        assert recorder.pending_sample_count == 1
        fake_clock.advance(2.0)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 16, None)
        assert recorder.pending_sample_count == 0
        assert count(store, "frame_samples") == 1

    def test_sample_records_raw_angle_state_and_count(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        t.current_state = "down"
        recorder.observe(t, metrics_for(t, 92.0), 92.04, 15, None)
        recorder.flush()
        row = store.conn.execute("SELECT angle, state, rep_count FROM frame_samples").fetchone()
        assert tuple(row) == (92.04, "down", 0)


class TestFormEvents:
    @pytest.mark.parametrize("status,expect", [("excellent", 0), ("good", 0), ("warning", 1), ("poor", 1), ("stop", 1)])
    def test_only_warning_poor_stop_are_stored(self, recorder, store, status, expect):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 10, assessment(status))
        assert count(store, "form_events") == expect

    def test_throttled_to_once_per_60_frames(self, recorder, store, fake_clock):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 10, assessment(message="A"))
        fake_clock.advance(5)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 50, assessment(message="B"))   # < 60 frames
        fake_clock.advance(5)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 70, assessment(message="C"))   # >= 60 frames
        msgs = [r[0] for r in store.conn.execute("SELECT message FROM form_events ORDER BY id")]
        assert msgs == ["A", "C"]

    def test_identical_message_not_stored_within_two_seconds(self, recorder, store, fake_clock):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 10, assessment(message="Same"))
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 100, assessment(message="Same"))     # ~1 s later: skipped
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 170, assessment(message="Other"))    # different: stored
        fake_clock.advance(3)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 240, assessment(message="Same"))     # > 2 s: stored
        msgs = [r[0] for r in store.conn.execute("SELECT message FROM form_events ORDER BY id")]
        assert msgs == ["Same", "Other", "Same"]

    @pytest.mark.parametrize("status,priority,expected", [
        ("warning", FeedbackPriority.SUGGESTION, "suggestion"),
        ("warning", FeedbackPriority.INFO, "suggestion"),
        ("warning", FeedbackPriority.WARNING, "warning"),
        ("poor", FeedbackPriority.INFO, "warning"),
        ("warning", FeedbackPriority.CRITICAL, "stop"),
        ("stop", FeedbackPriority.INFO, "stop"),
    ])
    def test_severity_mapping(self, recorder, store, status, priority, expected):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 10, assessment(status, priority))
        row = store.conn.execute("SELECT severity, status, body_part FROM form_events").fetchone()
        assert tuple(row) == (expected, status, "trunk")


class TestSwitchAndReset:
    def test_switch_closes_set_writes_event_opens_new_set(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE, exercise_key="knee_extension")
        old = FakeTracker(KNEE)
        old.complete_rep()
        recorder.observe(old, metrics_for(old, 91.0), 91.0, 60, None)
        old.partial("interrupted", rom=40.0)                     # legacy 'n' key records this on the old tracker
        recorder.switch(SQUAT, old, frame_num=200, exercise_key="squat")
        sets = store.conn.execute("SELECT ordinal, exercise_key, end_time FROM exercise_sets ORDER BY ordinal").fetchall()
        assert [(r["ordinal"], r["exercise_key"]) for r in sets] == [(1, "knee_extension"), (2, "squat")]
        assert sets[0]["end_time"] is not None and sets[1]["end_time"] is None
        ev = store.conn.execute("SELECT kind, from_exercise, to_exercise, frame_num FROM control_events").fetchone()
        assert tuple(ev) == ("switch", "Knee Extension", "Squat", 200)
        assert count(store, "partial_reps", "reason='interrupted'") == 1
        new = FakeTracker(SQUAT)
        new.complete_rep()
        recorder.observe(new, metrics_for(new, 170.0), 170.0, 240, None)
        rows = store.conn.execute(
            "SELECT s.ordinal, r.rep_number FROM reps r JOIN exercise_sets s ON s.id = r.set_id ORDER BY r.id").fetchall()
        assert [tuple(r) for r in rows] == [(1, 1), (2, 1)]

    def test_reset_writes_control_event_and_resets_delta_counters(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        t.complete_rep(); t.complete_rep()
        recorder.observe(t, metrics_for(t, 91.0), 91.0, 120, None)
        recorder.reset(t, frame_num=320)
        ev = store.conn.execute("SELECT kind, rep_count_at_reset, frame_num FROM control_events").fetchone()
        assert tuple(ev) == ("reset", 2, 320)
        fresh = FakeTracker(KNEE)
        fresh.complete_rep()
        recorder.observe(fresh, metrics_for(fresh, 91.0), 91.0, 380, None)
        assert count(store, "reps") == 3
        assert count(store, "exercise_sets") == 1


class TestEnd:
    def test_end_summary_matches_exercise_session(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        for form, rom in [(95.0, 78.4), (94.0, 79.1), (93.0, 77.8)]:
            t.complete_rep(form=form, rom=rom)
            recorder.observe(t, metrics_for(t, 91.0), 91.0, 60 * t.rep_count, None)
        es = t.session
        es.total_reps, es.avg_form_score, es.avg_rom = 3, round((95 + 94 + 93) / 3, 1), round((78.4 + 79.1 + 77.8) / 3, 1)
        session = recorder.end(es)
        assert (session.total_reps, session.avg_form_score, session.avg_rom) == (es.total_reps, es.avg_form_score, es.avg_rom)
        assert session.status == "completed"
        assert count(store, "exercise_sets", "end_time IS NULL") == 0

    def test_end_flushes_pending_samples(self, recorder, store):
        recorder.start(None, "webcam", "0", KNEE)
        t = FakeTracker(KNEE)
        recorder.observe(t, metrics_for(t, 100.0), 100.0, 15, None)
        recorder.end(t.session)
        assert count(store, "frame_samples") == 1


class TestDegradedMode:
    def test_store_errors_do_not_raise_until_end_and_log_no_phi(self, tmp_db, fake_clock, caplog):
        class FailingStore(SessionStore):
            def add_rep(self, set_id, rep):
                raise OSError("disk full")

        with FailingStore(tmp_db, clock=fake_clock).open() as store:
            store.conn.execute("INSERT INTO patients (id, label, notes, created_at) VALUES (?, ?, ?, ?)",
                               ("P-017", "Post-op knee", "private notes", "2026-03-23T09:00:00"))
            store.conn.commit()
            rec = SessionRecorder(store, clock=fake_clock)
            sid = rec.start("P-017", "webcam", "0", KNEE)
            t = FakeTracker(KNEE)
            t.complete_rep()
            with caplog.at_level(logging.ERROR, logger="ptlog"):
                rec.observe(t, metrics_for(t, 91.0), 91.0, 60, None)
                t.complete_rep()
                rec.observe(t, metrics_for(t, 91.0), 91.0, 120, None)
            assert rec.degraded is True
            assert len([r for r in caplog.records if r.name == "ptlog"]) == 1
            assert str(sid) in caplog.text
            assert "Post-op knee" not in caplog.text and "private notes" not in caplog.text
            with pytest.raises(OSError):
                rec.end(t.session)


class TestEngineHasNoLegacyWriters:
    def test_analyze_py_no_longer_calls_legacy_writers(self):
        src = (REPO_ROOT / "analyze.py").read_text()
        calls = re.findall(r"(?<!def )(?<!class )\b(ObservationLogger|PTARawLogger|SessionLogger|generate_session_report)\(", src)
        assert calls == [], f"legacy writer calls remain in analyze.py: {calls}"
