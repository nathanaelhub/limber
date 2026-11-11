"""Feature 020 slice A: the record on libSQL behaves like sqlite3 (FR-002), and the hosted-demo guard (FR-009).

These run the libSQL client against a local file (LIMBER_DB_BACKEND=libsql), so no network or Turso account is
needed. The rules are the four differences the G1 spike found, plus the write lock it found next.
"""

import sqlite3
import threading

import pytest

pytest.importorskip("libsql")

from src.ptlog import backend
from src.ptlog.store import SessionStore


@pytest.fixture
def libsql_mode(monkeypatch):
    monkeypatch.setenv("LIMBER_DB_BACKEND", "libsql")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)


def _conn(path):
    return backend.connect(path)


def test_local_sqlite_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("LIMBER_DB_BACKEND", raising=False)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    conn = backend.connect(tmp_path / "r.db")
    assert isinstance(conn, sqlite3.Connection) and not backend.hosted()


def test_rows_are_read_by_column_name(tmp_path, libsql_mode):
    c = _conn(tmp_path / "r.db")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE p (id INTEGER PRIMARY KEY, name TEXT)")
    c.execute("INSERT INTO p (name) VALUES ('a')")
    row = c.execute("SELECT id, name FROM p").fetchone()
    assert row["name"] == "a" and row[0] == 1 and row.keys() == ["id", "name"] and dict(row) == {"id": 1, "name": "a"}
    assert [r["name"] for r in c.execute("SELECT name FROM p")] == ["a"]


