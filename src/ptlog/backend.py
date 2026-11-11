"""
Where the record lives (feature 020). Local and self-hosted installs use a SQLite file through `sqlite3`, as
always. The hosted demo uses libSQL (Turso): each instance keeps a local copy (an embedded replica) that it reads,
sends writes to Turso, and syncs when the store opens, so it sees other instances' writes.

The libSQL client is wrapped so the store sees `sqlite3` behaviour. The gate G1 spike found where it differs:
rows are plain tuples; `lastrowid` follows the connection's latest insert, not the statement's; every error is a
`ValueError`; a script with its own BEGIN/COMMIT is skipped silently while a transaction is open; and Turso rolls
back a write transaction left waiting behind another writer. Each difference is handled here and has a test.

Principle III (amendment 1.5.0): a hosted record must hold simulated data only. `check_hosted_record` refuses
anything else, and `SessionStore.open` calls it on every hosted open.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, List, Optional

MARKER = "simulated_data"            # clinic setting written by scripts/seed_demo.py
WRITE_LOCK = threading.Lock()        # one write transaction at a time in this process (see Connection._begin_write)
LOCK_WAIT_SECONDS = 30.0             # fail loudly rather than hang if a writer never finishes
_WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")
# Connection settings the store sends on open. On a replica they go to Turso as a round trip each (measured
# 200-300 ms from a laptop) and change nothing there: Turso enforces foreign keys and manages its own journal.
_REPLICA_SKIPS = ("PRAGMA JOURNAL_MODE", "PRAGMA SYNCHRONOUS", "PRAGMA FOREIGN_KEYS")


class HostedRecordRefused(RuntimeError):
    """A hosted install pointed at a record that isn't the simulated demo."""


def _turso() -> Optional[tuple]:
    url, token = os.environ.get("TURSO_DATABASE_URL"), os.environ.get("TURSO_AUTH_TOKEN")
    return (url, token) if url and token else None


def hosted() -> bool:
    """True when the record is the hosted demo database (Turso)."""
    return _turso() is not None


def _uses_libsql() -> bool:
    return _turso() is not None or os.environ.get("LIMBER_DB_BACKEND") == "libsql"


def connect(path: Path | str, timeout: float = 5.0, check_same_thread: bool = True):
    """The one place a connection to the record is made."""
    if not _uses_libsql():
        return sqlite3.connect(str(path), timeout=timeout, check_same_thread=check_same_thread)
    import libsql
    turso = _turso()
    if turso:
        raw = libsql.connect(str(path), sync_url=turso[0], auth_token=turso[1])
        raw.sync()                                   # see other instances' writes (FR-003a)
        return Connection(raw, replica=True)
    return Connection(libsql.connect(str(path)))     # tests: the same client against a local file


def connect_primary():
    """A direct connection to the hosted database itself (no local copy), for resetting the demo."""
    turso = _turso()
    if not turso:
        raise HostedRecordRefused("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN to reset the hosted demo.")
    import libsql
    return Connection(libsql.connect(turso[0], auth_token=turso[1]))


# ---------------------------------------------------------------- the hosted-demo guard (FR-009)

def mark_simulated(store) -> None:
    store.set_clinic_setting(MARKER, "1")


def check_hosted_record(store) -> None:
    """Refuse a hosted record unless the install is in demo mode and the record is the simulated demo. An empty
    record (no patients yet) is allowed, so the demo can be seeded."""
    if os.environ.get("LIMBER_DEMO") != "1":
        raise HostedRecordRefused("A hosted record is allowed only for the demo: set LIMBER_DEMO=1. Real patients' "
                                  "records stay on the clinic's own machine (constitution, Principle III).")
    real_patients = store.conn.execute("SELECT COUNT(*) FROM patients WHERE is_builtin = 0").fetchone()[0]
    if real_patients and store.clinic_setting(MARKER) != "1":
        raise HostedRecordRefused("This hosted record has patients but no simulated-data marker, so it may not be "
                                  "the demo. Limber will not open it. Reset it with the demo seed.")


# ---------------------------------------------------------------- sqlite3 behaviour on top of libSQL (FR-002)

