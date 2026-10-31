"""Feature 018 T004 — the v16 upgrade adds the assistant's tables and `messages.from_draft` without touching a row.
Every table is counted, as for every migration before it."""

import sqlite3

from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

PREVIOUS = 15


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
    for pid, builtin in (("P-017", 0), ("unassigned", 1)):
        conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES (?, NULL, NULL, "
                     "'2026-03-01T08:00:00', ?)", (pid, builtin))
    conn.execute("INSERT INTO plans_of_care (patient_id, title, start_date, status, created_at) VALUES "
                 "('P-017', 'Plan of care', '2026-03-01', 'active', '2026-03-01T08:00:00')")
    conn.execute("INSERT INTO conversations (patient_id, enabled, updated_at) VALUES ('P-017', 1, '2026-09-01T09:00:00')")
    for body, sender in (("first", "patient"), ("second", "therapist")):
        conn.execute("INSERT INTO messages (patient_id, sender, body, sent_at, plan_id) VALUES ('P-017', ?, ?, "
                     "'2026-09-01T09:00:00', 1)", (sender, body))
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
    assert "assist_switches" not in before
    with SessionStore(tmp_db).open() as s:
        thread = s.message_thread("P-017")
        assert [m.body for m in thread] == ["first", "second"] and not any(m.from_draft for m in thread)
        assert s.assist_switches("P-017") == {"summaries": False, "coach": False}
    after = _counts(tmp_db)
    for table, n in before.items():
        expected = n + (SCHEMA_VERSION - PREVIOUS) if table == "schema_version" else n
        assert after[table] == expected, table
    assert {"assist_switches", "assist_calls", "therapist_notes", "message_handled"} <= set(after)
