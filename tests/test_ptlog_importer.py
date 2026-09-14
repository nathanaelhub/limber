"""T047 — one-time legacy import: three JSON shapes, idempotent, cross-folder dedup, malformed skipped."""

import shutil
from pathlib import Path

import pytest

from src.ptlog.importer import ImportReport, import_legacy
from src.ptlog.store import SessionStore

LEGACY = Path(__file__).resolve().parent / "fixtures" / "legacy"


@pytest.fixture
def dirs(tmp_path):
    shutil.copytree(LEGACY / "sessions", tmp_path / "sessions")
    shutil.copytree(LEGACY / "observation_logs", tmp_path / "observation_logs")
    return tmp_path / "sessions", tmp_path / "observation_logs"


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        yield s


def outcomes(report: ImportReport) -> dict:
    return {e.path.name: e.outcome for e in report.entries}


class TestImport:
    def test_creates_one_session_per_legacy_session(self, store, dirs):
        report = import_legacy(store, *dirs)
        o = outcomes(report)
        assert o["pt_session_knee_extension_20260127_134857.json"] == "imported"
        assert o["pt_session_knee_extension_20260127_134857.csv"] == "skipped"
        assert o["tracker_shape.json"] == "imported"
        assert o["session_2026-03-23_234321.json"] == "imported"
        assert o["malformed.json"] == "malformed"
        assert sorted(v for k, v in o.items() if "150551" in k) == ["duplicate", "imported"]   # cross-folder pair
        assert report.imported == 4 and report.duplicates == 1 and report.malformed == 1 and report.skipped == 1
        rows = store.list_sessions()
        assert len(rows) == 4 and all(r.patient_id == "unassigned" for r in rows)

    def test_report_shape_values_match_file(self, store, dirs):
        import_legacy(store, *dirs)
        row = next(r for r in store.list_sessions() if r.start_time.startswith("2026-01-27T13:45:10"))
        s = store.load_session(row.id)
        assert (s.source, s.status, s.end_time) == ("video", "completed", "2026-01-27T13:48:57.900000")
        assert [x.exercise_name for x in s.sets] == ["Knee Extension"]
        assert s.sets[0].exercise_key == "knee_extension" and s.sets[0].side == "left" and s.sets[0].target_reps == 10
        assert [(r.rep_number, r.rom, r.form_score) for r in s.sets[0].reps] == [(1, 78.4, 95.0), (2, 79.1, 94.0), (3, 77.8, 93.0)]
        assert (s.total_reps, s.avg_form_score, s.avg_rom) == (3, 94.0, 78.4)
        assert s.source_ref == "legacy-import"

    def test_observation_shape_sets_events_and_controls(self, store, dirs):
        import_legacy(store, *dirs)
        row = next(r for r in store.list_sessions() if r.start_time.startswith("2026-03-23T09:15:00"))
        s = store.load_session(row.id)
        assert s.source == "webcam"
        assert [(x.exercise_name, len(x.reps), len(x.partial_reps)) for x in s.sets] == [("Knee Extension", 2, 1), ("Squat", 1, 0)]
        assert [c.kind for c in s.control_events] == ["switch", "reset"]
        assert s.sets[0].end_time == "2026-03-23T09:16:00.000000" and s.sets[1].start_time == "2026-03-23T09:16:00.000000"
        assert s.total_reps == 3 and s.end_time == "2026-03-23T09:16:40.000000"
        assert s.sets[1].side == "bilateral" and s.sets[1].exercise_key == "squat"

    def test_tracker_shape_reconstructs_aggregate_reps(self, store, dirs):
        import_legacy(store, *dirs)
        row = next(r for r in store.list_sessions() if r.start_time.startswith("2026-02-03T11:10:00"))
        s = store.load_session(row.id)
        assert s.sets[0].exercise_name == "Shoulder Flexion" and len(s.sets[0].reps) == 4
        assert all(r.frame_num == -1 for r in s.sets[0].reps)          # marked as reconstructed from set averages
        assert (s.total_reps, s.avg_form_score, s.avg_rom) == (4, 81.0, 145.0)

    def test_second_run_creates_nothing(self, store, dirs):
        import_legacy(store, *dirs)
        before = len(store.list_sessions())
        report = import_legacy(store, *dirs)
        assert len(store.list_sessions()) == before
        assert report.imported == 0
        assert all(e.outcome in ("duplicate", "skipped", "malformed") for e in report.entries)
        assert all(e.detail == "already imported" for e in report.entries if e.outcome == "duplicate")

    def test_cross_folder_duplicate_detail(self, store, dirs):
        report = import_legacy(store, *dirs)
        dup = next(e for e in report.entries if e.outcome == "duplicate")
        assert dup.detail == "same session found in both folders"

    def test_malformed_reported_by_name_and_others_still_import(self, store, dirs):
        report = import_legacy(store, *dirs)
        bad = next(e for e in report.entries if e.outcome == "malformed")
        assert bad.path.name == "malformed.json" and bad.detail
        assert report.imported == 4

    def test_dry_run_writes_nothing(self, store, dirs):
        report = import_legacy(store, *dirs, dry_run=True)
        assert report.imported == 4
        assert store.list_sessions() == []
        assert store.conn.execute("SELECT COUNT(*) FROM import_ledger").fetchone()[0] == 0

    def test_ledger_rows(self, store, dirs):
        import_legacy(store, *dirs)
        rows = store.conn.execute("SELECT outcome, COUNT(*) FROM import_ledger GROUP BY outcome").fetchall()
        assert dict(rows) == {"imported": 4, "duplicate": 1, "malformed": 1}

    def test_missing_directories_are_fine(self, store, tmp_path):
        report = import_legacy(store, tmp_path / "nope", tmp_path / "nope2")
        assert report.entries == [] and report.imported == 0

    def test_patient_kept_when_registered(self, store, dirs):
        store.add_patient("P-002")
        import_legacy(store, *dirs)
        row = next(r for r in store.list_sessions() if r.start_time.startswith("2026-02-03"))
        assert row.patient_id == "P-002"
