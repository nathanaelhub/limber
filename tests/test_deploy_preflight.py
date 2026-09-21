"""Feature 009 T002 — the service refuses to start in an unsafe configuration, and says why."""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from src.deploy import preflight
from src.portal import admin
from src.ptlog.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "interfaces" / "cli.py"
PASSWORD = "a long therapist password"
GOOD = dict(public_origin="https://limber.example.org", therapist_url="https://limber.example.org/therapist")


@pytest.fixture
def ready(tmp_path, monkeypatch):
    """A data directory that passes every check."""
    monkeypatch.delenv("PTASSIST_PORTAL_KEY", raising=False)
    db = tmp_path / "data" / "ptassist.db"
    assets = tmp_path / "vendor"
    (assets / "lightning").mkdir(parents=True)
    (assets / "lightning" / "model.json").write_text("{}")
    secret = tmp_path / "therapist_password"
    secret.write_text(PASSWORD + "\n")
    preflight.initialise(db, password_file=secret)
    return db, assets


def problems(db, assets, **overrides):
    return [c.name for c in preflight.run(db, assets_dir=assets, **{**GOOD, **overrides}) if not c.ok]


def test_a_ready_installation_passes(ready):
    db, assets = ready
    checks = preflight.run(db, assets_dir=assets, **GOOD)
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert {c.name for c in checks} == {"therapist_password", "server_key", "record_writable", "pose_assets",
                                        "public_origin", "therapist_url"}


def test_each_failure_is_named_and_explained(ready, tmp_path):
    db, assets = ready
    with SessionStore(db).open() as s:
        admin.clear_password(s)
    assert problems(db, assets) == ["therapist_password"]
    (db.parent / "portal.key").unlink()
    assert "server_key" in problems(db, assets)
    assert problems(db, tmp_path / "nowhere")[-1] == "pose_assets" or "pose_assets" in problems(db, tmp_path / "nowhere")
    assert "public_origin" in problems(db, assets, public_origin="http://limber.example.org")
    assert "public_origin" in problems(db, assets, public_origin=None)
    assert "therapist_url" in problems(db, assets, therapist_url="https://elsewhere.example.com/therapist")
    for check in preflight.run(db, assets_dir=assets, public_origin=None, therapist_url=None):
        assert check.ok or len(check.detail) > 20                   # every failure carries a plain explanation


def test_record_must_be_writable(ready):
    db, assets = ready
    os.chmod(db.parent, stat.S_IRUSR | stat.S_IXUSR)
    try:
        assert "record_writable" in problems(db, assets)
    finally:
        os.chmod(db.parent, stat.S_IRWXU)


def test_initialise_is_private_and_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PTASSIST_PORTAL_KEY", raising=False)
    db = tmp_path / "data" / "ptassist.db"
    secret = tmp_path / "pw"
    secret.write_text(PASSWORD)
    done = preflight.initialise(db, password_file=secret)
    assert done == ["server key created", "therapist password set"]
    assert stat.S_IMODE(os.stat(db.parent / "portal.key").st_mode) == 0o600
    key = (db.parent / "portal.key").read_bytes()
    assert preflight.initialise(db, password_file=secret) == []     # nothing to do the second time
    assert (db.parent / "portal.key").read_bytes() == key
    with SessionStore(db).open() as s:
        assert admin.verify_password(s, PASSWORD)
    assert PASSWORD not in capsys.readouterr().out
    short = tmp_path / "short"
    short.write_text("short")
    with SessionStore(db).open() as s:
        admin.clear_password(s)
    with pytest.raises(Exception):
        preflight.initialise(db, password_file=short)


def test_cli_exit_codes(ready, tmp_path):
    db, assets = ready
    env = {**os.environ, "PTASSIST_DB": str(db)}
    ok = subprocess.run([sys.executable, str(CLI), "deploy", "preflight", "--public-origin", GOOD["public_origin"],
                         "--therapist-url", GOOD["therapist_url"], "--assets-dir", str(assets)],
                        env=env, capture_output=True, text=True, cwd=REPO_ROOT, timeout=90)
    assert ok.returncode == 0 and "ready" in ok.stdout.lower(), ok.stdout + ok.stderr
    bad = subprocess.run([sys.executable, str(CLI), "deploy", "preflight", "--public-origin", "http://plain.example",
                          "--assets-dir", str(assets)], env=env, capture_output=True, text=True, cwd=REPO_ROOT, timeout=90)
    assert bad.returncode == 1 and "https" in (bad.stdout + bad.stderr).lower()
