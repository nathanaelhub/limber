"""Feature 007 T011 — what the patient sees: today's program, this week, and the streak."""

import json
from datetime import datetime, timedelta

import pytest

from src.portal import viewmodels as vm
from src.ptlog.models import AdherenceWeek

D0 = datetime(2026, 3, 23, 9, 15, 0)
REP = [(90.0, 80.0, 2.4)]
ALLOWED_TODAY = {"patient_id", "date", "program", "exercises", "week", "streak_weeks", "message", "notes"}
FORBIDDEN = ("flag", "review", "next_step", "threshold", "label")


def week(index, recorded, planned=2, in_progress=False):
    return AdherenceWeek(index=index, start="", end="", planned=planned, recorded=recorded,
                         counted=min(recorded, planned), in_progress=in_progress, missed=recorded == 0 and not in_progress)


class TestStreak:
    def test_counts_back_from_the_latest_complete_week(self):
        assert vm.streak([week(1, 1), week(2, 2), week(3, 2), week(4, 3)]) == 3
        assert vm.streak([week(1, 2), week(2, 0), week(3, 2)]) == 1
        assert vm.streak([week(1, 2), week(2, 1)]) == 0
        assert vm.streak([]) == 0

    def test_week_in_progress_extends_but_never_breaks(self):
        done = [week(1, 2), week(2, 2)]
        assert vm.streak(done + [week(3, 1, in_progress=True)]) == 2
        assert vm.streak(done + [week(3, 2, in_progress=True)]) == 3
        assert vm.streak([week(1, 0, in_progress=True)]) == 0


@pytest.fixture
def patient(fixed_store, make_session):
    store, clock = fixed_store
    store.add_patient("P-017", label="Post-op knee", notes="prefers mornings")
    store.add_patient("P-018", label="Other person")
    store.assign_program("P-017", "custom", "Knee Home Program", ["knee_extension", "squat"], 2,
                         (D0 - timedelta(days=28)).date())
    # weeks 1-4 complete with 1, 2, 2, 3 sessions; week 5 in progress
    for days in (27, 20, 19, 13, 12, 6, 5, 4):
        make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=days), REP)
    make_session(store, clock, "P-018", "Squat", D0 - timedelta(days=1), REP)
    return store, clock


class TestTodayView:
    def test_program_targets_and_week(self, patient):
        store, _ = patient
        store.set_goal("P-017", "Squat", target_reps=15)
        view = vm.today_view(store, "P-017", now=D0)
        assert set(view) <= ALLOWED_TODAY and view["patient_id"] == "P-017" and view["date"] == "2026-03-23"
        assert view["program"] == {"name": "Knee Home Program", "sessions_per_week": 2}
        assert view["exercises"] == [
            {"key": "knee_extension", "name": "Knee Extension", "target_reps": 10, "done_today": False},
            {"key": "squat", "name": "Squat", "target_reps": 15, "done_today": False}]       # the goal's target wins
        assert view["week"] == {"done": 0, "planned": 2} and view["streak_weeks"] == 3 and view["message"] is None

    def test_done_today_needs_a_counted_rep_today(self, patient, make_session):
        store, clock = patient
        make_session(store, clock, "P-017", "Squat", D0 - timedelta(hours=1), [])               # no reps: not done
        make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(hours=2), REP)
        view = vm.today_view(store, "P-017", now=D0)
        assert [e["done_today"] for e in view["exercises"]] == [True, False]
        assert view["week"] == {"done": 1, "planned": 2} and view["streak_weeks"] == 3
        make_session(store, clock, "P-017", "Squat", D0 - timedelta(minutes=30), REP)
        view = vm.today_view(store, "P-017", now=D0)
        assert [e["done_today"] for e in view["exercises"]] == [True, True]
        assert view["week"] == {"done": 2, "planned": 2} and view["streak_weeks"] == 4

    def test_no_program(self, patient):
        store, _ = patient
        view = vm.today_view(store, "P-018", now=D0)
        assert view["program"] is None and view["exercises"] == [] and view["week"] is None
        assert view["streak_weeks"] is None and "not assigned a program" in view["message"]

    def test_exercise_missing_from_the_configuration_is_skipped_with_a_note(self, patient):
        store, _ = patient
        # The store validates keys when assigning, so an unknown key can only appear when the
        # configuration changed afterwards; simulate that on the stored assignment.
        store.conn.execute("UPDATE assignments SET exercise_keys = ? WHERE patient_id = 'P-017'",
                           (json.dumps(["knee_extension", "retired_exercise"]),))
        store.conn.commit()
        view = vm.today_view(store, "P-017", now=D0)
        assert [e["key"] for e in view["exercises"]] == ["knee_extension"]
        assert view["notes"] == ["One exercise in your program is no longer available and was skipped."]

    def test_only_the_patients_own_data(self, patient):
        store, _ = patient
        text = json.dumps(vm.today_view(store, "P-017", now=D0)).lower()
        assert "p-018" not in text and "post-op" not in text and "mornings" not in text
        assert not any(word in text for word in FORBIDDEN)

    def test_unknown_patient(self, patient):
        from src.ptlog.models import PatientNotFoundError
        store, _ = patient
        with pytest.raises(PatientNotFoundError):
            vm.today_view(store, "P-404", now=D0)
