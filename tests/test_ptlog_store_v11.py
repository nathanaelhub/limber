"""Feature 012 T002 — rebuilding the sessions table must not lose a single row.

With foreign keys on, dropping the old sessions table cascades into sets, reps, reviews, and entries.
This test writes a realistic previous-version record, upgrades it, and compares every table.
"""

import sqlite3

import pytest

from src.ptlog.models import ExerciseSetInfo, RepEvent
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

PREVIOUS = 10


def _previous_version_record(path):
    """A record written by the previous schema, with rows in every table a rebuild could destroy."""
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
    for sid, pid, source in ((1, "P-017", "webcam"), (2, "P-017", "video"), (3, "P-018", "webcam")):
        conn.execute("INSERT INTO sessions (id, patient_id, schema_version, source, source_ref, source_extras, status, "
                     "start_time, end_time, total_reps, avg_form_score, avg_rom, duration_seconds) "
                     "VALUES (?, ?, 10, ?, 'ref', '{\"origin\": \"portal\"}', 'completed', '2026-09-01T09:00:00', "
                     "'2026-09-01T09:10:00', 10, 88.5, 80.1, 600.0)", (sid, pid, source))
        conn.execute("INSERT INTO exercise_sets (session_id, ordinal, exercise_key, exercise_name, side, target_reps, "
                     "up_angle, down_angle, start_time) VALUES (?, 1, 'squat', 'Squat', 'left', 10, 170, 90, '2026-09-01T09:00:00')",
                     (sid,))
        set_id = conn.execute("SELECT id FROM exercise_sets WHERE session_id = ?", (sid,)).fetchone()[0]
        for n in range(1, 4):
            conn.execute("INSERT INTO reps (set_id, rep_number, min_angle, max_angle, rom, duration_seconds, form_score, "
                         "timestamp, frame_num, out_of_range) VALUES (?, ?, 90, 170, 80, 2.5, 88, '2026-09-01T09:00:10', 60, 0)",
                         (set_id, n))
        conn.execute("INSERT INTO partial_reps (set_id, reason, min_angle, max_angle, rom, duration_seconds, timestamp, frame_num) "
                     "VALUES (?, 'reversed_early', 120, 160, 40, 1.4, '2026-09-01T09:00:20', 90)", (set_id,))
        conn.execute("INSERT INTO form_events (set_id, severity, status, message, timestamp, frame_num) "
                     "VALUES (?, 'warning', 'warning', 'Keep the knee aligned', '2026-09-01T09:00:30', 120)", (set_id,))
        conn.execute("INSERT INTO control_events (session_id, kind, timestamp, frame_num) VALUES (?, 'reset', '2026-09-01T09:05:00', 300)", (sid,))
        conn.execute("INSERT INTO frame_samples (set_id, frame_num, timestamp, angle, state, rep_count) "
                     "VALUES (?, 15, '2026-09-01T09:00:05', 120.5, 'down', 1)", (set_id,))
        conn.execute("INSERT INTO reviews (session_id, next_step, notes, reviewed_at) VALUES (?, 'continue', 'note', '2026-09-02T09:00:00')", (sid,))
    conn.execute("INSERT INTO entries (patient_id, kind, recorded_at, received_at, phase, session_id, score, payload, client_id) "
                 "VALUES ('P-017', 'checkin', '2026-09-01T10:00:00', '2026-09-01T10:00:00', 'after', 1, 4.0, '{\"pain\": 4}', 'c1')")
    conn.execute("INSERT INTO media (id, patient_id, kind, ext, container, codec, bytes, duration, sha256, created_at) "
                 "VALUES ('00000000-0000-4000-8000-000000000001', 'P-017', 'clip', 'mp4', 'mov', 'h264', 100, 2.0, 'x', '2026-09-01T11:00:00')")
    conn.execute("INSERT INTO conversations (patient_id, enabled, updated_at) VALUES ('P-017', 1, '2026-09-01T09:00:00')")
    conn.execute("INSERT INTO messages (patient_id, sender, body, sent_at) VALUES ('P-017', 'patient', 'hello', '2026-09-01T09:00:00')")
    conn.execute("INSERT INTO portal_audit (at, patient_id, event, client, detail) VALUES ('2026-09-01T09:00:00', 'P-017', 'login_ok', 'abc', NULL)")
    conn.execute("INSERT INTO goals (patient_id, exercise_name, target_rom, target_reps, set_at) "
                 "VALUES ('P-017', 'Squat', 100.0, 12, '2026-09-01T09:00:00')")
    conn.execute("INSERT INTO assignments (patient_id, program_id, program_name, exercise_keys, sessions_per_week, start_date, created_at) "
                 "VALUES ('P-017', 'custom', 'Home', '[\"squat\"]', 3, '2026-08-01', '2026-08-01T09:00:00')")
    conn.execute("INSERT INTO patient_thresholds (patient_id, key, value) VALUES ('P-017', 'form_drop', 8)")
    conn.execute("INSERT INTO exercise_thresholds (patient_id, exercise_name, key, value) VALUES ('P-017', 'Squat', 'rom_regression', 5)")
    conn.commit()
    conn.close()


