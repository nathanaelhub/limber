"""
Encrypted backups of the record (feature 009).

A backup is taken with SQLite's online backup while the service keeps running, encrypted with Fernet
(authenticated encryption from the `cryptography` package), and written as
`limber-YYYYMMDD-HHMMSS.db.enc`. Old backups beyond the retention count are removed. The backup key
is separate from the portal's server key and must be stored away from the backups themselves.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from src.ptlog.models import PTLogError

PREFIX, SUFFIX = "limber-", ".db.enc"
DEFAULT_KEEP = 14


def load_backup_key(path: Path) -> bytes:
    """The Fernet key for backups: LIMBER_BACKUP_KEY, or a private file created on first use."""
    env = os.environ.get("LIMBER_BACKUP_KEY")
    if env:
        return env.strip().encode()
    path = Path(path)
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    return key


def _snapshot(db_path: Path) -> bytes:
    """A consistent copy of the live database, through SQLite's online backup."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.db"
        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
        target = sqlite3.connect(str(copy))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return copy.read_bytes()


def create(db_path: Path, dest_dir: Path, key: bytes, now: Optional[datetime] = None, keep: int = DEFAULT_KEEP) -> Path:
    db_path, dest_dir = Path(db_path), Path(dest_dir)
    if not db_path.is_file():
        raise PTLogError(f"No record at {db_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    out = dest_dir / f"{PREFIX}{stamp}{SUFFIX}"
    partial = out.with_suffix(out.suffix + ".part")
    partial.write_bytes(Fernet(key).encrypt(_snapshot(db_path)))
    os.chmod(partial, 0o600)
    partial.replace(out)
    prune(dest_dir, keep)
    backup_media(db_path, dest_dir, key, now=now)
    return out


def prune(dest_dir: Path, keep: int = DEFAULT_KEEP) -> int:
    """Remove Limber's own backup files beyond the newest `keep`. Nothing else in the folder is touched."""
    files = sorted(Path(dest_dir).glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: p.name)
    old = files[:-keep] if keep > 0 else []
    for p in old:
        p.unlink()
    return len(old)


def _decrypt(backup_file: Path, key: bytes) -> bytes:
    try:
        data = Fernet(key).decrypt(Path(backup_file).read_bytes())
    except (InvalidToken, ValueError):
        raise PTLogError(f"{backup_file} could not be decrypted: wrong key, or the file is damaged") from None
    if not data.startswith(b"SQLite format 3"):
        raise PTLogError(f"{backup_file} does not contain a Limber record")
    return data


def verify(backup_file: Path, key: bytes) -> bool:
    """True when the file decrypts, is a SQLite database, and passes SQLite's integrity check."""
    try:
        data = _decrypt(backup_file, key)
    except PTLogError:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "check.db"
        copy.write_bytes(data)
        conn = sqlite3.connect(str(copy))
        try:
            return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        except sqlite3.Error:
            return False
        finally:
            conn.close()


def backup_media(db_path: Path, dest_dir: Path, key: bytes, now: Optional[datetime] = None) -> int:
    """Copy each live media file that has not been backed up yet, encrypted, to dest_dir/media/<id>.<ext>.enc.
    Copied once per file; removed here when its row is deleted. Returns how many were copied."""
    from src.ptlog.store import SessionStore
    media_root = Path(dest_dir) / "media"
    copied = 0
    with SessionStore(db_path).open() as store:
        rows = store.media_list()
        for m in rows:
            enc = media_root / f"{m.id}.{m.ext}.enc"
            if m.deleted_at is not None:
                enc.unlink(missing_ok=True)
                continue
            source = store.media_dir / m.patient_id / f"{m.id}.{m.ext}"
            if m.backed_up_at and enc.is_file():
                continue
            if not source.is_file():
                continue
            media_root.mkdir(parents=True, exist_ok=True)
            partial = enc.with_suffix(".part")
            partial.write_bytes(Fernet(key).encrypt(source.read_bytes()))
            os.chmod(partial, 0o600)
            partial.replace(enc)
            store.media_update(m.id, backed_up_at=(now or datetime.now()).isoformat())
            copied += 1
    return copied


def restore_media(media_backup_dir: Path, db_path: Path, key: bytes) -> int:
    """Put every backed-up file that the (restored) record still references back under data/media/."""
    from src.ptlog.store import SessionStore
    restored = 0
    with SessionStore(db_path).open() as store:
        for m in store.media_list(live_only=True):
            enc = Path(media_backup_dir) / f"{m.id}.{m.ext}.enc"
            if not enc.is_file():
                continue
            target = store.media_dir / m.patient_id / f"{m.id}.{m.ext}"
            target.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(target.parent, 0o700)
            try:
                target.write_bytes(Fernet(key).decrypt(enc.read_bytes()))
            except (InvalidToken, ValueError):
                raise PTLogError(f"{enc.name} could not be decrypted with this key") from None
            os.chmod(target, 0o600)
            restored += 1
    return restored


def restore(backup_file: Path, db_path: Path, key: bytes, force: bool = False,
            media_backup_dir: Optional[Path] = None) -> Path:
    """Write the backup's record to `db_path`. Stop the service first. Never overwrites without force."""
    db_path = Path(db_path)
    if db_path.exists() and not force:
        raise PTLogError(f"{db_path} already exists. Stop Limber, keep a copy of that file, and repeat with --force.")
    data = _decrypt(backup_file, key)                     # nothing is written when this fails
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    partial = db_path.with_suffix(db_path.suffix + ".restoring")
    partial.write_bytes(data)
    partial.replace(db_path)
    if media_backup_dir is not None and Path(media_backup_dir).is_dir():
        restore_media(media_backup_dir, db_path, key)
    return db_path