def test_lastrowid_belongs_to_its_own_statement(tmp_path, libsql_mode):
    """libSQL's lastrowid follows the connection's latest insert; the store reads it after a second insert."""
    c = _conn(tmp_path / "r.db")
    c.execute("CREATE TABLE p (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
    first = c.execute("INSERT INTO p (name) VALUES ('first')")
    c.execute("INSERT INTO p (name) VALUES ('second')")
    assert first.lastrowid == 1


def test_errors_keep_their_sqlite3_types(tmp_path, libsql_mode):
    c = _conn(tmp_path / "r.db")
    c.execute("CREATE TABLE p (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL)")
    c.execute("INSERT INTO p (name) VALUES ('a')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO p (name) VALUES ('a')")
    with pytest.raises(sqlite3.OperationalError):
        c.execute("SELECT * FROM missing")


def test_a_script_runs_even_inside_an_open_transaction(tmp_path, libsql_mode):
    """libSQL silently skipped a script with its own BEGIN/COMMIT while a transaction was open (migrations 9, 10)."""
    path = tmp_path / "r.db"
    c = _conn(path)
    c.execute("CREATE TABLE a (x)")
    c.execute("INSERT INTO a VALUES (1)")                                   # a transaction is now open
    c.executescript("BEGIN; CREATE TABLE b (x); INSERT INTO b VALUES (2); COMMIT;")
    c.commit()
    c.close()
    again = _conn(path)
    assert again.execute("SELECT x FROM b").fetchone()[0] == 2 and again.execute("SELECT x FROM a").fetchone()[0] == 1


def test_one_write_transaction_at_a_time_per_instance(tmp_path, libsql_mode):
    """Turso rolls back a transaction left waiting for another writer, so writes in one process take turns."""
    path = tmp_path / "r.db"
    setup = _conn(path)
    setup.execute("CREATE TABLE t (v TEXT)")
    setup.commit()
    a = _conn(path)
    a.execute("INSERT INTO t VALUES ('a')")
    assert backend.WRITE_LOCK.locked()
    done = []

    def other_writer():
        b = _conn(path)
        b.execute("INSERT INTO t VALUES ('b')")
        b.commit()
        done.append(True)

    t = threading.Thread(target=other_writer)
    t.start()
    t.join(timeout=0.3)
    assert not done                                                        # waits for a's transaction
    a.commit()
    t.join(timeout=5)
    assert done and not backend.WRITE_LOCK.locked()
    assert sorted(r[0] for r in setup.execute("SELECT v FROM t").fetchall()) == ["a", "b"]


def test_rollback_and_close_release_the_write_lock(tmp_path, libsql_mode):
    c = _conn(tmp_path / "r.db")
    c.execute("CREATE TABLE t (v)")
    c.commit()
    c.execute("INSERT INTO t VALUES (1)")
    c.rollback()
    assert not backend.WRITE_LOCK.locked()
    c.execute("INSERT INTO t VALUES (2)")
    c.close()
    assert not backend.WRITE_LOCK.locked()


def test_the_whole_store_opens_and_works_on_libsql(tmp_path, libsql_mode):
    with SessionStore(tmp_path / "r.db").open() as s:
        s.add_patient("P-021", label="hip")
        assert [p.id for p in s.list_patients() if p.id == "P-021"] == ["P-021"]


# ---- the hosted-demo guard (FR-009, SC-005) -------------------------------------------------------------------

def _store_with_patient(path):
    s = SessionStore(path).open()
    s.add_patient("P-021", label="hip")
    return s


def test_guard_allows_an_empty_record_so_it_can_be_seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("LIMBER_DEMO", "1")
    with SessionStore(tmp_path / "r.db").open() as s:
        backend.check_hosted_record(s)


def test_guard_refuses_a_record_without_the_simulated_data_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("LIMBER_DEMO", "1")
    s = _store_with_patient(tmp_path / "r.db")
    with pytest.raises(backend.HostedRecordRefused, match="simulated"):
        backend.check_hosted_record(s)


def test_guard_refuses_without_demo_mode_even_with_the_marker(tmp_path, monkeypatch):
    monkeypatch.delenv("LIMBER_DEMO", raising=False)
    s = _store_with_patient(tmp_path / "r.db")
    backend.mark_simulated(s)
    with pytest.raises(backend.HostedRecordRefused, match="LIMBER_DEMO"):
        backend.check_hosted_record(s)


def test_guard_passes_a_marked_record_in_demo_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("LIMBER_DEMO", "1")
    s = _store_with_patient(tmp_path / "r.db")
    backend.mark_simulated(s)
    backend.check_hosted_record(s)


def test_a_hosted_store_refuses_to_open_an_unmarked_record(tmp_path, monkeypatch, libsql_mode):
    """SC-005: the guard runs inside SessionStore.open, so no entry point can skip it."""
    path = tmp_path / "r.db"
    _store_with_patient(path).close()
    monkeypatch.setenv("LIMBER_DEMO", "1")
    monkeypatch.setattr(backend, "hosted", lambda: True)
    with pytest.raises(backend.HostedRecordRefused):
        SessionStore(path).open()


def test_the_demo_seed_marks_its_record(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("seed_demo", Path(__file__).parent.parent / "scripts" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    db = tmp_path / "demo.db"
    seed.build(db, 7)
    with SessionStore(db).open() as s:
        assert s.clinic_setting(backend.MARKER) == "1"


# ---- keeping a hosted open fast (measured live: each remote round trip cost 200-300 ms from a laptop) -------

class _RecordingRaw:
    """Stands in for a libSQL replica connection and records what reaches it."""
    in_transaction = False

    def __init__(self):
        self.sent = []

    def execute(self, sql, args=()):
        self.sent.append(sql)

        class C:
            description, lastrowid, rowcount = None, None, -1

            def fetchone(self):
                return None

            def fetchall(self):
                return []
        return C()


def test_a_hosted_copy_does_not_send_connection_pragmas_to_turso():
    raw = _RecordingRaw()
    conn = backend.Connection(raw, replica=True)
    for pragma in ("PRAGMA journal_mode=WAL", "PRAGMA synchronous=FULL", "PRAGMA foreign_keys=ON"):
        conn.execute(pragma)
    conn.execute("SELECT 1")
    assert raw.sent == ["SELECT 1"]


def test_a_local_libsql_file_still_runs_them(tmp_path, libsql_mode):
    c = _conn(tmp_path / "r.db")
    assert c.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"


def test_opening_an_up_to_date_record_writes_nothing(tmp_path, libsql_mode):
    """Every write is a round trip to Turso; opening a store that needs no migration must make none."""
    path = tmp_path / "r.db"
    SessionStore(path).open().close()
    seen = []
    real_execute = backend.Connection.execute

    def spy(self, sql, params=()):
        seen.append(sql.lstrip().split(None, 1)[0].upper())
        return real_execute(self, sql, params)

    backend.Connection.execute = spy
    try:
        SessionStore(path).open().close()
    finally:
        backend.Connection.execute = real_execute
    assert not [s for s in seen if s in backend._WRITES], seen
