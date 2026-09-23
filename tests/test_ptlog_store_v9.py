"""Feature 010 T003 — schema v9: the entries table, and a table rebuild that must lose nothing."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from src.ptlog.models import EntryValidationError, PatientNotFoundError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

D0 = datetime(2026, 9, 20, 9, 0, 0)
GOOD = {"pain": 4, "area": "knee", "stiffness": "mild", "swelling": "none", "note": ""}


def _v8_record(path, make_session, fake_clock):
    """A realistic v8 record: patients, sessions with reps, reviews, audit rows, messages."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, sql in MIGRATIONS:
        if version > 8:
            break
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version VALUES (?, '2026-03-01T00:00:00')", (version,))
    conn.commit()
    conn.close()
    # fill it through a store pinned at v8 behaviour: the migrations up to 8 are already applied,
    # so opening with the full MIGRATIONS list would run v9; write rows with raw SQL instead
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES ('P-017', 'k', NULL, '2026-03-01', 0)")
    conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES ('unassigned', NULL, NULL, '2026-03-01', 1)")
    conn.execute("INSERT INTO sessions (patient_id, schema_version, source, source_ref, status, start_time) VALUES ('P-017', 8, 'webcam', '0', 'completed', '2026-09-01T09:00:00')")
    conn.execute("INSERT INTO exercise_sets (session_id, ordinal, exercise_key, exercise_name, side, target_reps, up_angle, down_angle, start_time) VALUES (1, 1, 'squat', 'Squat', 'left', 10, 170, 90, '2026-09-01T09:00:00')")
    for n in range(1, 6):
        conn.execute("INSERT INTO reps (set_id, rep_number, min_angle, max_angle, rom, duration_seconds, form_score, timestamp, frame_num, out_of_range) VALUES (1, ?, 90, 170, 80, 2.5, 88, '2026-09-01T09:00:10', 60, 0)", (n,))
    conn.execute("INSERT INTO reviews (session_id, next_step, notes, reviewed_at) VALUES (1, 'continue', 'fine', '2026-09-02T09:00:00')")
    conn.execute("INSERT INTO portal_audit (at, patient_id, event, client, detail) VALUES ('2026-09-02T09:00:00', 'P-017', 'login_ok', 'abc', NULL)")
    conn.execute("INSERT INTO portal_audit (at, patient_id, event, client, detail) VALUES ('2026-09-02T09:01:00', NULL, 'login_failed', 'abc', 'unknown_code')")
    conn.execute("INSERT INTO conversations (patient_id, enabled, updated_at) VALUES ('P-017', 1, '2026-09-02T09:00:00')")
    conn.execute("INSERT INTO messages (patient_id, sender, body, sent_at) VALUES ('P-017', 'patient', 'hello', '2026-09-02T09:00:00')")
    conn.commit()
    conn.close()


def _counts(path):
    conn = sqlite3.connect(str(path))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()
    return counts


def test_v8_record_upgrades_to_v9_without_losing_a_row(tmp_db, make_session, fake_clock):
    _v8_record(tmp_db, make_session, fake_clock)
    before = _counts(tmp_db)
    assert before["reps"] == 5 and before["portal_audit"] == 2 and before["reviews"] == 1
    with SessionStore(tmp_db).open() as s:
        assert SCHEMA_VERSION >= 9 and s.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert s.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # the rebuilt audit table accepts the new events and still refuses unknown ones
        s.portal_audit_add("entry_stored", "P-017", None, "checkin")
        with pytest.raises(sqlite3.IntegrityError):
            s.portal_audit_add("made_up", "P-017", None)
        assert len(s.load_session(1).sets[0].reps) == 5 and s.get_review(1).next_step == "continue"
    after = _counts(tmp_db)
    for table, n in before.items():
        assert after[table] >= n, table
    assert after["portal_audit"] == before["portal_audit"] + 1 and after["reps"] == 5 and after["reviews"] == 1
    assert "entries" in after


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-020")
        yield s


def test_add_list_and_idempotent_client_id(store, fake_clock):
    e = store.entry_add("P-017", "checkin", GOOD, score=4.0, recorded_at=fake_clock().isoformat(),
                        client_id="c-1", phase="standalone", session_id=None, warned=False, time_adjusted=False)
    again = store.entry_add("P-017", "checkin", {**GOOD, "pain": 9}, score=9.0, recorded_at=fake_clock().isoformat(),
                            client_id="c-1", phase="standalone", session_id=None, warned=False, time_adjusted=False)
    assert again.id == e.id and again.score == 4.0                          # resend: the first entry stands
    other = store.entry_add("P-020", "checkin", GOOD, score=4.0, recorded_at=fake_clock().isoformat(),
                            client_id="c-1", phase="standalone", session_id=None, warned=False, time_adjusted=False)
    assert other.id != e.id                                                  # client ids are per patient
    fake_clock.advance(60)
    later = store.entry_add("P-017", "checkin", {**GOOD, "pain": 6, "note": "worse"}, score=6.0,
                            recorded_at=fake_clock().isoformat(), client_id="c-2", phase="after", session_id=None,
                            warned=True, time_adjusted=True)
    rows = store.entries("P-017", "checkin")
    assert [r.id for r in rows] == [e.id, later.id] and rows[1].warned and rows[1].time_adjusted and rows[1].phase == "after"
    assert store.entries("P-017", "checkin", newest_first=True)[0].id == later.id
    assert store.entries("P-020")[0].patient_id == "P-020" and len(store.entries("P-020")) == 1
    events = [(a.event, a.detail) for a in store.portal_audit_list("P-017")]
    assert events[0] == ("entry_stored", "checkin") and "worse" not in str(events)


def test_note_removal_and_validation_at_the_store(store, fake_clock):
    e = store.entry_add("P-017", "checkin", {**GOOD, "note": "I am Jane Smith"}, score=4.0,
                        recorded_at=fake_clock().isoformat(), client_id="c-9", phase="standalone", session_id=None,
                        warned=True, time_adjusted=False)
    assert store.entry_remove_note(e.id) is True and store.entry_remove_note(e.id) is False
    (row,) = store.entries("P-017")
    assert row.payload["note"] == "" and row.note_removed is True
    assert "Jane" not in str(store.conn.execute("SELECT * FROM entries").fetchall())
    assert store.portal_audit_list("P-017")[0].event == "entry_note_removed"
    with pytest.raises(PatientNotFoundError):
        store.entry_add("P-404", "checkin", GOOD, 4.0, fake_clock().isoformat(), "c", "standalone", None, False, False)
    with pytest.raises(sqlite3.IntegrityError):
        store.entry_add("P-017", "unknown_kind", GOOD, 4.0, fake_clock().isoformat(), "c-3", "standalone", None, False, False)


def test_entries_follow_the_patient(store, fake_clock):
    store.entry_add("P-017", "checkin", GOOD, 4.0, fake_clock().isoformat(), "c", "standalone", None, False, False)
    store.conn.execute("UPDATE patients SET id = 'P-117' WHERE id = 'P-017'")
    store.conn.commit()
    assert len(store.entries("P-117")) == 1
    store.delete_patient("P-117")
    assert store.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
