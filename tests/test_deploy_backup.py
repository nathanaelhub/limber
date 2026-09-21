"""Feature 009 T004 — encrypted backups of the record, retention, verification, and restore."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from src.deploy import backup
from src.ptlog.models import PTLogError
from src.ptlog.store import SessionStore


@pytest.fixture
def record(tmp_path):
    db = tmp_path / "data" / "ptassist.db"
    db.parent.mkdir()
    with SessionStore(db).open() as s:
        s.add_patient("P-017", label="Post-op knee")
        s.set_patient_threshold("P-017", "form_drop", 8)
    return db


@pytest.fixture
def key(tmp_path):
    return backup.load_backup_key(tmp_path / "secrets" / "backup.key")


def test_backup_while_a_writer_is_open_and_restore_round_trip(record, key, tmp_path):
    writer = SessionStore(record).open()                       # the service keeps running during a backup
    writer.add_patient("P-018")
    out = backup.create(record, tmp_path / "backups", key, now=datetime(2026, 9, 21, 2, 0))
    writer.close()
    assert out.name == "limber-20260921-020000.db.enc"
    blob = out.read_bytes()
    assert b"SQLite format 3" not in blob and b"P-017" not in blob and b"Post-op" not in blob
    restored = tmp_path / "restore" / "ptassist.db"
    backup.restore(out, restored, key)
    with SessionStore(restored).open() as s:
        assert {p.id for p in s.list_patients()} >= {"P-017", "P-018"}
        assert s.get_patient_thresholds("P-017") == {"form_drop": 8}
    assert backup.verify(out, key) is True


def test_wrong_key_and_corruption_are_refused(record, key, tmp_path):
    out = backup.create(record, tmp_path / "backups", key)
    other = backup.load_backup_key(tmp_path / "secrets" / "other.key")
    with pytest.raises(PTLogError):
        backup.restore(out, tmp_path / "x.db", other)
    assert backup.verify(out, other) is False
    data = bytearray(out.read_bytes())
    data[len(data) // 2] ^= 0xFF
    out.write_bytes(bytes(data))
    assert backup.verify(out, key) is False
    assert not (tmp_path / "x.db").exists()


def test_restore_never_overwrites_silently(record, key, tmp_path):
    out = backup.create(record, tmp_path / "backups", key)
    with pytest.raises(PTLogError) as err:
        backup.restore(out, record, key)
    assert "--force" in str(err.value)
    backup.restore(out, record, key, force=True)
    assert sqlite3.connect(str(record)).execute("SELECT COUNT(*) FROM patients").fetchone()[0] >= 1


def test_retention_keeps_the_newest_fourteen(record, key, tmp_path):
    dest = tmp_path / "backups"
    start = datetime(2026, 9, 1, 2, 0)
    for day in range(20):
        backup.create(record, dest, key, now=start + timedelta(days=day), keep=14)
    names = sorted(p.name for p in dest.glob("limber-*.db.enc"))
    assert len(names) == 14 and names[0] == "limber-20260907-020000.db.enc" and names[-1] == "limber-20260920-020000.db.enc"
    (dest / "notes.txt").write_text("not a backup")
    backup.create(record, dest, key, now=start + timedelta(days=21), keep=14)
    assert (dest / "notes.txt").exists()                      # only Limber's own backup files are ever removed


def test_backup_key_file_is_private(tmp_path):
    import os, stat
    path = tmp_path / "k" / "backup.key"
    k1 = backup.load_backup_key(path)
    assert backup.load_backup_key(path) == k1 and stat.S_IMODE(os.stat(path).st_mode) == 0o600
