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


class TestTrendRendering:
    def _trend(self, store, clock, make_session, goal=False):
        from datetime import datetime, timedelta
        from src.ptlog import review
        d0 = datetime(2026, 3, 23, 9, 15, 0)
        store.add_patient("P-017")
        make_session(store, clock, "P-017", "Knee Extension", d0 - timedelta(days=10), [(85, 80.0, 2.4), (85, 80.0, 2.4)], target_reps=10)
        make_session(store, clock, "P-017", "Knee Extension", d0, [(88, 92.0, 2.1), (88, 92.0, 2.1)], target_reps=10)
        if goal:
            store.set_goal("P-017", "Knee Extension", target_rom=120, target_reps=10)
        return review.trend(store, "P-017", "Knee Extension", "all", now=d0)

    def test_table_rows_carry_units(self, fixed_store, make_session):
        store, clock = fixed_store
        rows = views.trend_table_rows(self._trend(store, clock, make_session))
        assert rows[0]["date"] == "2026-03-13 09:15" and rows[0]["reps"] == "2/10"
        assert rows[0]["avg_form"] == "85.0/100" and rows[0]["avg_rom"] == "80.0°"
        assert rows[0]["avg_duration"] == "2.40 s" and rows[0]["tempo_sd"] == "0.00 s"
        assert rows[0]["partial_share"] == "0.0%" and rows[0]["status"] == "completed"
        assert views.fmt_measure("avg_rom", None) == "not available"

    def test_summary_lines(self, fixed_store, make_session):
        store, clock = fixed_store
        lines = views.trend_summary_lines(self._trend(store, clock, make_session, goal=True))
        assert "avg ROM: 80.0° → 92.0° (+12.0°)" in lines
        assert "avg form: 85.0/100 → 88.0/100 (+3.0)" in lines
        assert "Goal: ROM 120° (77% of goal) | reps 10" in lines

    def test_single_session_message(self, fixed_store, make_session):
        from datetime import datetime
        from src.ptlog import review
        store, clock = fixed_store
        store.add_patient("P-017")
        make_session(store, clock, "P-017", "Knee Extension", datetime(2026, 3, 23, 9, 15), [(85, 80.0, 2.4)])
        lines = views.trend_summary_lines(review.trend(store, "P-017", "Knee Extension", "all"))
        assert "A trend needs at least two sessions." in lines


class TestReviewLines:
    def test_pending_and_reviewed(self, fixed_store, make_session):
        from datetime import datetime
        from src.ptlog import review
        store, clock = fixed_store
        store.add_patient("P-017")
        sid = make_session(store, clock, "P-017", "Knee Extension", datetime(2026, 3, 23, 9, 15), [(90, 78.0, 3.0)])
        lines = views.review_lines(review.session_review_view(store, sid))
        assert lines[0] == "REVIEW: pending"
        assert any(l.startswith("Knee Extension: 1/10 reps | avg form 90.0/100 | avg ROM 78.0°") for l in lines)
        clock.set(datetime(2026, 3, 24, 10, 12))
        store.set_review(sid, "progress", "post-op week 3")
        lines = views.review_lines(review.session_review_view(store, sid))
        assert lines[0] == "REVIEW: reviewed 2026-03-24 10:12 | next step: progress | notes: post-op week 3"