def _translate(error: Exception) -> sqlite3.Error:
    message = str(error)
    if "constraint failed" in message:
        return sqlite3.IntegrityError(message)
    return sqlite3.OperationalError(message)


class Row(tuple):
    """Like sqlite3.Row: by position or by column name, with keys() so dict(row) works."""

    def __new__(cls, values: Iterable[Any], names: List[str]):
        row = super().__new__(cls, values)
        row._names = names
        return row

    def keys(self) -> List[str]:
        return list(self._names)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return tuple.__getitem__(self, self._names.index(key))
            except ValueError:
                raise IndexError(f"No item with that key: {key}") from None
        return tuple.__getitem__(self, key)


class Cursor:
    def __init__(self, cursor, named: bool):
        self._cursor, self._named = cursor, named
        self._names = [d[0] for d in cursor.description] if cursor.description else None
        # libSQL's lastrowid follows the connection's latest insert; sqlite3 keeps it per statement.
        self.lastrowid, self.rowcount = cursor.lastrowid, cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def _row(self, values):
        if values is None or not self._named or self._names is None:
            return values
        return Row(values, self._names)

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(r) for r in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class _EmptyCursor:
    description, lastrowid, rowcount = None, None, -1

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class Connection:
    """The parts of sqlite3.Connection the store uses, over a libSQL connection."""

    def __init__(self, raw, replica: bool = False):
        self._raw = raw
        self._replica = replica
        self.row_factory = None
        self._holds_write_lock = False

    def _run(self, fn, *args):
        try:
            return fn(*args)
        except ValueError as e:
            raise _translate(e) from None

    def _begin_write(self, sql: str) -> None:
        """Turso keeps one writer at a time and rolls back a transaction left waiting behind another, so writes
        in this process take turns: the lock is held from a transaction's first write to its commit or rollback."""
        if not self._holds_write_lock and sql.lstrip().upper().startswith(_WRITES):
            if not WRITE_LOCK.acquire(timeout=LOCK_WAIT_SECONDS):
                raise sqlite3.OperationalError("database is locked: another write in this process did not finish")
            self._holds_write_lock = True

    def _end_write(self) -> None:
        if self._holds_write_lock:
            self._holds_write_lock = False
            WRITE_LOCK.release()

    def execute(self, sql: str, params=()):
        if self._replica and sql.lstrip().upper().replace(" =", "=").startswith(_REPLICA_SKIPS):
            return _EmptyCursor()
        self._begin_write(sql)
        args = params if isinstance(params, dict) else tuple(params)
        try:
            cursor = self._run(self._raw.execute, sql, args)
        except Exception:
            if not self._raw.in_transaction:
                self._end_write()
            raise
        if not self._raw.in_transaction:            # a statement that committed by itself (e.g. DDL)
            self._end_write()
        return Cursor(cursor, self.row_factory is sqlite3.Row)

    def executemany(self, sql: str, seq):
        self._begin_write(sql)
        cursor = self._run(self._raw.executemany, sql, [tuple(p) for p in seq])
        return Cursor(cursor, False)

    def executescript(self, sql: str):
        # sqlite3 commits an open transaction first; libSQL silently skips a script with its own BEGIN/COMMIT
        # while one is open (migrations 9 and 10 created nothing in the spike).
        if self._raw.in_transaction:
            self.commit()
        if not WRITE_LOCK.acquire(timeout=LOCK_WAIT_SECONDS):
            raise sqlite3.OperationalError("database is locked: another write in this process did not finish")
        try:
            return self._run(self._raw.executescript, sql)
        finally:
            WRITE_LOCK.release()

    def commit(self) -> None:
        try:
            self._run(self._raw.commit)
        finally:
            self._end_write()

    def rollback(self) -> None:
        try:
            self._run(self._raw.rollback)
        finally:
            self._end_write()

    def close(self) -> None:
        try:
            if self._raw.in_transaction:
                self._raw.rollback()
            self._raw.close()
        finally:
            self._end_write()

    def __del__(self):
        # A connection dropped mid-transaction (sqlite3 rolls it back) must not keep every other writer waiting.
        if getattr(self, "_holds_write_lock", False):
            try:
                self._raw.rollback()
            except Exception:  # noqa: BLE001 — the connection may already be gone
                pass
            self._end_write()
