"""Feature 007 T003 — schema v6 and the store's portal methods (access codes, sign-ins, access history)."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from src.ptlog.models import PatientNotFoundError, PortalError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

T0 = datetime(2026, 9, 21, 9, 0, 0)


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-020")
        yield s


def _v5_file(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, sql in MIGRATIONS:
        if version > 5:
            break
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version VALUES (?, '2026-03-01T00:00:00')", (version,))
    conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES ('P-017', NULL, NULL, '2026-03-01', 0)")
    conn.execute("INSERT INTO patient_thresholds VALUES ('P-017', 'form_drop', 8)")
    conn.commit()
    conn.close()


def test_v6_tables_and_upgrade_keeps_data(tmp_db):
    _v5_file(tmp_db)
    with SessionStore(tmp_db).open() as s:
        tables = {r[0] for r in s.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        versions = [r[0] for r in s.conn.execute("SELECT version FROM schema_version ORDER BY version")]
        assert SCHEMA_VERSION >= 6 and versions == [v for v, _ in MIGRATIONS]
        assert {"portal_access", "portal_sessions", "portal_audit"} <= tables
        assert s.get_patient_thresholds("P-017") == {"form_drop": 8}
        assert s.portal_status("P-017").state == "none"


def test_code_lifecycle_and_states(store, fake_clock):
    now = fake_clock()
    status = store.portal_set_code("P-017", "hash-a", now + timedelta(days=90))
    assert status.state == "active" and status.patient_id == "P-017"
    assert store.portal_lookup("hash-a").patient_id == "P-017" and store.portal_lookup("nope") is None
    store.portal_touch("P-017")
    assert store.portal_status("P-017").last_used_at == now.isoformat()
    fake_clock.advance(91 * 86400)
    assert store.portal_status("P-017").state == "expired"
    store.portal_set_code("P-017", "hash-b", fake_clock() + timedelta(days=1))
    assert store.portal_lookup("hash-a") is None and store.portal_status("P-017").state == "active"
    assert store.portal_revoke("P-017") is True and store.portal_revoke("P-017") is False
    assert store.portal_status("P-017").state == "revoked"
    assert [(a.patient_id, a.state) for a in store.portal_list()] == [("P-017", "revoked"), ("P-020", "none")]


def test_codes_are_refused_for_builtin_discharged_and_unknown(store, fake_clock):
    later = fake_clock() + timedelta(days=1)
    with pytest.raises(PortalError):
        store.portal_set_code("unassigned", "h1", later)
    store.discharge("P-020")
    with pytest.raises(PortalError):
        store.portal_set_code("P-020", "h2", later)
    with pytest.raises(PatientNotFoundError):
        store.portal_set_code("P-404", "h3", later)
    with pytest.raises(sqlite3.IntegrityError):
        store.portal_set_code("P-017", "same", later)
        store.reactivate("P-020")
        store.portal_set_code("P-020", "same", later)          # lookup hashes are unique


def test_sign_ins(store, fake_clock):
    now = fake_clock()
    for i in range(4):
        store.portal_signin_create(f"tok{i}", "P-017", now + timedelta(hours=12), keep=3)
        fake_clock.advance(1)
    assert store.portal_signin_get("tok0") is None                   # oldest pruned, three kept
    s = store.portal_signin_get("tok3")
    assert s.patient_id == "P-017" and s.expires_at == (now + timedelta(hours=12)).isoformat()
    fake_clock.advance(60)
    store.portal_signin_touch("tok3")
    assert store.portal_signin_get("tok3").last_seen_at == fake_clock().isoformat()
    store.portal_signin_delete("tok3")
    assert store.portal_signin_get("tok3") is None
    store.portal_set_code("P-017", "new", now + timedelta(days=1))     # a new code signs the patient out everywhere
    assert store.portal_signin_get("tok1") is None and store.portal_signin_get("tok2") is None
    store.portal_signin_create("tokR", "P-017", now + timedelta(hours=12))
    store.portal_revoke("P-017")
    assert store.portal_signin_get("tokR") is None


def test_audit(store, fake_clock):
    store.portal_audit_add("login_failed", None, "3fa9c1d2e4b7a680", "unknown_code")
    fake_clock.advance(5)
    store.portal_audit_add("login_ok", "P-017", "3fa9c1d2e4b7a680")
    store.portal_audit_add("live_start", "P-020", None)
    rows = store.portal_audit_list()
    assert [(r.event, r.patient_id) for r in rows] == [("live_start", "P-020"), ("login_ok", "P-017"), ("login_failed", None)]
    assert [r.event for r in store.portal_audit_list("P-017")] == ["login_ok"]
    assert len(store.portal_audit_list(limit=1)) == 1
    with pytest.raises(sqlite3.IntegrityError):
        store.portal_audit_add("made_up_event", "P-017", None)


def test_everything_follows_the_patient(store, fake_clock):
    later = fake_clock() + timedelta(days=1)
    store.portal_set_code("P-017", "h", later)
    store.portal_signin_create("tok", "P-017", later)
    store.portal_audit_add("login_ok", "P-017", None)
    store.conn.execute("UPDATE patients SET id = 'P-117' WHERE id = 'P-017'")
    store.conn.commit()
    assert store.portal_lookup("h").patient_id == "P-117" and store.portal_signin_get("tok").patient_id == "P-117"
    store.delete_patient("P-117")
    for table in ("portal_access", "portal_sessions", "portal_audit"):
        assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