def _counts(path):
    conn = sqlite3.connect(str(path))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()
    return counts


def test_the_rebuild_keeps_every_row(tmp_db):
    _previous_version_record(tmp_db)
    before = _counts(tmp_db)
    assert before["reps"] == 9 and before["reviews"] == 3 and before["entries"] == 1 and before["media"] == 1
    with SessionStore(tmp_db).open() as s:
        assert SCHEMA_VERSION >= 11 and [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION
        assert s.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert s.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        session = s.load_session(1)
        assert len(session.sets[0].reps) == 3 and session.total_reps == 10 and session.source_extras["origin"] == "portal"
        assert s.get_review(1).next_step == "continue" and len(s.entries("P-017")) == 1
        indexes = {r[0] for r in s.conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='sessions'")}
        assert {"idx_sessions_patient_start", "idx_sessions_status"} <= indexes
    after = _counts(tmp_db)
    for table, n in before.items():
        if table == "schema_version":
            assert after[table] == n + (SCHEMA_VERSION - PREVIOUS)   # one row per migration applied
            continue
        if table == "portal_admin":                                  # v14 moved it into accounts (feature 016)
            assert table not in after and after["accounts"] == n
            continue
        assert after[table] == n, f"{table}: {n} rows before, {after[table]} after"


def test_a_diary_session_can_be_stored(tmp_db, fake_clock):
    _previous_version_record(tmp_db)
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        sid = s.start_session("P-017", "diary", "self-reported", {"origin": "diary"})
        set_id = s.open_set(sid, ExerciseSetInfo("squat", "Squat", "left", 10, 170.0, 90.0))
        s.set_reported(set_id, reps=10, sets=2, effort=3)
        done = s.end_session(sid)
        assert done.source == "diary" and done.total_reps == 20 and done.avg_form_score is None and done.avg_rom is None
        stored = s.load_session(sid).sets[0]
        assert (stored.reported_reps, stored.reported_sets, stored.effort) == (10, 2, 3)
        with pytest.raises(sqlite3.IntegrityError):
            s.conn.execute("INSERT INTO sessions (patient_id, schema_version, source, status, start_time) "
                           "VALUES ('P-017', 11, 'telepathy', 'completed', '2026-09-01T09:00:00')")


def test_medication_list_and_diary_switch(tmp_db):
    _previous_version_record(tmp_db)
    with SessionStore(tmp_db).open() as s:
        assert s.diary_enabled("P-017") is True                      # on by default
        s.set_diary_enabled("P-017", False)
        assert s.diary_enabled("P-017") is False and s.diary_enabled("P-018") is True
        assert s.medication_list("P-017") == []
        s.set_medication_list("P-017", ["ibuprofen 400 mg", "paracetamol"])
        assert s.medication_list("P-017") == ["ibuprofen 400 mg", "paracetamol"]
        s.set_medication_list("P-017", [])
        assert s.medication_list("P-017") == []
        s.delete_patient("P-018")
        assert s.conn.execute("SELECT COUNT(*) FROM patient_settings WHERE patient_id = 'P-018'").fetchone()[0] == 0
