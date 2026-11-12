"""Feature 020 slice C: what Vercel's instances must share besides the record and the files (FR-007, FR-008,
FR-010 to FR-012), and the v18 upgrade that holds the sign-in limiter's counts."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from src.portal import access
from src.ptlog import backend
from src.ptlog.models import PortalError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore
from tests.fixtures.golden.sequence import FixedClock


# ---- v18: the limiter's tables ----------------------------------------------------------------------------------

def test_the_v18_upgrade_keeps_every_row(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, sql in MIGRATIONS:
        if version > 17:
            break
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version VALUES (?, '2026-03-01T00:00:00')", (version,))
    for pid, builtin in (("P-017", 0), ("unassigned", 1)):
        conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES (?, NULL, NULL, '2026-03-01', ?)",
                     (pid, builtin))
    conn.commit()
    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    conn.close()
    with SessionStore(tmp_db).open() as s:
        after = {t: s.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for (t,) in s.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    assert SCHEMA_VERSION == 18 and [v for v, _ in MIGRATIONS][-1] == 18
    for table, n in before.items():
        assert after[table] == (n + 1 if table == "schema_version" else n), table
    assert {"login_failures", "login_lockouts"} <= set(after)


# ---- the sign-in limiter in the record (FR-007) -------------------------------------------------------------------

@pytest.fixture
def two_instances(tmp_db):
    """Two portal instances sharing one record, each with its own limiter object, as on Vercel."""
    clock = FixedClock(datetime(2026, 11, 11, 9, 0, 0))
    store = SessionStore(tmp_db, clock=clock).open()
    yield store, access.RecordLoginLimiter(clock=clock), access.RecordLoginLimiter(clock=clock), clock
    store.close()


def test_failures_on_two_instances_count_together(two_instances):
    store, a, b, _ = two_instances
    for limiter in (a, b, a, b, a):                                       # five failures, split across instances
        assert limiter.retry_after("203.0.113.9", store) == 0
        limiter.failure("203.0.113.9", store)
    assert a.retry_after("203.0.113.9", store) > 0 and b.retry_after("203.0.113.9", store) > 0
    assert b.retry_after("198.51.100.1", store) == 0                      # another client is unaffected


def test_a_success_clears_the_count_everywhere(two_instances):
    store, a, b, _ = two_instances
    for _ in range(4):
        a.failure("c1", store)
    b.success("c1", store)
    a.failure("c1", store)
    assert b.retry_after("c1", store) == 0


def test_the_lockout_ends(two_instances):
    store, a, b, clock = two_instances
    for _ in range(5):
        a.failure("c1", store)
    wait = b.retry_after("c1", store)
    assert 0 < wait <= access.LoginLimiter.BASE_LOCKOUT
    clock.set(clock() + timedelta(seconds=access.LoginLimiter.WINDOW + 1))
    assert b.retry_after("c1", store) == 0


def test_no_client_address_is_stored(two_instances):
    store, a, *_ = two_instances
    a.failure("203.0.113.9", store)
    dump = " ".join(str(tuple(r)) for t in ("login_failures", "login_lockouts") for r in store.conn.execute(f"SELECT * FROM {t}"))
    assert "203.0.113.9" not in dump


def test_the_in_memory_limiter_ignores_the_store(two_instances):
    store, *_ = two_instances
    local = access.LoginLimiter()
    for _ in range(5):
        local.failure("c1", store)
    assert local.retry_after("c1", store) > 0
    assert store.conn.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0] == 0


# ---- the server key (FR-008) ------------------------------------------------------------------------------------

def test_a_hosted_install_needs_the_key_in_its_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("PTASSIST_PORTAL_KEY", raising=False)
    monkeypatch.setattr(backend, "hosted", lambda: True)
    with pytest.raises(PortalError, match="PTASSIST_PORTAL_KEY"):
        access.load_key(tmp_path / "portal.key")
    assert not (tmp_path / "portal.key").exists()
    monkeypatch.setenv("PTASSIST_PORTAL_KEY", "ab" * 32)
    assert access.load_key(tmp_path / "portal.key") == bytes.fromhex("ab" * 32)


def test_a_local_install_still_makes_its_own_key(tmp_path, monkeypatch):
    monkeypatch.delenv("PTASSIST_PORTAL_KEY", raising=False)
    assert len(access.load_key(tmp_path / "portal.key")) == 32 and (tmp_path / "portal.key").exists()


# ---- health (FR-011) --------------------------------------------------------------------------------------------

def _client(tmp_db, **kw):
    from starlette.testclient import TestClient
    from interfaces.patient_portal import create_app
    return TestClient(create_app(db_path=tmp_db, key=b"k" * 32, allowed_origins=["http://testserver"], **kw))


def test_health_reports_the_file_store(tmp_db):
    body = _client(tmp_db).get("/api/health").json()
    assert body["ok"] and body["record"] == "ok" and body["files"] == "ok"


def test_health_is_503_when_the_file_store_is_down(tmp_db, monkeypatch):
    from src.media import files

    class Down(files.LocalFiles):
        def list(self, prefix):
            raise OSError("bucket unreachable")
    monkeypatch.setattr(files, "at", lambda media_dir: Down(media_dir))
    r = _client(tmp_db).get("/api/health")
    assert r.status_code == 503 and r.json()["files"] == "unavailable"


# ---- resetting the hosted demo (FR-010, FR-012) -----------------------------------------------------------------

def test_the_reset_loads_a_fresh_seed_in_foreign_key_order(tmp_path, monkeypatch):
    """Turso stops a remote script at the first error without raising (slice A), so the reset loads row by row,
    parents first. Here the target is a local file through the same libSQL client."""
    from src.deploy import demo
    monkeypatch.setenv("LIMBER_DB_BACKEND", "libsql")
    target = tmp_path / "hosted.db"
    report = demo.reset(target, connect=lambda: backend.connect(target))
    with SessionStore(target).open() as s:
        assert s.clinic_setting(backend.MARKER) == "1"
        assert len([p for p in s.list_patients() if not p.is_builtin]) == report["patients"] > 0
        assert int(s.clinic_setting("assist_daily_cap")) == demo.HOSTED_AI_CAP == 10
    assert report["codes"] and all(len(code) == 14 for code in report["codes"].values())


def test_the_reset_refuses_a_record_that_isnt_the_demo(tmp_path, monkeypatch):
    from src.deploy import demo
    monkeypatch.setenv("LIMBER_DB_BACKEND", "libsql")
    target = tmp_path / "real.db"
    with SessionStore(target).open() as s:
        s.add_patient("P-099")
    with pytest.raises(backend.HostedRecordRefused):
        demo.reset(target, connect=lambda: backend.connect(target))
    with SessionStore(target).open() as s:
        assert [p.id for p in s.list_patients() if p.id == "P-099"] == ["P-099"]       # untouched


def test_the_reset_builds_locally_and_copies_the_demo_files(tmp_path, monkeypatch):
    """The seed is built as a plain local file even when the hosted settings are present (otherwise it would be
    written through Turso and R2 as it is built), then its files replace the old ones in the file store."""
    from src.deploy import demo
    from src.media import files
    monkeypatch.setenv("LIMBER_DB_BACKEND", "libsql")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://never-used.example")      # would fail if the build used it
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "never-used")
    target = tmp_path / "hosted.db"
    store_files = files.LocalFiles(tmp_path / "bucket")
    store_files.put_bytes("P-021/old-demo-file.wav", b"old")
    import os
    real_connect = backend.connect

    def only_local(*a, **k):
        assert not os.environ.get("TURSO_DATABASE_URL"), "the seed was opened with the Turso settings present"
        return real_connect(*a, **k)
    monkeypatch.setattr(backend, "connect", only_local)
    target_conn = backend.Connection(__import__("libsql").connect(str(target)))
    demo.reset(target, connect=lambda: target_conn, files_target=store_files)
    stored = store_files.list("")
    assert "P-021/old-demo-file.wav" not in stored
    assert any(name.startswith("P-021/") and name.endswith(".m4a") for name in stored)       # the seed's voice note
    assert any(name.startswith("P-021/attachments/") for name in stored)                     # and its photo
