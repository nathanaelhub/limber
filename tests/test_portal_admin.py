"""Feature 007 US6 — one entry page with two doors: therapist sign-in beside the patient code."""

import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.portal import access, admin
from src.ptlog.models import PortalError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

KEY = b"k" * 32
ORIGIN = "http://testserver"
PASSWORD = "correct horse battery"
REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "interfaces" / "cli.py"


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-017")
        yield s


class TestPassword:
    def test_schema_and_status(self, store):
        tables = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert SCHEMA_VERSION >= 7 and {"portal_admin", "admin_signins", "admin_audit"} <= tables
        assert [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION
        assert admin.password_is_set(store) is False

    def test_set_verify_and_never_stored_in_the_clear(self, store):
        admin.set_password(store, PASSWORD)
        assert admin.password_is_set(store) and admin.verify_password(store, PASSWORD)
        assert not admin.verify_password(store, PASSWORD + "x") and not admin.verify_password(store, "")
        dump = "\n".join(str(tuple(r)) for r in store.conn.execute("SELECT * FROM portal_admin"))
        assert PASSWORD not in dump
        first = dump
        admin.set_password(store, PASSWORD)                          # a fresh salt every time
        assert "\n".join(str(tuple(r)) for r in store.conn.execute("SELECT * FROM portal_admin")) != first
        assert admin.clear_password(store) is True and admin.password_is_set(store) is False

    @pytest.mark.parametrize("bad", ["short", "", None, "a" * 11, " " * 20, "x" * 300])
    def test_password_rules(self, store, bad):
        with pytest.raises(PortalError):
            admin.set_password(store, bad)


class TestPassesAndSignIns:
    def test_pass_is_single_use_and_short_lived(self, store, fake_clock):
        admin.set_password(store, PASSWORD)
        p = admin.issue_pass(store, clock=fake_clock)
        token = admin.redeem_pass(store, p, clock=fake_clock)
        assert token and admin.signed_in(store, token, clock=fake_clock)
        assert admin.redeem_pass(store, p, clock=fake_clock) is None            # used
        late = admin.issue_pass(store, clock=fake_clock)
        fake_clock.advance(61)
        assert admin.redeem_pass(store, late, clock=fake_clock) is None         # expired
        assert admin.redeem_pass(store, "made-up", clock=fake_clock) is None
        assert p not in "\n".join(str(tuple(r)) for r in store.conn.execute("SELECT * FROM admin_signins"))

    def test_sign_in_lasts_eight_hours_and_ends_on_sign_out_or_password_change(self, store, fake_clock):
        admin.set_password(store, PASSWORD)
        token = admin.sign_in(store, PASSWORD, "c", access.LoginLimiter(clock=fake_clock), clock=fake_clock)
        fake_clock.advance(7 * 3600)
        assert admin.signed_in(store, token, clock=fake_clock)
        fake_clock.advance(2 * 3600)
        assert not admin.signed_in(store, token, clock=fake_clock)
        token = admin.sign_in(store, PASSWORD, "c", access.LoginLimiter(clock=fake_clock), clock=fake_clock)
        admin.sign_out(store, token, "c")
        assert not admin.signed_in(store, token, clock=fake_clock)
        token = admin.sign_in(store, PASSWORD, "c", access.LoginLimiter(clock=fake_clock), clock=fake_clock)
        admin.set_password(store, "another long password")
        assert not admin.signed_in(store, token, clock=fake_clock)
        assert not admin.signed_in(store, None, clock=fake_clock)

    def test_refusals_limits_and_history(self, store, fake_clock):
        admin.set_password(store, PASSWORD)
        lim = access.LoginLimiter(clock=fake_clock)
        for _ in range(5):
            with pytest.raises(access.AccessDenied):
                admin.sign_in(store, "wrong password here", "client-a", lim, clock=fake_clock)
        with pytest.raises(access.LockedOut):
            admin.sign_in(store, PASSWORD, "client-a", lim, clock=fake_clock)
        events = [(e["event"], e["client"]) for e in admin.history(store)]
        assert events[0] == ("locked_out", "client-a") and events.count(("login_failed", "client-a")) == 5
        assert ("password_set", None) in events
        assert PASSWORD not in str(admin.history(store)) and "wrong password" not in str(admin.history(store))

    def test_no_password_set(self, store, fake_clock):
        with pytest.raises(admin.NotConfigured):
            admin.sign_in(store, PASSWORD, "c", access.LoginLimiter(clock=fake_clock), clock=fake_clock)
        assert admin.signed_in(store, "anything", clock=fake_clock) is False


@pytest.fixture
def client(tmp_db):
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-017")
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN], therapist_url="http://therapist.test:8501")
    with TestClient(app, base_url=ORIGIN) as c:
        yield c, tmp_db


def admin_login(c, password):
    return c.post("/api/admin/login", json={"password": password}, headers={"Origin": ORIGIN})


class TestFrontPage:
    def test_both_doors_are_on_the_front_page(self, client):
        c, _ = client
        html = c.get("/").text
        assert 'id="signin"' in html and 'id="admin-signin"' in html
        assert "Therapist sign-in" in html and "I'm a patient" in html.replace("&#39;", "'").replace("’", "'")
        assert c.get("/api/health").json()["therapist_sign_in"] is False

    def test_without_a_password_the_door_explains(self, client):
        c, _ = client
        r = admin_login(c, PASSWORD)
        assert r.status_code == 409 and "not been set up" in r.json()["error"]

    def test_right_password_hands_over_with_a_single_use_pass(self, client):
        c, db = client
        with SessionStore(db).open() as s:
            admin.set_password(s, PASSWORD)
        assert c.get("/api/health").json()["therapist_sign_in"] is True
        r = admin_login(c, PASSWORD)
        assert r.status_code == 200
        url = r.json()["redirect"]
        m = re.fullmatch(r"http://therapist\.test:8501/\?pass=([A-Za-z0-9_\-]{20,})", url)
        assert m, url
        with SessionStore(db).open() as s:
            assert admin.redeem_pass(s, m.group(1)) and admin.redeem_pass(s, m.group(1)) is None
        assert "set-cookie" not in r.headers                         # the portal itself holds no therapist session

    def test_wrong_password_is_generic_and_shares_the_limits(self, client):
        c, db = client
        with SessionStore(db).open() as s:
            admin.set_password(s, PASSWORD)
        r = admin_login(c, "not the password!")
        assert r.status_code == 401 and r.json()["error"] == access.DENIED_ADMIN_MESSAGE
        for _ in range(4):
            admin_login(c, "not the password!")
        assert admin_login(c, PASSWORD).status_code == 429
        assert c.post("/api/login", json={"code": "0000-0000-0000"}, headers={"Origin": ORIGIN}).status_code == 429
        assert c.post("/api/admin/login", json={"password": PASSWORD}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_cli_sets_the_password_from_standard_input(cli_env):
    def run(*args, stdin=None):
        return subprocess.run([sys.executable, str(CLI), *args], env=cli_env, input=stdin, capture_output=True,
                              text=True, cwd=REPO_ROOT, timeout=90)
    assert "not set" in run("portal", "admin", "status").stdout
    r = run("portal", "admin", "set-password", "--stdin", stdin=PASSWORD + "\n")
    assert r.returncode == 0 and PASSWORD not in r.stdout + r.stderr
    assert "is set" in run("portal", "admin", "status").stdout
    assert run("portal", "admin", "set-password", "--stdin", stdin="short\n").returncode == 1
    assert run("portal", "admin", "clear").returncode == 0 and "not set" in run("portal", "admin", "status").stdout
