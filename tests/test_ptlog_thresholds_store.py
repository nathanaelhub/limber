"""Feature 005 T004 — schema v4, the upgrade from v3, and threshold storage."""

import sqlite3

import pytest

from src.ptlog.models import PatientNotFoundError, ThresholdValidationError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore


def _v3_file(path, gap=None, adherence=60):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, sql in MIGRATIONS:
        if version > 3:
            break
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version VALUES (?, '2026-03-01T00:00:00')", (version,))
    conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES ('P-017', NULL, NULL, '2026-03-01', 0)")
    if gap is not None:
        conn.execute("INSERT INTO review_settings (patient_id, gap_days) VALUES ('P-017', ?)", (gap,))
    conn.execute("UPDATE tracker_settings SET adherence_threshold = ? WHERE id = 1", (adherence,))
    conn.commit()
    conn.close()


@pytest.fixture
def store(tmp_db):
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-020")
        yield s


def test_fresh_store_is_v4_with_both_tables(tmp_db):
    with SessionStore(tmp_db).open() as s:
        tables = {r[0] for r in s.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        versions = [r[0] for r in s.conn.execute("SELECT version FROM schema_version ORDER BY version")]
    assert SCHEMA_VERSION == 4 and versions == [v for v, _ in MIGRATIONS] and versions[-1] == 4
    assert {"patient_thresholds", "installation_thresholds", "review_settings", "tracker_settings"} <= tables


def test_upgrade_preserves_gap_override_and_installation_adherence(tmp_db):
    _v3_file(tmp_db, gap=14, adherence=70)
    with SessionStore(tmp_db).open() as s:
        assert s.get_patient_thresholds("P-017") == {"practice_gap": 14}
        assert s.get_installation_thresholds() == {"adherence": 70}
        assert s.get_gap_days("P-017") == 14 and s.get_adherence_threshold() == 70
        t = s.effective_thresholds("P-017")
        assert (t.origin("practice_gap"), t.origin("adherence"), t.origin("form_drop")) == (
            "patient", "installation", "default")


def test_upgrade_with_default_adherence_copies_nothing(tmp_db):
    _v3_file(tmp_db)
    with SessionStore(tmp_db).open() as s:
        assert s.get_installation_thresholds() == {} and s.get_patient_thresholds("P-017") == {}


def test_patient_set_reset_and_reset_all(store):
    assert store.set_patient_threshold("P-017", "rom_regression", "5") == 5
    store.set_patient_threshold("P-017", "rom_regression", 6)
    store.set_patient_threshold("P-017", "form_drop", 8)
    assert store.get_patient_thresholds("P-017") == {"form_drop": 8, "rom_regression": 6}
    assert store.get_patient_thresholds("P-020") == {}
    assert store.reset_patient_threshold("P-017", "form_drop") is True
    assert store.reset_patient_threshold("P-017", "form_drop") is False
    assert store.reset_patient_thresholds("P-017") == 1
    assert store.effective_thresholds("P-017").overridden() == []


def test_validation_happens_before_any_write(store):
    with pytest.raises(ThresholdValidationError):
        store.set_patient_threshold("P-017", "form_drop", 0)
    with pytest.raises(ThresholdValidationError):
        store.set_installation_threshold("speed", 3)
    with pytest.raises(ThresholdValidationError):
        store.reset_patient_threshold("P-017", "speed")
    with pytest.raises(PatientNotFoundError):
        store.set_patient_threshold("P-404", "form_drop", 8)
    with pytest.raises(PatientNotFoundError):
        store.effective_thresholds("P-404")
    assert store.get_patient_thresholds("P-017") == {} and store.get_installation_thresholds() == {}


def test_installation_values_and_restore(store):
    store.set_installation_threshold("form_drop", 8)
    store.set_installation_threshold("adherence", 50)
    store.set_patient_threshold("P-017", "form_drop", 12)
    a, b = store.effective_thresholds("P-017"), store.effective_thresholds("P-020")
    assert (a.form_drop, a.origin("form_drop")) == (12, "patient")
    assert (b.form_drop, b.origin("form_drop")) == (8, "installation")
    assert store.reset_installation_threshold("adherence") is True
    assert store.restore_builtin_thresholds() == 1
    assert store.get_installation_thresholds() == {}
    assert store.effective_thresholds("P-017").form_drop == 12          # overrides are untouched


def test_effective_thresholds_all_covers_every_patient(store):
    store.set_installation_threshold("adherence", 55)
    store.set_patient_threshold("P-020", "adherence", 40)
    everyone = store.effective_thresholds_all()
    assert {"P-017", "P-020", "unassigned"} <= set(everyone)
    assert (everyone["P-017"].adherence, everyone["P-020"].adherence) == (55, 40)


def test_legacy_accessors_use_the_new_tables(store):
    assert store.set_gap_days("P-017", 10) == 10
    assert store.get_patient_thresholds("P-017") == {"practice_gap": 10}
    assert store.set_adherence_threshold(45) == 45
    assert store.get_installation_thresholds() == {"adherence": 45}
    store.set_installation_threshold("practice_gap", 9)
    assert store.get_gap_days("P-020") == 9 and store.get_gap_days("P-017") == 10
    with pytest.raises(ThresholdValidationError):
        store.set_gap_days("P-017", 91)


def test_overrides_follow_delete_and_id_change(store):
    store.set_patient_threshold("P-017", "form_drop", 8)
    store.set_patient_threshold("P-020", "form_drop", 9)
    store.conn.execute("UPDATE patients SET id = 'P-117' WHERE id = 'P-017'")
    store.conn.commit()
    assert store.get_patient_thresholds("P-117") == {"form_drop": 8}
    store.delete_patient("P-020")
    assert store.conn.execute("SELECT COUNT(*) FROM patient_thresholds WHERE patient_id = 'P-020'").fetchone()[0] == 0
