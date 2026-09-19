"""T006 — per-session, per-exercise measures derived from recorded reps (FR-001, FR-002)."""

import statistics
from datetime import datetime

from src.ptlog.measures import measure_series, measures_for_session
from src.ptlog.models import RepEvent

D0 = datetime(2026, 3, 23, 9, 15, 0)


class TestMeasuresForSession:
    def test_two_sets_of_one_exercise_combine_and_squat_separate(self, fixed_store, make_session):
        store, clock = fixed_store
        sid = make_session(store, clock, "unassigned", "Knee Extension", D0, [(95, 78.4, 3.1), (94, 79.1, 3.0)],
                           partials=1, target_reps=10,
                           extra_sets=[{"exercise": "Knee Extension", "reps": [(93, 77.8, 3.2)], "target_reps": 12},
                                       {"exercise": "Squat", "reps": [(88, 83.0, 2.4)], "safety_stop": "STOP: Knee hyperextension risk!"}])
        m = measures_for_session(store.load_session(sid))
        assert list(m) == ["Knee Extension", "Squat"]
        knee = m["Knee Extension"]
        assert knee.reps_completed == 3 and knee.target_reps == 12
        assert knee.avg_rom == round((78.4 + 79.1 + 77.8) / 3, 1)
        assert knee.avg_form == round((95 + 94 + 93) / 3, 1)
        assert knee.avg_duration == round((3.1 + 3.0 + 3.2) / 3, 2)
        assert knee.tempo_sd == round(statistics.pstdev([3.1, 3.0, 3.2]), 2)
        assert knee.partial_count == 1 and knee.partial_share == round(1 / 4 * 100, 1)
        assert knee.safety_stops == [] and knee.interrupted is False
        assert (knee.session_id, knee.patient_id, knee.status) == (sid, "unassigned", "completed")
        squat = m["Squat"]
        assert squat.reps_completed == 1 and squat.partial_share == 0.0
        assert len(squat.safety_stops) == 1 and squat.safety_stops[0][1].startswith("STOP")

    def test_out_of_range_rep_excluded_everywhere(self, fixed_store, make_session):
        store, clock = fixed_store
        sid = make_session(store, clock, "unassigned", "Knee Extension", D0, [(90, 78.0, 3.0)])
        set_id = store.load_session(sid).sets[0].id
        store.add_rep(set_id, RepEvent(2, 10.0, 88.0, 78.0, 3.0, 101.0, D0.isoformat(), 120))
        knee = measures_for_session(store.load_session(sid))["Knee Extension"]
        assert knee.reps_completed == 1 and knee.avg_form == 90.0

    def test_no_reps_gives_none_measures(self, fixed_store, make_session):
        store, clock = fixed_store
        sid = make_session(store, clock, "unassigned", "Knee Extension", D0, [])
        knee = measures_for_session(store.load_session(sid))["Knee Extension"]
        assert (knee.reps_completed, knee.avg_rom, knee.avg_form, knee.avg_duration, knee.tempo_sd, knee.partial_share) == (0, None, None, None, None, None)
        sid2 = make_session(store, clock, "unassigned", "Knee Extension", D0, [], partials=2)
        assert measures_for_session(store.load_session(sid2))["Knee Extension"].partial_share == 100.0

    def test_interrupted_flag(self, fixed_store, make_session):
        store, clock = fixed_store
        sid = make_session(store, clock, "unassigned", "Knee Extension", D0, [(90, 78.0, 3.0)], interrupted=True)
        assert measures_for_session(store.load_session(sid))["Knee Extension"].interrupted is True


class TestMeasureSeries:
    def test_oldest_first_and_skips_sessions_without_exercise(self, fixed_store, make_session):
        store, clock = fixed_store
        from datetime import timedelta
        a = make_session(store, clock, "unassigned", "Knee Extension", D0 - timedelta(days=2), [(90, 78.0, 3.0)])
        make_session(store, clock, "unassigned", "Squat", D0 - timedelta(days=1), [(88, 83.0, 2.4)])
        c = make_session(store, clock, "unassigned", "Knee Extension", D0, [(92, 80.0, 3.1)])
        series = measure_series(store.sessions_in_period("unassigned", None), "Knee Extension")
        assert [m.session_id for m in series] == [a, c]
