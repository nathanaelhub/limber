"""T028 — unit-labelled rendering for CLI and web, and the trend loader for the legacy analysis code."""

import pytest

from src.ptlog import views
from src.ptlog.models import METRIC_DEFINITIONS, ControlEvent, ExerciseSetInfo, FormEvent, PartialRepEvent, RepEvent
from src.ptlog.store import SessionStore

KNEE = ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0)
SQUAT = ExerciseSetInfo("squat", "Squat", "bilateral", 10, 170.0, 90.0)


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        yield s


def seed(store, patient="unassigned"):
    sid = store.start_session(patient, "webcam", "0", extras={"camera_id": 0, "imgsz": 320, "frame_skip": 1})
    s1 = store.open_set(sid, KNEE)
    store.add_rep(s1, RepEvent(1, 10.2, 88.6, 78.4, 3.1, 95.0, "2026-03-23T09:15:02", 60))
    store.add_partial_rep(s1, PartialRepEvent("reversed_early", 95.0, 135.2, 40.2, 1.3, "2026-03-23T09:15:05", 150))
    store.add_form_event(s1, FormEvent("warning", "warning", "Keep your back straight against the chair",
                                       "2026-03-23T09:15:05.500000", 165, body_part="trunk"))
    store.close_set(s1, "2026-03-23T09:15:06.666667")
    store.add_control_event(sid, ControlEvent("switch", "2026-03-23T09:15:06.666667", 200,
                                              from_exercise="Knee Extension", to_exercise="Squat"))
    s2 = store.open_set(sid, SQUAT)
    store.add_rep(s2, RepEvent(1, 88.0, 171.0, 83.0, 2.4, 88.0, "2026-03-23T09:15:08", 240))
    store.add_control_event(sid, ControlEvent("reset", "2026-03-23T09:15:10.666667", 320, rep_count_at_reset=1))
    return sid


class TestEventLogLines:
    def test_lines_carry_units(self, store):
        sid = seed(store)
        store.end_session(sid)
        lines = views.event_log_lines(store, sid)
        assert lines[0].startswith("[09:15:00] SESSION START | Knee Extension (left) | target 10")
        assert "[09:15:02] REP 1 | ROM 78.4° | form 95/100 | 3.1 s | 10.2°–88.6°" in lines
        assert "[09:15:05] PARTIAL REP | reversed_early | ROM 40.2° | 95.0°–135.2° | 1.3 s" in lines
        assert "[09:15:05] FORM warning | Keep your back straight against the chair" in lines
        assert "[09:15:06] SWITCH | Knee Extension -> Squat" in lines
        assert "[09:15:10] RESET | Squat | count 1" in lines
        assert lines[-2].startswith("[09:15:10] SESSION END | 2 reps | avg form 91.5/100 | avg ROM 80.7°")
        assert lines[-1] == "STATUS: completed"

    def test_interrupted_status_line(self, store):
        sid = seed(store)
        store._interrupt_running("recovered_on_open")
        lines = views.event_log_lines(store, sid)
        assert lines[-1] == "STATUS: interrupted"
        assert any("SESSION INTERRUPTED | 2 reps | avg form 91.5/100" in l for l in lines)   # summary computed from events
        assert not any("SESSION END" in l for l in lines)


class TestHeaderAndTable:
    def test_header_not_available_for_null_averages(self, store):
        sid = store.start_session("unassigned", "video", "clip.mp4")
        store.open_set(sid, KNEE)
        session = store.end_session(sid)
        header = views.session_header_lines(session)
        assert any("not available" in h for h in header)
        assert any("video (clip.mp4)" in h for h in header)

    def test_table_rows(self, store):
        sid = seed(store)
        store.end_session(sid)
        rows = views.session_table_rows(store)
        assert rows[0]["id"] == sid
        assert rows[0]["exercises"] == "Knee Extension, Squat"
        assert rows[0]["total_reps"] == 2
        assert rows[0]["avg_form_score"] == "91.5/100"
        assert rows[0]["status"] == "completed"
        assert rows[0]["date"] == "2026-03-23 09:15"

    @pytest.mark.parametrize("field", ["rom", "form_score", "duration_seconds", "min_angle", "max_angle",
                                       "avg_form_score", "avg_rom", "total_reps", "target_reps"])
    def test_every_displayed_metric_has_a_definition(self, field):
        label = views.metric_label(field)
        assert METRIC_DEFINITIONS[field]["unit"] in label


class TestTrendLoader:
    def test_builds_session_data_for_legacy_trend_math(self, store):
        from src.session_tracker import SessionTracker
        store.add_patient("P-017")
        sid = seed(store, "P-017")
        store.end_session(sid)
        history = views.load_session_data_for_trends(store, "P-017")
        assert len(history) == 1
        sd = history[0]
        assert sd.patient_id == "P-017" and sd.date == "2026-03-23" and sd.session_id == "P-017_20260323_091500"
        assert [e.exercise_name for e in sd.exercises] == ["Knee Extension", "Squat"]
        knee = sd.exercises[0]
        assert (knee.reps_completed, knee.target_reps, knee.avg_form_score, knee.min_rom, knee.max_rom, knee.rom_range, knee.avg_rep_duration) == \
               (1, 10, 95.0, 10.2, 88.6, 78.4, 3.1)
        assert "Knee Extension: Completed only 1/10 reps" in sd.flags_for_review
        assert sd.overall_form_score == 91.5
        # the legacy trend math consumes it unchanged (two sessions needed for a trend)
        tracker = SessionTracker.__new__(SessionTracker)
        tracker.session_history = history + history
        assert tracker.calculate_progress("Knee Extension", days_back=36500) is not None
