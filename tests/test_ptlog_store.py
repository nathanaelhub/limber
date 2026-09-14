"""T005 (foundation) — schema, pragmas, migrations, built-in patient, path resolution."""

import os
import sqlite3
from pathlib import Path

import pytest

from src.ptlog.store import MIGRATIONS, SessionStore, default_db_path

EXPECTED_TABLES = {
    "patients", "sessions", "exercise_sets", "reps", "partial_reps", "form_events",
    "control_events", "frame_samples", "exports", "import_ledger", "schema_version",
}


def _tables(db_path: Path) -> set:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows if not r[0].startswith("sqlite_")}


class TestOpen:
    def test_creates_all_tables(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open():
            pass
        assert EXPECTED_TABLES <= _tables(tmp_db)

    def test_schema_version_is_one(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as store:
            rows = store.conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        assert [r[0] for r in rows] == [1]
        assert MIGRATIONS[0][0] == 1

    def test_pragmas(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as store:
            assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert store.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert store.conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL

    def test_builtin_unassigned_patient_exists_and_is_first(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as store:
            patients = store.list_patients()
            unassigned = store.get_patient("unassigned")
        assert unassigned is not None
        assert unassigned.is_builtin is True
        assert patients[0].id == "unassigned"

    def test_open_twice_is_idempotent(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open():
            pass
        with SessionStore(tmp_db, clock=fake_clock).open() as store:
            versions = store.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            unassigned_rows = store.conn.execute(
                "SELECT COUNT(*) FROM patients WHERE id='unassigned'").fetchone()[0]
        assert versions == 1
        assert unassigned_rows == 1

    def test_get_unknown_patient_returns_none(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as store:
            assert store.get_patient("nope") is None

    def test_creates_parent_directory(self, tmp_path, fake_clock):
        nested = tmp_path / "deeper" / "data" / "ptassist.db"
        with SessionStore(nested, clock=fake_clock).open():
            pass
        assert nested.exists()


class TestDefaultDbPath:
    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PTASSIST_DB", str(tmp_path / "x.db"))
        assert default_db_path() == tmp_path / "x.db"

    def test_default_under_repo_data_dir(self, monkeypatch):
        monkeypatch.delenv("PTASSIST_DB", raising=False)
        p = default_db_path()
        assert p.name == "ptassist.db"
        assert p.parent.name == "data"
        assert (p.parent.parent / "analyze.py").exists()


# ======================================================================================
# T010 — session writes (User Story 1)
# ======================================================================================

import json  # noqa: E402

from src.ptlog.models import (  # noqa: E402
    ControlEvent,
    ExerciseSetInfo,
    FormEvent,
    FrameSample,
    PartialRepEvent,
    RepEvent,
)

KNEE = ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0)
SQUAT = ExerciseSetInfo("squat", "Squat", "bilateral", 10, 170.0, 90.0)


def _rep(n=1, ts="2026-03-23T09:15:08", form=95.0, rom=78.4, frame=240, **kw):
    base = dict(rep_number=n, min_angle=10.2, max_angle=88.6, rom=rom, duration_seconds=3.1,
                form_score=form, timestamp=ts, frame_num=frame)
    base.update(kw)
    return RepEvent(**base)


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        yield s


class TestSessionWrites:
    def test_start_session_is_running_with_schema_version(self, store):
        sid = store.start_session("unassigned", "webcam", "0")
        row = store.conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        assert row["status"] == "running"
        assert row["schema_version"] == 1
        assert row["patient_id"] == "unassigned"
        assert row["source"] == "webcam"
        assert row["source_ref"] == "0"
        assert row["start_time"] == "2026-03-23T09:15:00"
        assert row["end_time"] is None

    def test_start_session_stores_extras_as_json(self, store):
        sid = store.start_session("unassigned", "webcam", "0",
                                  extras={"camera_id": 0, "imgsz": 320, "frame_skip": 1})
        raw = store.conn.execute("SELECT source_extras FROM sessions WHERE id = ?", (sid,)).fetchone()[0]
        assert json.loads(raw) == {"camera_id": 0, "imgsz": 320, "frame_skip": 1}

    def test_start_session_unknown_patient_raises(self, store):
        from src.ptlog.models import PatientNotFoundError
        with pytest.raises(PatientNotFoundError):
            store.start_session("ghost", "webcam", "0")

    def test_open_set_stores_metadata_and_ordinal(self, store):
        sid = store.start_session("unassigned", "video", "clip.mp4")
        s1 = store.open_set(sid, KNEE)
        s2 = store.open_set(sid, SQUAT)
        rows = store.conn.execute(
            "SELECT * FROM exercise_sets WHERE session_id = ? ORDER BY ordinal", (sid,)).fetchall()
        assert [r["id"] for r in rows] == [s1, s2]
        assert [r["ordinal"] for r in rows] == [1, 2]
        k = rows[0]
        assert (k["exercise_key"], k["exercise_name"], k["side"], k["target_reps"],
                k["up_angle"], k["down_angle"]) == ("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0)
        assert k["start_time"] is not None and k["end_time"] is None

    def test_close_set_sets_end_time_even_with_zero_reps(self, store):
        sid = store.start_session("unassigned", "webcam", "0")
        set_id = store.open_set(sid, KNEE)
        store.close_set(set_id)
        row = store.conn.execute("SELECT end_time FROM exercise_sets WHERE id = ?", (set_id,)).fetchone()
        assert row["end_time"] is not None

    def test_each_event_is_visible_to_another_connection_immediately(self, store, tmp_db):
        sid = store.start_session("unassigned", "webcam", "0")
        set_id = store.open_set(sid, KNEE)
        other = sqlite3.connect(tmp_db)

        def count(table):
            return other.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        store.add_rep(set_id, _rep())
        assert count("reps") == 1
        store.add_partial_rep(set_id, PartialRepEvent("reversed_early", 95.0, 135.2, 40.2, 1.3,
                                                      "2026-03-23T09:15:12", 300))
        assert count("partial_reps") == 1
        store.add_form_event(set_id, FormEvent("warning", "warning", "Keep your back straight",
                                               "2026-03-23T09:15:13", 330, body_part="trunk"))
        assert count("form_events") == 1
        store.add_control_event(sid, ControlEvent("reset", "2026-03-23T09:15:14", 360, rep_count_at_reset=1))
        assert count("control_events") == 1
        other.close()

    def test_add_frame_samples_writes_batch(self, store):
        sid = store.start_session("unassigned", "webcam", "0")
        set_id = store.open_set(sid, KNEE)
        store.add_frame_samples(set_id, [
            FrameSample(15, "2026-03-23T09:15:00.500000", 92.0, "down", 0),
            FrameSample(30, "2026-03-23T09:15:01", 130.5, "idle", 0),
            FrameSample(45, "2026-03-23T09:15:01.500000", 168.9, "up", 0),
        ])
        n = store.conn.execute("SELECT COUNT(*) FROM frame_samples WHERE set_id = ?", (set_id,)).fetchone()[0]
        assert n == 3

    def test_end_session_summary_equals_recomputation(self, store):
        sid = store.start_session("unassigned", "webcam", "0")
        set_id = store.open_set(sid, KNEE)
        for n, (form, rom) in enumerate([(95.0, 78.4), (94.0, 79.1), (93.0, 77.8)], 1):
            store.add_rep(set_id, _rep(n, form=form, rom=rom, frame=60 * n))
        session = store.end_session(sid)
        assert session.status == "completed"
        assert session.end_time is not None
        assert session.duration_seconds is not None and session.duration_seconds >= 0
        assert session.total_reps == 3
        assert session.avg_form_score == 94.0
        assert session.avg_rom == round((78.4 + 79.1 + 77.8) / 3, 1)
        row = store.conn.execute("SELECT status, total_reps, avg_form_score, avg_rom FROM sessions WHERE id = ?", (sid,)).fetchone()
        assert tuple(row) == ("completed", 3, 94.0, session.avg_rom)
        set_row = store.conn.execute("SELECT end_time FROM exercise_sets WHERE id = ?", (set_id,)).fetchone()
        assert set_row["end_time"] is not None

    def test_out_of_range_rep_stored_flagged_and_excluded(self, store):
        sid = store.start_session("unassigned", "webcam", "0")
        set_id = store.open_set(sid, KNEE)
        store.add_rep(set_id, _rep(1, form=101.0))
        store.add_rep(set_id, _rep(2, form=90.0, rom=80.0))
        flagged = store.conn.execute("SELECT out_of_range FROM reps WHERE rep_number = 1").fetchone()[0]
        assert flagged == 1
        session = store.end_session(sid)
        assert session.total_reps == 1
        assert session.avg_form_score == 90.0
        assert session.avg_rom == 80.0

    def test_zero_reps_gives_null_averages(self, store):
        sid = store.start_session("unassigned", "webcam", "0")
        store.open_set(sid, KNEE)
        session = store.end_session(sid)
        assert session.total_reps == 0
        assert session.avg_form_score is None
        assert session.avg_rom is None

    def test_start_marks_previous_running_session_interrupted(self, store):
        s1 = store.start_session("unassigned", "webcam", "0")
        set_id = store.open_set(s1, KNEE)
        store.add_rep(set_id, _rep(1, ts="2026-03-23T09:15:08"))
        s2 = store.start_session("unassigned", "webcam", "0")
        row = store.conn.execute("SELECT status, end_time, interrupted_reason, total_reps FROM sessions WHERE id = ?", (s1,)).fetchone()
        assert row["status"] == "interrupted"
        assert row["end_time"] == "2026-03-23T09:15:08"
        assert row["interrupted_reason"]
        assert row["total_reps"] == 1
        assert store.conn.execute("SELECT status FROM sessions WHERE id = ?", (s2,)).fetchone()[0] == "running"

    def test_two_sessions_in_same_second_get_distinct_ids(self, tmp_db):
        from tests.fixtures.golden.sequence import FixedClock
        with SessionStore(tmp_db, clock=FixedClock()).open() as s:
            a = s.start_session("unassigned", "webcam", "0")
            b = s.start_session("unassigned", "webcam", "0")
            starts = s.conn.execute("SELECT start_time FROM sessions ORDER BY id").fetchall()
        assert a != b
        assert starts[0][0] == starts[1][0]


# ======================================================================================
# T022 — patients (User Story 2)
# ======================================================================================

from src.ptlog.models import (  # noqa: E402
    BuiltinPatientError,
    DuplicatePatientError,
    PatientNotFoundError,
    PatientValidationError,
)


class TestPatients:
    def test_add_patient_stores_fields(self, store):
        p = store.add_patient("P-017", label="Post-op knee", notes="Week 3 after surgery")
        assert (p.id, p.label, p.notes, p.is_builtin, p.session_count) == ("P-017", "Post-op knee", "Week 3 after surgery", False, 0)
        assert p.created_at == "2026-03-23T09:15:00"
        assert store.get_patient("P-017").label == "Post-op knee"

    def test_add_patient_validates(self, store):
        with pytest.raises(PatientValidationError):
            store.add_patient("John Smith")
        with pytest.raises(PatientValidationError):
            store.add_patient("P-018", label="x" * 61)

    def test_duplicate_id_is_case_insensitive(self, store):
        store.add_patient("P-017")
        with pytest.raises(DuplicatePatientError):
            store.add_patient("p-017")

    def test_update_patient_changes_label_and_notes_only(self, store):
        store.add_patient("P-017", label="old", notes="n1")
        p = store.update_patient("P-017", label="new")
        assert (p.label, p.notes) == ("new", "n1")
        p = store.update_patient("P-017", notes="n2")
        assert (p.label, p.notes) == ("new", "n2")
        with pytest.raises(PatientNotFoundError):
            store.update_patient("ghost", label="x")

    def test_list_patients_order_and_counts(self, store):
        store.add_patient("zeta")
        store.add_patient("Alpha")
        sid = store.start_session("zeta", "webcam", "0")
        store.end_session(sid)
        ids = [p.id for p in store.list_patients()]
        assert ids == ["unassigned", "Alpha", "zeta"]
        zeta = store.get_patient("zeta")
        assert zeta.session_count == 1 and zeta.last_session_at == "2026-03-23T09:15:00"

    def test_delete_patient_cascades_and_removes_export_files(self, store, tmp_path):
        store.add_patient("P-017")
        sid = store.start_session("P-017", "webcam", "0")
        set_id = store.open_set(sid, KNEE)
        store.add_rep(set_id, _rep(1))
        store.add_partial_rep(set_id, PartialRepEvent("reversed_early", 95.0, 135.2, 40.2, 1.3, "2026-03-23T09:15:12", 300))
        store.add_form_event(set_id, FormEvent("warning", "warning", "Keep your back straight", "2026-03-23T09:15:13", 330))
        store.add_control_event(sid, ControlEvent("reset", "2026-03-23T09:15:14", 360, rep_count_at_reset=1))
        store.add_frame_samples(set_id, [FrameSample(15, "2026-03-23T09:15:00.5", 92.0, "down", 0)])
        store.end_session(sid)
        f1, f2 = tmp_path / "a.csv", tmp_path / "b.txt"
        f1.write_text("x"); f2.write_text("y")
        store.record_export(sid, "csv_report", f1)
        store.record_export(sid, "pta_log", f2)
        other_sid = store.start_session("unassigned", "webcam", "0")
        store.end_session(other_sid)

        report = store.delete_patient("P-017")

        assert (report.patient_id, report.sessions, report.events, report.export_files) == ("P-017", 1, 4, 2)
        assert not f1.exists() and not f2.exists()
        for table in ("exercise_sets", "reps", "partial_reps", "form_events", "control_events", "frame_samples", "exports"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        assert store.get_patient("P-017") is None
        assert store.get_patient("unassigned").session_count == 1

    def test_delete_builtin_and_unknown_refused(self, store):
        with pytest.raises(BuiltinPatientError):
            store.delete_patient("unassigned")
        with pytest.raises(PatientNotFoundError):
            store.delete_patient("ghost")

    def test_reassign_session(self, store):
        store.add_patient("P-017")
        sid = store.start_session("unassigned", "video", "clip.mp4")
        store.end_session(sid)
        store.reassign_session(sid, "P-017")
        assert store.conn.execute("SELECT patient_id FROM sessions WHERE id = ?", (sid,)).fetchone()[0] == "P-017"
        assert store.get_patient("P-017").session_count == 1
        assert store.get_patient("unassigned").session_count == 0
        with pytest.raises(PatientNotFoundError):
            store.reassign_session(sid, "ghost")
        from src.ptlog.models import SessionNotFoundError
        with pytest.raises(SessionNotFoundError):
            store.reassign_session(999, "P-017")


# ======================================================================================
# T027 — reads (User Story 3)
# ======================================================================================

import time  # noqa: E402

from src.ptlog.models import SessionNotFoundError  # noqa: E402


def _seed_two_set_session(store, patient="unassigned"):
    sid = store.start_session(patient, "webcam", "0")
    s1 = store.open_set(sid, KNEE)
    store.add_rep(s1, _rep(1, ts="2026-03-23T09:15:02", form=95.0, rom=78.4, frame=60))
    store.add_partial_rep(s1, PartialRepEvent("reversed_early", 95.0, 135.2, 40.2, 1.3, "2026-03-23T09:15:05", 150))
    store.add_form_event(s1, FormEvent("warning", "warning", "Keep your back straight against the chair",
                                       "2026-03-23T09:15:05.500000", 165, body_part="trunk"))
    store.add_partial_rep(s1, PartialRepEvent("interrupted", 100.0, 140.0, 40.0, 0.8, "2026-03-23T09:15:06.666667", 200))
    store.close_set(s1, "2026-03-23T09:15:06.666667")
    store.add_control_event(sid, ControlEvent("switch", "2026-03-23T09:15:06.666667", 200,
                                              from_exercise="Knee Extension", to_exercise="Squat"))
    s2 = store.open_set(sid, SQUAT)
    store.add_rep(s2, _rep(1, ts="2026-03-23T09:15:08", form=88.0, rom=83.0, frame=240))
    store.add_control_event(sid, ControlEvent("reset", "2026-03-23T09:15:10.666667", 320, rep_count_at_reset=1))
    store.add_rep(s2, _rep(1, ts="2026-03-23T09:15:12.666667", form=90.0, rom=81.0, frame=380))
    return sid


class TestReads:
    def test_list_sessions_newest_first_with_summary_columns(self, store, fake_clock):
        store.add_patient("P-017")
        a = store.start_session("P-017", "video", "clip.mp4"); store.open_set(a, KNEE); store.end_session(a)
        fake_clock.advance(60)
        b = store.start_session("unassigned", "webcam", "0"); store.open_set(b, SQUAT); store.end_session(b)
        fake_clock.advance(60)
        c = _seed_two_set_session(store, "P-017"); store.end_session(c)
        rows = store.list_sessions()
        assert [r.id for r in rows] == [c, b, a]
        top = rows[0]
        assert (top.patient_id, top.source, top.status, top.exercises, top.total_reps, top.avg_form_score) == \
               ("P-017", "webcam", "completed", ["Knee Extension", "Squat"], 3, 91.0)
        assert top.end_time is not None
        assert [r.id for r in store.list_sessions(patient_id="P-017")] == [c, a]

    def test_load_session_full_graph(self, store):
        sid = _seed_two_set_session(store)
        store.end_session(sid)
        s = store.load_session(sid)
        assert [x.ordinal for x in s.sets] == [1, 2]
        assert len(s.sets[0].reps) == 1 and len(s.sets[0].partial_reps) == 2 and len(s.sets[0].form_events) == 1
        assert len(s.sets[1].reps) == 2
        assert [c.kind for c in s.control_events] == ["switch", "reset"]
        assert s.sets[0].end_time == "2026-03-23T09:15:06.666667"

    def test_event_log_ordered_and_tagged(self, store):
        sid = _seed_two_set_session(store)
        store.end_session(sid)
        log = store.event_log(sid)
        assert [r.type for r in log] == [
            "session_start", "rep", "partial_rep", "form", "partial_rep", "switch", "rep", "reset", "rep", "session_end",
        ]
        assert log[0].data["exercise"] == "Knee Extension" and log[0].data["target_reps"] == 10
        assert [r.set_ordinal for r in log[1:6]] == [1, 1, 1, 1, 1]
        assert log[6].set_ordinal == 2 and log[7].data["exercise"] == "Squat"
        assert log[4].type == "partial_rep" and log[5].type == "switch"   # same timestamp: partial before switch
        assert log[-1].data["total_reps"] == 3 and log[-1].data["avg_form_score"] == 91.0

    def test_interrupted_session_log_ends_with_computed_summary_marked_interrupted(self, store):
        sid = _seed_two_set_session(store)
        store._interrupt_running("recovered_on_open")
        log = store.event_log(sid)
        assert log[-1].type == "session_end"
        assert log[-1].data["status"] == "interrupted" and log[-1].data["total_reps"] == 3
        assert log[-1].timestamp == "2026-03-23T09:15:12.666667"   # last recorded event
        assert store.load_session(sid).status == "interrupted"

    def test_running_session_log_has_no_end_row(self, store):
        sid = _seed_two_set_session(store)
        log = store.event_log(sid)
        assert log[-1].type != "session_end"

    def test_unknown_session_raises(self, store):
        with pytest.raises(SessionNotFoundError):
            store.event_log(999)
        with pytest.raises(SessionNotFoundError):
            store.load_session(999)

    def test_performance_500_events_and_200_sessions(self, store):
        sid = store.start_session("unassigned", "webcam", "0")
        set_id = store.open_set(sid, KNEE)
        for n in range(1, 251):
            store.add_rep(set_id, _rep(n, ts=f"2026-03-23T09:{15 + n // 60:02d}:{n % 60:02d}", frame=60 * n))
            store.add_form_event(set_id, FormEvent("warning", "warning", f"msg {n}", f"2026-03-23T09:{15 + n // 60:02d}:{n % 60:02d}.5", 60 * n + 30))
        store.end_session(sid)
        t0 = time.perf_counter(); log = store.event_log(sid); elapsed = time.perf_counter() - t0
        assert len(log) == 502 and elapsed < 2.0
        for _ in range(199):
            s = store.start_session("unassigned", "video", "clip.mp4"); store.open_set(s, SQUAT); store.end_session(s)
        t0 = time.perf_counter(); rows = store.list_sessions(); elapsed = time.perf_counter() - t0
        assert len(rows) == 200 and elapsed < 2.0
