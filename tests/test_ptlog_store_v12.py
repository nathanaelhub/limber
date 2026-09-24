"""Feature 013 T006 — assignments in the record, and a v11 record upgrading without loss.

Unlike v11, nothing is rebuilt here: `instrument_assignments` is a new table, and `entries.kind` has
allowed 'questionnaire' since v9. The migration test still compares every table, because the cheapest
migration is the one that quietly drops a row.
"""

import sqlite3
from datetime import date, datetime

import pytest

from src.ptlog.models import ExerciseSetInfo, PTLogError, RepEvent
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

PREVIOUS = 11
D0 = date(2026, 9, 24)


def _previous_version_record(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, sql in MIGRATIONS:
        if version > PREVIOUS:
            break
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version VALUES (?, '2026-03-01T00:00:00')", (version,))
    conn.commit()
    conn.close()
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys=ON")
    for pid, builtin in (("P-017", 0), ("P-018", 0), ("unassigned", 1)):
        conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES (?, ?, NULL, '2026-03-01', ?)",
                     (pid, "label " + pid, builtin))
    conn.execute("INSERT INTO sessions (id, patient_id, schema_version, source, source_ref, status, start_time, "
                 "end_time, total_reps) VALUES (1, 'P-017', 11, 'webcam', 'ref', 'completed', "
                 "'2026-09-01T09:00:00', '2026-09-01T09:10:00', 10)")
    conn.execute("INSERT INTO exercise_sets (session_id, ordinal, exercise_key, exercise_name, side, target_reps, "
                 "up_angle, down_angle, start_time) VALUES (1, 1, 'squat', 'Squat', 'left', 10, 170, 90, "
                 "'2026-09-01T09:00:00')")
    conn.execute("INSERT INTO reps (set_id, rep_number, min_angle, max_angle, rom, duration_seconds, form_score, "
                 "timestamp, frame_num, out_of_range) VALUES (1, 1, 90, 170, 80, 2.5, 88, '2026-09-01T09:00:10', 60, 0)")
    conn.execute("INSERT INTO entries (patient_id, kind, recorded_at, received_at, phase, session_id, score, payload, "
                 "client_id) VALUES ('P-017', 'checkin', '2026-09-01T10:00:00', '2026-09-01T10:00:00', 'after', 1, "
                 "4.0, '{\"pain\": 4}', 'c1')")
    conn.execute("INSERT INTO patient_settings (patient_id, diary_enabled, medications, updated_at) "
                 "VALUES ('P-017', 1, '[\"ibuprofen\"]', '2026-09-01T09:00:00')")
    conn.commit()
    conn.close()


def _counts(path):
    conn = sqlite3.connect(str(path))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()
    return counts


def test_the_upgrade_keeps_every_row(tmp_db):
    _previous_version_record(tmp_db)
    before = _counts(tmp_db)
    assert "instrument_assignments" not in before
    with SessionStore(tmp_db).open() as s:
        assert SCHEMA_VERSION >= 12 and [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION
        assert s.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert len(s.load_session(1).sets[0].reps) == 1 and len(s.entries("P-017")) == 1
        assert s.medication_list("P-017") == ["ibuprofen"]
        assert s.assignments("P-017") == []
    after = _counts(tmp_db)
    assert after["instrument_assignments"] == 0
    for table, n in before.items():
        expected = n + 1 if table == "schema_version" else n
        assert after[table] == expected, f"{table}: {n} rows before, {after[table]} after"


class TestAssignments:
    def test_assign_list_and_end(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as s:
            s.add_patient("P-017")
            a = s.assign_instrument("P-017", "demo_knee_function", "fortnightly", D0)
            assert (a.instrument_key, a.interval, a.start_date, a.ended_at) == (
                "demo_knee_function", "fortnightly", D0.isoformat(), None)
            assert [x.id for x in s.assignments("P-017")] == [a.id]
            assert s.assignments("P-017", include_ended=True) == s.assignments("P-017")
            s.end_assignment(a.id)
            assert s.assignments("P-017") == []
            ended = s.assignments("P-017", include_ended=True)
            assert len(ended) == 1 and ended[0].ended_at is not None

    def test_assigning_again_replaces_the_live_one_and_keeps_the_old(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as s:
            s.add_patient("P-017")
            first = s.assign_instrument("P-017", "demo_knee_function", "weekly", D0)
            second = s.assign_instrument("P-017", "demo_knee_function", "monthly", D0)
            live = s.assignments("P-017")
            assert [x.id for x in live] == [second.id] and live[0].interval == "monthly"
            assert len(s.assignments("P-017", include_ended=True)) == 2
            assert first.id != second.id
            other = s.assign_instrument("P-017", "another", "weekly", D0)     # a different instrument stands beside it
            assert {x.instrument_key for x in s.assignments("P-017")} == {"demo_knee_function", "another"}
            assert other.patient_id == "P-017"

    def test_refusals(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as s:
            s.add_patient("P-017")
            with pytest.raises(PTLogError):
                s.assign_instrument("P-999", "demo_knee_function", "weekly", D0)      # no such patient
            with pytest.raises(PTLogError):
                s.assign_instrument("P-017", "demo_knee_function", "whenever", D0)    # not an interval
            with pytest.raises(PTLogError):
                s.assign_instrument("P-017", "", "weekly", D0)

    def test_the_latest_answer_drives_the_next_due_date(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as s:
            s.add_patient("P-017")
            s.assign_instrument("P-017", "demo_knee_function", "weekly", D0)
            assert s.last_questionnaire_at("P-017", "demo_knee_function") is None
            for when in ("2026-09-20T09:00:00", "2026-09-22T09:00:00"):
                s.entry_add("P-017", "questionnaire", {"instrument": "demo_knee_function", "answers": {}}, 30.0,
                            when, f"c{when}", "standalone", None, False, False)
            assert s.last_questionnaire_at("P-017", "demo_knee_function") == "2026-09-22T09:00:00"
            assert s.last_questionnaire_at("P-017", "other") is None

    def test_deleting_a_patient_removes_assignments_and_answers(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as s:
            for pid in ("P-017", "P-018"):
                s.add_patient(pid)
                s.assign_instrument(pid, "demo_knee_function", "weekly", D0)
                s.entry_add(pid, "questionnaire", {"instrument": "demo_knee_function", "answers": {}}, 20.0,
                            "2026-09-20T09:00:00", f"c{pid}", "standalone", None, False, False)
            s.delete_patient("P-017")
            assert s.assignments("P-017", include_ended=True) == [] and s.entries("P-017") == []
            assert len(s.assignments("P-018", include_ended=True)) == 1 and len(s.entries("P-018")) == 1
