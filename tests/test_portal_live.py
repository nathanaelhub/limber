"""Feature 007 T024 — a patient's guided home session: the clinic's engine fed by body points from
the browser, moving through the assigned program, recorded under the patient's ID."""

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from src.portal import live
from src.ptlog.models import PortalError
from src.ptlog.origin import capture_origin
from src.ptlog.store import SessionStore
from tests.fixtures.poses import keypoints_for_angle, rep_cycle

W, H = 640, 480


def frame(angle):
    return {"type": "frame", "k": None if angle is None else keypoints_for_angle(angle).reshape(-1).tolist(), "w": W, "h": H}


class QuietAnalyzer:
    def analyze_frame(self, keypoints, frame_num=0):
        from src.form_assessment import FormStatus, OverallFormAssessment
        return OverallFormAssessment(overall_score=95.0, status=FormStatus.EXCELLENT)

    def reset(self):
        pass


@pytest.fixture
def db(tmp_db):
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-018")
        s.assign_program("P-017", "custom", "Knee Home Program", ["knee_extension", "squat"], 3,
                         date.today() - timedelta(days=7))
        s.set_goal("P-017", "Squat", target_reps=2)
    return tmp_db


@pytest.fixture
def registry():
    return live.LiveRegistry(limit=8)


NOW = [datetime.now()]


def start(db, registry, patient="P-017"):
    """A session on a clock the tests move: one fifteenth of a second per frame, like the browser."""
    return live.PortalLiveSession.start(db, patient, registry, pose_model="movenet-lightning-4",
                                        form_analyzer_factory=lambda base: QuietAnalyzer(), clock=lambda: NOW[0])


def feed(session, angles):
    state = None
    for a in angles:
        NOW[0] += timedelta(seconds=1 / 15)
        state = session.handle_frame(frame(a))
    return state


class TestGuidedSession:
    def test_two_exercises_are_recorded_as_a_home_session(self, db, registry):
        s = start(db, registry)
        first = s.state()
        assert (first["exercise"], first["index"], first["total"], first["target_reps"]) == ("Knee Extension", 1, 2, 10)
        state = feed(s, rep_cycle() * 3)
        assert state["rep_count"] == 3 and state["seen"] is True and state["set_complete"] is False
        state = s.next()
        assert (state["exercise"], state["index"], state["target_reps"], state["rep_count"]) == ("Squat", 2, 2, 0)
        state = feed(s, rep_cycle() * 2)
        assert state["rep_count"] == 2 and state["set_complete"] is True          # the goal's target of two is reached
        assert s.next()["exercise"] == "Squat"                                      # nothing after the last exercise
        ended = s.stop()
        assert ended["status"] == "completed" and ended["summary"]["total_reps"] == 5
        assert ended["summary"]["exercises"] == [{"name": "Knee Extension", "reps": 3}, {"name": "Squat", "reps": 2}]
        with SessionStore(db).open() as store:
            stored = store.load_session(s.session_id)
            assert (stored.patient_id, stored.source, stored.source_ref, stored.status) == ("P-017", "webcam", "home", "completed")
            assert capture_origin(stored) == "home" and stored.source_extras["pose_model"] == "movenet-lightning-4"
            assert stored.source_extras["fps_nominal"] == 15
            assert [(x.exercise_key, x.target_reps, len(x.reps)) for x in stored.sets] == [("knee_extension", 10, 3), ("squat", 2, 2)]
            assert [c.kind for c in stored.control_events] == ["switch"]
            events = [a.event for a in store.portal_audit_list("P-017")]
            assert events[0] == "live_end" and "live_start" in events

    def test_starts_at_the_first_exercise_not_done_today(self, db, registry):
        done = start(db, registry)
        feed(done, rep_cycle())
        done.stop()
        again = start(db, registry)
        assert again.state()["exercise"] == "Squat" and again.state()["index"] == 2
        again.stop()

    def test_nobody_in_view_and_bad_frames(self, db, registry):
        s = start(db, registry)
        assert feed(s, [None] * 5)["seen"] is False
        with pytest.raises(PortalError):
            s.handle_frame({"type": "frame", "k": [1.0] * 5, "w": W, "h": H})
        assert s.bad_frames == 1
        s.stop()

    def test_a_dropped_connection_keeps_the_reps(self, db, registry):
        s = start(db, registry)
        feed(s, rep_cycle() * 2)
        s.interrupt("portal_disconnected")
        with SessionStore(db).open() as store:
            stored = store.load_session(s.session_id)
            assert (stored.status, stored.interrupted_reason, stored.total_reps) == ("interrupted", "portal_disconnected", 2)
            assert store.portal_audit_list("P-017")[0].event == "live_interrupted"
        assert registry.active("P-017") is None

    def test_frames_after_the_end_are_ignored(self, db, registry):
        s = start(db, registry)
        s.stop()
        assert s.handle_frame(frame(170.0)) is None and s.stop()["status"] == "completed"


class TestLimits:
    def test_one_home_session_per_patient_and_a_total_cap(self, db):
        registry = live.LiveRegistry(limit=1)
        first = start(db, registry)
        with pytest.raises(live.LiveRefused) as second_device:
            start(db, registry)
        assert second_device.value.reason == "second_device"
        with SessionStore(db).open() as store:
            store.assign_program("P-018", "custom", "Other", ["squat"], 2, date.today())
        with pytest.raises(live.LiveRefused) as busy:
            start(db, registry, patient="P-018")
        assert busy.value.reason == "busy"
        first.stop()
        other = start(db, registry, patient="P-018")
        other.stop()

    def test_no_program_is_refused(self, db, registry):
        with pytest.raises(live.LiveRefused) as err:
            start(db, registry, patient="P-018")
        assert err.value.reason == "no_program"

    def test_another_patients_session_is_untouched(self, db):
        registry = live.LiveRegistry(limit=8)
        with SessionStore(db).open() as store:
            store.assign_program("P-018", "custom", "Other", ["squat"], 2, date.today())
        a, b = start(db, registry), start(db, registry, patient="P-018")
        feed(a, rep_cycle())
        a.interrupt("portal_disconnected")
        feed(b, rep_cycle())
        assert b.stop()["status"] == "completed" and b.stop()["summary"]["total_reps"] == 1

    def test_the_rate_cap_drops_frames_and_a_slow_device_is_noticed(self, db, registry):
        now = [datetime.now()]
        s = live.PortalLiveSession.start(db, "P-017", registry, form_analyzer_factory=lambda b: QuietAnalyzer(),
                                         clock=lambda: now[0])
        accepted = 0
        for _ in range(60):                                     # sixty frames inside one second
            accepted += s.handle_frame(frame(170.0)) is not None
            now[0] += timedelta(milliseconds=10)
        assert accepted == 20 and s.meter.dropped == 40
        for _ in range(8 * 8):                                  # eight seconds at eight frames per second
            now[0] += timedelta(seconds=1 / 8)
            state = s.handle_frame(frame(170.0))
        assert state["notice"] == "low_rate"
        s.stop()
        with SessionStore(db).open() as store:
            assert "low_rate" in store.portal_audit_list("P-017")[0].detail
