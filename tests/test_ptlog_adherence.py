"""T006 — adherence weeks and percentage (FR-009 … FR-012), pure computation."""

from datetime import date, datetime, timedelta

import pytest

from src.ptlog import adherence
from src.ptlog.models import Assignment

START = date(2026, 3, 1)


def assignment(start=START, end=None, per_week=3, keys=("knee_extension", "partial_squat")):
    return Assignment(1, "P-017", "custom", "Custom", list(keys), per_week, start.isoformat(),
                      end.isoformat() if end else None, "2026-03-01T00:00:00")


def sessions_for(store, clock, make_session, spec):
    """spec: list of (datetime, exercise, reps) -> loaded Session objects."""
    store.add_patient("P-017") if store.get_patient("P-017") is None else None
    ids = [make_session(store, clock, "P-017", ex, when, reps) for when, ex, reps in spec]
    return [store.load_session(i) for i in ids]


class TestStatusAndWeeks:
    def test_status(self):
        a = assignment()
        assert adherence.assignment_status(a, date(2026, 2, 20)) == "scheduled"
        assert adherence.assignment_status(a, date(2026, 3, 10)) == "active"
        assert adherence.assignment_status(assignment(end=date(2026, 3, 20)), date(2026, 3, 25)) == "completed"
        assert adherence.assignment_status(assignment(end=date(2026, 2, 28)), date(2026, 3, 25)) == "superseded"

    def test_week_bounds_and_index(self):
        a = assignment()
        assert adherence.week_bounds(a, 1) == (date(2026, 3, 1), date(2026, 3, 7))
        assert adherence.week_bounds(a, 3) == (date(2026, 3, 15), date(2026, 3, 21))
        assert adherence.week_index(a, date(2026, 3, 8)) == 2 and adherence.week_index(a, date(2026, 3, 1)) == 1


class TestCompute:
    def test_weeks_missed_in_progress_and_percentage(self, fixed_store, make_session):
        store, clock = fixed_store
        d = lambda day, hour=10: datetime(2026, 3, day, hour, 0)
        spec = [(d(1), "knee_extension", [(90, 78.0, 3.0)]), (d(3), "partial_squat", [(85, 40.0, 2.0)]),
                (d(5), "knee_extension", [(90, 78.0, 3.0)]),                                     # week 1: 3
                (d(9), "knee_extension", [(90, 78.0, 3.0)]),                                     # week 2: 1
                (d(22), "knee_extension", [(90, 78.0, 3.0)]), (d(23, 8), "knee_extension", [(90, 78.0, 3.0)])]  # week 4: 2
        sessions = sessions_for(store, clock, make_session, spec)
        a = adherence.compute(assignment(), sessions, date(2026, 3, 23))
        assert a.status == "active" and [w.index for w in a.weeks] == [1, 2, 3, 4]
        assert [w.recorded for w in a.weeks] == [3, 1, 0, 2]
        assert [w.missed for w in a.weeks] == [False, False, True, False]
        assert [w.in_progress for w in a.weeks] == [False, False, False, True]
        assert a.weeks[0].exercises_performed == ["knee_extension", "partial_squat"] and a.weeks[0].exercises_missing == []
        assert a.weeks[1].exercises_missing == ["partial_squat"]
        assert a.weeks[2].exercises_missing == ["knee_extension", "partial_squat"]
        assert a.percentage == 44 and a.note == ""

    def test_capped_at_planned(self, fixed_store, make_session):
        store, clock = fixed_store
        spec = [(datetime(2026, 3, day, 10, 0), "knee_extension", [(90, 78.0, 3.0)]) for day in (1, 2, 3, 4, 5)]
        a = adherence.compute(assignment(), sessions_for(store, clock, make_session, spec), date(2026, 3, 9))
        assert a.weeks[0].recorded == 5 and a.weeks[0].counted == 3 and a.percentage == 100

    def test_zero_rep_session_does_not_count(self, fixed_store, make_session):
        store, clock = fixed_store
        a = adherence.compute(assignment(), sessions_for(store, clock, make_session,
                                                          [(datetime(2026, 3, 2, 10, 0), "knee_extension", [])]), date(2026, 3, 9))
        assert a.weeks[0].recorded == 0 and a.weeks[0].missed is True and a.percentage == 0

    def test_start_day_and_last_day_belong_to_week_one(self, fixed_store, make_session):
        store, clock = fixed_store
        spec = [(datetime(2026, 3, 1, 0, 0), "knee_extension", [(90, 78.0, 3.0)]),
                (datetime(2026, 3, 7, 23, 59), "knee_extension", [(90, 78.0, 3.0)])]
        a = adherence.compute(assignment(), sessions_for(store, clock, make_session, spec), date(2026, 3, 9))
        assert a.weeks[0].recorded == 2

    def test_first_week_in_progress_and_no_program(self, fixed_store, make_session):
        store, clock = fixed_store
        a = adherence.compute(assignment(), sessions_for(store, clock, make_session,
                                                          [(datetime(2026, 3, 2, 10, 0), "knee_extension", [(90, 78.0, 3.0)])]), date(2026, 3, 3))
        assert a.percentage is None and a.note == "first week in progress" and a.weeks[0].in_progress
        none = adherence.compute(None, [], date(2026, 3, 3))
        assert none.percentage is None and none.note == "no program" and none.weeks == [] and none.status == "none"

    def test_scheduled_completed_superseded(self):
        assert adherence.compute(assignment(start=date(2026, 4, 1)), [], date(2026, 3, 23)).note == "starts on 2026-04-01"
        done = adherence.compute(assignment(end=date(2026, 3, 14)), [], date(2026, 3, 25))
        assert done.status == "completed" and done.note == "completed on 2026-03-14" and [w.index for w in done.weeks] == [1, 2] and done.percentage == 0
        sup = adherence.compute(assignment(end=date(2026, 2, 28)), [], date(2026, 3, 25))
        assert sup.status == "superseded" and sup.note == "superseded" and sup.weeks == [] and sup.percentage is None

    def test_window_is_last_four_complete_weeks(self):
        a = adherence.compute(assignment(), [], date(2026, 4, 10))     # 40 days in: 5 complete weeks + current
        assert [w.index for w in a.weeks] == [2, 3, 4, 5, 6] and a.weeks[-1].in_progress
        assert all(w.missed for w in a.weeks[:-1]) and a.percentage == 0
