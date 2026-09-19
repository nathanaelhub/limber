"""T027 — the seven attention rules with explicit thresholds and evidence (FR-014, FR-015)."""

from datetime import datetime, timedelta

from src.ptlog import flags
from src.ptlog.models import Flag, Goal, NotEvaluated, SessionMeasure

D0 = datetime(2026, 3, 1, 9, 0, 0)


def sm(i, form=None, rom=None, reps=8, target=10, partial=None, days=None, stops=(), exercise="Knee Extension"):
    start = D0 + timedelta(days=days if days is not None else i)
    return SessionMeasure(session_id=i, patient_id="P", start_time=start.isoformat(), status="completed",
                          interrupted=False, exercise_name=exercise, reps_completed=reps, target_reps=target,
                          avg_rom=rom, avg_form=form, avg_duration=2.0, tempo_sd=0.1, partial_count=0,
                          partial_share=partial, safety_stops=list(stops))


def series(**kw):
    """Build a series from parallel lists, e.g. series(form=[90, 86, 81, 75])."""
    n = max(len(v) for v in kw.values())
    return [sm(i + 1, **{k: v[i] for k, v in kw.items()}) for i in range(n)]


class TestFormDeclining:
    def test_each_lower_fires_with_evidence(self):
        f = flags.form_declining(series(form=[90, 86, 81, 75]))
        assert isinstance(f, Flag) and f.rule == "form_declining" and f.session_ids == [1, 2, 3, 4]
        for token in ("1", "2", "3", "4", "90", "86", "81", "75"):
            assert token in f.message

    def test_ten_point_drop_below_best_fires(self):
        assert flags.form_declining(series(form=[90, 88, 89, 78])).rule == "form_declining"

    def test_no_decline(self):
        assert flags.form_declining(series(form=[90, 86, 88, 85])) is None

    def test_not_enough_sessions(self):
        r = flags.form_declining(series(form=[90, 86, 81]))
        assert r == NotEvaluated("form_declining", "Knee Extension", 4, 3)

    def test_missing_values_are_skipped(self):
        assert flags.form_declining(series(form=[90, None, 81, 75])) == NotEvaluated("form_declining", "Knee Extension", 4, 3)


class TestRom:
    def test_regression_fires(self):
        f = flags.rom_regression(series(rom=[85, 84, 86, 70]))
        assert f.rule == "rom_regression" and "70" in f.message and "86" in f.message and f.session_ids == [1, 2, 3, 4]

    def test_regression_not_fired(self):
        assert flags.rom_regression(series(rom=[85, 84, 86, 80])) is None

    def test_plateau_fires_below_goal(self):
        goal = Goal("P", "Knee Extension", 110.0, None, "")
        f = flags.rom_plateau(series(rom=[80, 81, 79, 80]), goal)
        assert f.rule == "rom_plateau" and "110" in f.message and f.values["goal_rom"] == 110.0

    def test_plateau_needs_goal_and_below_goal(self):
        assert flags.rom_plateau(series(rom=[80, 81, 79, 80]), None) is None
        assert flags.rom_plateau(series(rom=[80, 81, 79, 80]), Goal("P", "Knee Extension", 80.0, None, "")) is None
        assert flags.rom_plateau(series(rom=[80, 81, 79, 84]), Goal("P", "Knee Extension", 110.0, None, "")) is None

    def test_plateau_not_evaluated_when_regression_fires(self):
        s = series(rom=[85, 84, 86, 70])
        result = flags.evaluate({"Knee Extension": s}, {"Knee Extension": Goal("P", "Knee Extension", 110.0, None, "")},
                                [m.start_time for m in s], 7, D0 + timedelta(days=5))
        rules = [f.rule for f in result.flags]
        assert "rom_regression" in rules and "rom_plateau" not in rules


class TestTargetReps:
    def test_fires_when_last_three_below_target(self):
        f = flags.target_reps_not_reached(series(reps=[10, 8, 7, 9]))
        assert f.rule == "target_reps_not_reached" and f.session_ids == [2, 3, 4] and "10" in f.message

    def test_not_fired_when_one_reached(self):
        assert flags.target_reps_not_reached(series(reps=[8, 10, 9])) is None

    def test_not_enough(self):
        assert flags.target_reps_not_reached(series(reps=[8, 7])) == NotEvaluated("target_reps_not_reached", "Knee Extension", 3, 2)


class TestPartials:
    def test_rising_fires(self):
        f = flags.rising_partial_reps(series(partial=[10, 10, 10, 30]))
        assert f.rule == "rising_partial_reps" and "30" in f.message and f.values["previous_mean"] == 10.0

    def test_below_minimum_share_not_fired(self):
        assert flags.rising_partial_reps(series(partial=[10, 10, 10, 20])) is None

    def test_none_treated_as_zero(self):
        assert flags.rising_partial_reps(series(partial=[None, None, None, 30])).rule == "rising_partial_reps"
        assert flags.rising_partial_reps(series(partial=[20, 20, 20, None])) is None


class TestSafetyAndGap:
    def test_safety_stop_per_session(self):
        s = series(form=[90, 90], stops=[[], [("2026-03-02T09:00:05", "STOP: Knee hyperextension risk!")]])
        result = flags.safety_stops(s)
        assert len(result) == 1 and result[0].rule == "safety_stop" and result[0].session_ids == [2]
        assert "Knee hyperextension" in result[0].message and "09:00:05" in result[0].message

    def test_practice_gap_between_sessions_and_to_now(self):
        starts = [(D0 + timedelta(days=d)).isoformat() for d in (0, 9, 14)]
        result = flags.practice_gap(starts, 7, D0 + timedelta(days=23))
        assert [f.values["days"] for f in result] == [9, 9]
        assert result[0].session_ids == [] or "9 days" in result[0].message
        assert flags.practice_gap(starts, 7, D0 + timedelta(days=16)) and len(flags.practice_gap([starts[0], (D0 + timedelta(days=5)).isoformat()], 7, D0 + timedelta(days=8))) == 0

    def test_single_session_measures_gap_to_now(self):
        result = flags.practice_gap([D0.isoformat()], 7, D0 + timedelta(days=8))
        assert len(result) == 1 and result[0].values["days"] == 8


class TestEvaluate:
    def test_aggregates_per_exercise_and_lists_not_evaluated(self):
        knee = series(form=[90, 86, 81, 75], rom=[80, 80, 80, 80], reps=[10, 10, 10, 10])
        squat = [sm(9, form=88, rom=90, reps=10, exercise="Squat", days=1), sm(10, form=87, rom=91, reps=10, exercise="Squat", days=2)]
        result = flags.evaluate({"Knee Extension": knee, "Squat": squat}, {}, [m.start_time for m in knee + squat], 7, D0 + timedelta(days=4))
        rules = sorted((f.rule, f.exercise) for f in result.flags)
        assert ("form_declining", "Knee Extension") in rules
        assert not any(r == "practice_gap" for r, _ in rules)
        assert NotEvaluated("form_declining", "Squat", 4, 2) in result.not_evaluated
        assert NotEvaluated("target_reps_not_reached", "Squat", 3, 2) in result.not_evaluated
