"""Feature 017 FR-005 — the v15 upgrade gives every patient one active plan and puts every existing record
in it, keeping message order and read state. Every table is counted, as for every migration before it."""

import sqlite3

from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

PREVIOUS = 14
MEDIA_ID = "00000000-0000-4000-8000-000000000001"


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
        conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES (?, ?, NULL, ?, ?)",
                     (pid, "label " + pid, "2026-03-01T08:00:00", builtin))
    conn.execute("INSERT INTO conversations (patient_id, enabled, updated_at) VALUES ('P-017', 1, '2026-09-01T09:00:00')")
    for body, sender, read in (("first", "patient", "2026-09-01T10:00:00"), ("second", "therapist", None),
                               ("third", "patient", None)):
        conn.execute("INSERT INTO messages (patient_id, sender, body, sent_at, read_at) VALUES ('P-017', ?, ?, "
                     "'2026-09-01T09:00:00', ?)", (sender, body, read))
    conn.execute("INSERT INTO messages (patient_id, sender, body, sent_at) VALUES ('P-018', 'patient', 'hi', "
                 "'2026-09-02T09:00:00')")
    conn.execute("INSERT INTO sessions (patient_id, schema_version, source, source_ref, status, start_time) "
                 "VALUES ('P-017', 14, 'video', 'clip.mp4', 'completed', '2026-09-01T08:00:00')")
    conn.execute("INSERT INTO entries (patient_id, kind, recorded_at, received_at, phase, score, payload, client_id) "
                 "VALUES ('P-018', 'checkin', '2026-09-01', '2026-09-01', 'before', 3, '{}', 'c-1')")
    conn.execute("INSERT INTO media (id, patient_id, kind, ext, container, codec, bytes, duration, sha256, created_at) "
                 "VALUES (?, 'P-017', 'clip', 'mp4', 'mov', 'h264', 100, 2.0, 'x', '2026-09-01T11:00:00')", (MEDIA_ID,))
    conn.execute("INSERT INTO assignments (patient_id, program_id, program_name, exercise_keys, sessions_per_week, "
                 "start_date, created_at) VALUES ('P-017', 'custom', 'Knee', '[\"squat\"]', 3, '2026-09-01', '2026-09-01')")
    conn.execute("INSERT INTO instrument_assignments (patient_id, instrument_key, interval, start_date, created_at) "
                 "VALUES ('P-018', 'demo_knee_function', 'weekly', '2026-09-01', '2026-09-01T09:00:00')")
    conn.commit()
    conn.close()


def _counts(path):
    conn = sqlite3.connect(str(path))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()
    return counts


def test_the_upgrade_keeps_every_row_and_makes_one_plan_each(tmp_db):
    _previous_version_record(tmp_db)
    before = _counts(tmp_db)
    assert "plans_of_care" not in before
    with SessionStore(tmp_db).open() as s:
        assert SCHEMA_VERSION >= 15 and [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION
        assert s.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        for pid in ("P-017", "P-018", "unassigned"):
            (plan,) = s.plans(pid)
            assert (plan.title, plan.status, plan.start_date) == ("Plan of care", "active", "2026-03-01")
        knee = s.plans("P-017")[0]
        thread = s.message_thread("P-017", knee.id)                       # story 2, scenario 2
        assert [(m.body, m.read_at is not None) for m in thread] == [("first", True), ("second", False), ("third", False)]
        assert s.messages_unread_by_plan("patient", "P-017") == {knee.id: 1}
        for table in ("messages", "sessions", "entries", "media", "assignments", "instrument_assignments"):
            orphans = s.conn.execute(
                f"SELECT COUNT(*) FROM {table} t LEFT JOIN plans_of_care p ON p.id = t.plan_id "
                f"WHERE p.id IS NULL OR p.patient_id <> t.patient_id").fetchone()[0]
            assert orphans == 0, table
    after = _counts(tmp_db)
    assert after["plans_of_care"] == 3 and after["appointments"] == 0 and after["attachments"] == 0
    for table, n in before.items():
        expected = n + (SCHEMA_VERSION - PREVIOUS) if table == "schema_version" else n
        assert after[table] == expected, f"{table}: {n} rows before, {after[table]} after"
