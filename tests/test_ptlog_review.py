"""Feature 002 — review over time: migration, store primitives, trends, reviews, flags, comparison, summary."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from src.ptlog import models
from src.ptlog.models import (
    METRIC_DEFINITIONS,
    GoalValidationError,
    PTLogError,
    ComparisonError,
    ReviewValidationError,
)
from src.ptlog.store import MIGRATIONS, SessionStore

D0 = datetime(2026, 3, 23, 9, 15, 0)


# ======================================================================================
# T003 — migration 2 and models
# ======================================================================================

class TestMigration2:
    def test_v1_database_upgrades_to_v2_with_data_intact(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        conn.executescript(MIGRATIONS[0][1])
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (1, '2026-01-01T00:00:00')")
        conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES ('unassigned', 'Unassigned', NULL, '2026-01-01T00:00:00', 1)")
        conn.execute("INSERT INTO sessions (patient_id, schema_version, source, source_ref, status, start_time, end_time, total_reps) "
                     "VALUES ('unassigned', 1, 'video', 'clip.mp4', 'completed', '2026-01-01T10:00:00', '2026-01-01T10:05:00', 3)")
        conn.commit(); conn.close()
        with SessionStore(tmp_db).open() as store:
            versions = [r[0] for r in store.conn.execute("SELECT version FROM schema_version ORDER BY version")]
            tables = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert store.load_session(1).total_reps == 3
        assert versions == [1, 2]
        assert {"reviews", "goals", "review_settings", "review_exports"} <= tables


class TestModels:
    def test_enums_and_definitions(self):
        assert models.NEXT_STEPS == ("continue", "progress", "regress", "hold")
        assert models.PERIODS == {"14d": 14, "30d": 30, "90d": 90, "all": None}
        assert models.REVIEW_EXPORT_FORMATS == ("review_report", "review_csv")
        for key, unit in (("avg_duration", "seconds"), ("tempo_sd", "seconds"), ("partial_share", "percent"),
                          ("reps_completed", "count"), ("avg_form", "score 0-100")):
            assert METRIC_DEFINITIONS[key]["unit"] == unit and len(METRIC_DEFINITIONS[key]["definition"]) > 10

    def test_dataclasses_exist(self):
        import dataclasses
        for name, fields in {
            "Review": {"session_id", "reviewed_at", "notes", "next_step"},
            "Goal": {"patient_id", "exercise_name", "target_rom", "target_reps", "set_at"},
            "ReviewSettings": {"patient_id", "gap_days"},
            "SessionMeasure": {"session_id", "patient_id", "start_time", "status", "interrupted", "exercise_name",
                               "reps_completed", "target_reps", "avg_rom", "avg_form", "avg_duration", "tempo_sd",
                               "partial_count", "partial_share", "safety_stops"},
            "Flag": {"rule", "exercise", "session_ids", "values", "message"},
            "NotEvaluated": {"rule", "exercise", "needed", "have"},
            "FlagResult": {"flags", "not_evaluated"},
            "Trend": {"exercise", "period", "points", "summary", "goal", "rom_progress_pct", "enough_for_trend"},
            "Comparison": {"exercise", "a", "b", "rows"},
            "ReviewSummary": {"patient_id", "period", "period_start", "generated_at", "gap_days", "trends", "flags", "goals", "sessions"},
        }.items():
            cls = getattr(models, name)
            assert fields <= {f.name for f in dataclasses.fields(cls)}, name

    def test_exceptions(self):
        for exc in (GoalValidationError, ComparisonError, ReviewValidationError):
            assert issubclass(exc, PTLogError)


# ======================================================================================
# T004 — store primitives: goals, settings, period reads, review exports
# ======================================================================================

class TestStorePrimitives:
    def test_goal_set_get_update_list_clear(self, fixed_store):
        store, clock = fixed_store
        store.add_patient("P-017")
        g = store.set_goal("P-017", "Knee Extension", target_rom=120, target_reps=10)
        assert (g.target_rom, g.target_reps, g.set_at) == (120.0, 10, "2026-03-23T09:15:00")
        g = store.set_goal("P-017", "Knee Extension", target_reps=12)
        assert (g.target_rom, g.target_reps) == (120.0, 12)
        assert store.get_goal("P-017", "Squat") is None
        store.set_goal("P-017", "Squat", target_rom=100)
        assert [x.exercise_name for x in store.list_goals("P-017")] == ["Knee Extension", "Squat"]
        assert store.clear_goal("P-017", "Squat") is True
        assert store.clear_goal("P-017", "Squat") is False

    @pytest.mark.parametrize("kwargs,rule", [
        ({"target_rom": 0}, "1–180"), ({"target_rom": 181}, "1–180"), ({"target_reps": 0}, "at least 1"), ({}, "at least one"),
    ])
    def test_goal_validation(self, fixed_store, kwargs, rule):
        store, _ = fixed_store
        store.add_patient("P-017")
        with pytest.raises(GoalValidationError) as exc:
            store.set_goal("P-017", "Knee Extension", **kwargs)
        assert rule in str(exc.value)

    def test_gap_days(self, fixed_store):
        store, _ = fixed_store
        store.add_patient("P-017")
        assert store.get_gap_days("P-017") == 7
        assert store.set_gap_days("P-017", 5) == 5
        assert store.get_gap_days("P-017") == 5
        for bad in (0, 91):
            with pytest.raises(PTLogError):
                store.set_gap_days("P-017", bad)

    def test_sessions_in_period_and_exercise_names(self, fixed_store, make_session):
        store, clock = fixed_store
        store.add_patient("P-017")
        a = make_session(store, clock, "P-017", "Squat", D0 - timedelta(days=40), [(85, 80, 2.4)])
        b = make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=10), [(90, 78, 3.0)])
        c = make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=1), [(92, 79, 3.1)])
        assert [s.id for s in store.sessions_in_period("P-017", None)] == [a, b, c]
        assert [s.id for s in store.sessions_in_period("P-017", D0 - timedelta(days=14))] == [b, c]
        assert store.sessions_in_period("P-017", None)[0].sets[0].reps[0].rom == 80.0
        assert store.exercise_names("P-017") == ["Squat", "Knee Extension"]

    def test_review_export_recorded_and_removed_with_patient(self, fixed_store, tmp_path):
        store, _ = fixed_store
        store.add_patient("P-017")
        f = tmp_path / "P-017_review_all_x.txt"; f.write_text("x")
        store.record_review_export("P-017", "review_report", "all", f)
        store.set_goal("P-017", "Knee Extension", target_rom=120)
        store.set_gap_days("P-017", 9)
        report = store.delete_patient("P-017")
        assert report.export_files == 1 and not f.exists()
        for table in ("goals", "review_settings", "review_exports"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


# ======================================================================================
# T011 — trends (User Story 1)
# ======================================================================================

from src.ptlog import review  # noqa: E402

KNEE_VALUES = [(85, 80.0, 2.4), (86, 84.0, 2.3), (88, 88.0, 2.2), (90, 92.0, 2.1)]
KNEE_DAYS = [40, 20, 10, 1]


def seed_knee_history(store, clock, make_session, patient="P-017"):
    store.add_patient(patient)
    return [make_session(store, clock, patient, "Knee Extension", D0 - timedelta(days=d), [v, v])
            for d, v in zip(KNEE_DAYS, KNEE_VALUES)]


class TestTrend:
    def test_points_ordered_with_values_and_summary(self, fixed_store, make_session):
        store, clock = fixed_store
        ids = seed_knee_history(store, clock, make_session)
        t = review.trend(store, "P-017", "Knee Extension", "all", now=D0)
        assert [p.session_id for p in t.points] == ids
        assert [p.avg_rom for p in t.points] == [80.0, 84.0, 88.0, 92.0]
        assert t.points[0].reps_completed == 2 and t.points[0].target_reps == 10
        assert t.enough_for_trend is True
        assert t.summary["avg_rom"] == {"first": 80.0, "latest": 92.0, "change": 12.0}
        assert t.summary["avg_form"] == {"first": 85.0, "latest": 90.0, "change": 5.0}
        assert t.summary["avg_duration"] == {"first": 2.4, "latest": 2.1, "change": -0.3}
        assert t.summary["reps_completed"] == {"first": 2, "latest": 2, "change": 0}
        assert t.goal is None and t.rom_progress_pct is None

    @pytest.mark.parametrize("period,expected", [("14d", 2), ("30d", 3), ("90d", 4), ("all", 4)])
    def test_period_filtering(self, fixed_store, make_session, period, expected):
        store, clock = fixed_store
        seed_knee_history(store, clock, make_session)
        assert len(review.trend(store, "P-017", "Knee Extension", period, now=D0).points) == expected

    def test_single_session_is_not_a_trend(self, fixed_store, make_session):
        store, clock = fixed_store
        store.add_patient("P-017")
        make_session(store, clock, "P-017", "Knee Extension", D0, [(90, 78.0, 3.0)])
        t = review.trend(store, "P-017", "Knee Extension", "all", now=D0)
        assert len(t.points) == 1 and t.enough_for_trend is False and t.summary == {}

    def test_interrupted_session_marked(self, fixed_store, make_session):
        store, clock = fixed_store
        store.add_patient("P-017")
        make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=1), [(90, 78.0, 3.0)])
        make_session(store, clock, "P-017", "Knee Extension", D0, [(90, 78.0, 3.0)], interrupted=True)
        t = review.trend(store, "P-017", "Knee Extension", "all", now=D0)
        assert [p.interrupted for p in t.points] == [False, True]

    def test_goal_progress(self, fixed_store, make_session):
        store, clock = fixed_store
        seed_knee_history(store, clock, make_session)
        store.set_goal("P-017", "Knee Extension", target_rom=120, target_reps=10)
        t = review.trend(store, "P-017", "Knee Extension", "all", now=D0)
        assert t.goal.target_rom == 120.0 and t.rom_progress_pct == 77
        store.set_goal("P-017", "Knee Extension", target_rom=80)
        assert review.trend(store, "P-017", "Knee Extension", "all", now=D0).rom_progress_pct == 100

    def test_exercise_never_done_gives_empty_trend_and_names(self, fixed_store, make_session):
        store, clock = fixed_store
        seed_knee_history(store, clock, make_session)
        t = review.trend(store, "P-017", "Squat", "all", now=D0)
        assert t.points == [] and t.enough_for_trend is False
        assert review.exercise_names(store, "P-017") == ["Knee Extension"]

    def test_same_day_sessions_ordered_by_start_and_side_variants_separate(self, fixed_store, make_session):
        store, clock = fixed_store
        store.add_patient("P-017")
        later = make_session(store, clock, "P-017", "Knee Extension", D0.replace(hour=10), [(90, 78.0, 3.0)])
        earlier = make_session(store, clock, "P-017", "Knee Extension", D0.replace(hour=9), [(88, 76.0, 3.0)])
        make_session(store, clock, "P-017", "Knee Extension (Right)", D0.replace(hour=11), [(70, 60.0, 3.0)])
        t = review.trend(store, "P-017", "Knee Extension", "all", now=D0.replace(hour=12))
        assert [p.session_id for p in t.points] == [earlier, later]

    def test_period_start(self):
        assert review.period_start("14d", D0) == D0 - timedelta(days=14)
        assert review.period_start("all", D0) is None
        with pytest.raises(ValueError):
            review.period_start("2w", D0)
