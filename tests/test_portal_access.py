"""Feature 007 T009 — access codes, keyed lookup, the server key, the login limiter, sign-in rules."""

import os
import re
import stat
from datetime import timedelta

import pytest

from src.portal import access
from src.ptlog.models import PortalError
from src.ptlog.store import SessionStore

KEY = b"k" * 32
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-020")
        yield s


class TestCodes:
    def test_format_alphabet_and_uniqueness(self):
        codes = {access.generate_code() for _ in range(1000)}
        assert len(codes) == 1000
        for code in list(codes)[:50]:
            assert re.fullmatch(r"[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}", code)
            assert set(code.replace("-", "")) <= set(ALPHABET)

    def test_normalize_is_forgiving_about_typing(self):
        assert access.normalize(" 7k3m-qx2p 9rtd ") == "7K3MQX2P9RTD"
        assert access.normalize("OIL0-0000-0000") == "01100000" + "0000"          # O→0, I→1, L→1
        for bad in ("", "7K3M-QX2P", "7K3M-QX2P-9RTD-AAAA", "7K3M-QX2P-9RT!", None, "U" * 12):
            with pytest.raises(PortalError):
                access.normalize(bad)

    def test_lookup_hash_is_keyed(self):
        a = access.lookup_hash(KEY, "7K3MQX2P9RTD")
        assert a == access.lookup_hash(KEY, "7K3MQX2P9RTD") and re.fullmatch(r"[0-9a-f]{64}", a)
        assert a != access.lookup_hash(b"x" * 32, "7K3MQX2P9RTD") and "7K3M" not in a

    def test_client_marker_hides_the_address(self):
        m = access.client_marker(KEY, "203.0.113.7")
        assert re.fullmatch(r"[0-9a-f]{16}", m) and "203" not in m
        assert m == access.client_marker(KEY, "203.0.113.7") != access.client_marker(KEY, "203.0.113.8")


class TestKeyFile:
    def test_created_private_and_reused(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PTASSIST_PORTAL_KEY", raising=False)
        path = tmp_path / "data" / "portal.key"
        key = access.load_key(path)
        assert len(key) == 32 and access.load_key(path) == key
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    def test_environment_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PTASSIST_PORTAL_KEY", "ab" * 32)
        assert access.load_key(tmp_path / "unused.key") == bytes.fromhex("ab" * 32)
        assert not (tmp_path / "unused.key").exists()
        monkeypatch.setenv("PTASSIST_PORTAL_KEY", "short")
        with pytest.raises(PortalError):
            access.load_key(tmp_path / "unused.key")


class TestLimiter:
    def test_five_failures_then_a_growing_lockout(self, fake_clock):
        lim = access.LoginLimiter(clock=fake_clock)
        for _ in range(5):
            assert lim.retry_after("c1") == 0
            lim.failure("c1")
        assert lim.retry_after("c1") == 60 and lim.retry_after("c2") == 0
        fake_clock.advance(61)
        assert lim.retry_after("c1") == 0
        lim.failure("c1")                                   # still inside the fifteen minutes: locked again, longer
        assert lim.retry_after("c1") == 120
        fake_clock.advance(16 * 60)
        assert lim.retry_after("c1") == 0

    def test_success_clears_and_the_global_breaker_trips(self, fake_clock):
        lim = access.LoginLimiter(clock=fake_clock)
        for _ in range(4):
            lim.failure("c1")
        lim.success("c1")
        lim.failure("c1")
        assert lim.retry_after("c1") == 0
        for i in range(30):
            lim.failure(f"bot{i}")
        assert lim.retry_after("someone-new") > 0
        fake_clock.advance(61)
        assert lim.retry_after("someone-new") == 0


class TestIssueAndSignIn:
    def test_issue_stores_only_the_hash(self, store):
        code, status = access.issue_code(store, KEY, "P-017", days=30)
        assert status.state == "active" and store.portal_lookup(access.lookup_hash(KEY, access.normalize(code)))
        dump = "\n".join(str(tuple(r)) for t in ("portal_access", "portal_audit")
                         for r in store.conn.execute(f"SELECT * FROM {t}"))
        assert code not in dump and access.normalize(code) not in dump
        assert [a.event for a in store.portal_audit_list("P-017")] == ["code_created"]
        with pytest.raises(PortalError):
            access.issue_code(store, KEY, "P-017", days=0)
        with pytest.raises(PortalError):
            access.issue_code(store, KEY, "P-017", days=400)

    def test_sign_in_and_current_patient_limits(self, store, fake_clock):
        code, _ = access.issue_code(store, KEY, "P-017")
        lim = access.LoginLimiter(clock=fake_clock)
        token = access.sign_in(store, KEY, code.lower(), "client-a", lim, clock=fake_clock)
        assert len(token) >= 40 and access.current_patient(store, token, clock=fake_clock) == "P-017"
        assert token not in "\n".join(str(tuple(r)) for r in store.conn.execute("SELECT * FROM portal_sessions"))
        fake_clock.advance(29 * 60)
        assert access.current_patient(store, token, clock=fake_clock) == "P-017"      # touching keeps it alive
        fake_clock.advance(31 * 60)
        assert access.current_patient(store, token, clock=fake_clock) is None          # idle for more than 30 minutes
        token = access.sign_in(store, KEY, code, "client-a", lim, clock=fake_clock)
        for _ in range(30):
            fake_clock.advance(25 * 60)
            alive = access.current_patient(store, token, clock=fake_clock)
        assert alive is None                                                           # absolute limit of 12 hours
        assert access.current_patient(store, "not-a-token", clock=fake_clock) is None
        assert access.current_patient(store, None, clock=fake_clock) is None

    def test_refusals_look_the_same_and_are_logged(self, store, fake_clock):
        code, _ = access.issue_code(store, KEY, "P-017", days=1)
        lim = access.LoginLimiter(clock=fake_clock)
        with pytest.raises(access.AccessDenied) as wrong:
            access.sign_in(store, KEY, "0000-0000-0000", "c", lim, clock=fake_clock)
        with pytest.raises(access.AccessDenied) as malformed:
            access.sign_in(store, KEY, "nonsense", "c", lim, clock=fake_clock)
        store.portal_set_code("P-017", access.lookup_hash(KEY, access.normalize(code)),
                              fake_clock() - timedelta(seconds=1))                  # the same code, now expired
        with pytest.raises(access.AccessDenied) as expired:
            access.sign_in(store, KEY, code, "c", lim, clock=fake_clock)
        code2, _ = access.issue_code(store, KEY, "P-017")
        store.portal_revoke("P-017")
        with pytest.raises(access.AccessDenied) as revoked:
            access.sign_in(store, KEY, code2, "c", lim, clock=fake_clock)
        code3, _ = access.issue_code(store, KEY, "P-020")
        store.discharge("P-020")
        with pytest.raises(access.AccessDenied) as discharged:
            access.sign_in(store, KEY, code3, "c", lim, clock=fake_clock)
        assert len({str(e.value) for e in (wrong, malformed, expired, revoked, discharged)}) == 1
        details = [a.detail for a in store.portal_audit_list() if a.event == "login_failed"]
        assert sorted(details) == ["discharged", "expired", "revoked", "unknown_code", "unknown_code"]
        with pytest.raises(access.LockedOut) as locked:                                 # that was the fifth failure
            access.sign_in(store, KEY, code2, "c", lim, clock=fake_clock)
        assert locked.value.retry_after >= 60
        assert store.portal_audit_list()[0].event == "locked_out"

    def test_sign_out(self, store, fake_clock):
        code, _ = access.issue_code(store, KEY, "P-017")
        token = access.sign_in(store, KEY, code, "c", access.LoginLimiter(clock=fake_clock), clock=fake_clock)
        access.sign_out(store, token, "c")
        assert access.current_patient(store, token, clock=fake_clock) is None
        assert store.portal_audit_list("P-017")[0].event == "logout"


class TestDeviceSignIn:
    """Feature 010: an installed patient app stays signed in on the device for 30 days."""

    def test_device_sign_in_ignores_idle_and_lasts_thirty_days(self, store, fake_clock):
        code, _ = access.issue_code(store, KEY, "P-017")
        lim = access.LoginLimiter(clock=fake_clock)
        token = access.sign_in(store, KEY, code, "phone", lim, clock=fake_clock, device=True)
        fake_clock.advance(20 * 86400)                                       # idle for twenty days
        assert access.current_patient(store, token, clock=fake_clock) == "P-017"
        fake_clock.advance(11 * 86400)
        assert access.current_patient(store, token, clock=fake_clock) is None

    def test_browser_sign_in_keeps_the_short_limits(self, store, fake_clock):
        code, _ = access.issue_code(store, KEY, "P-017")
        token = access.sign_in(store, KEY, code, "pc", access.LoginLimiter(clock=fake_clock), clock=fake_clock)
        fake_clock.advance(31 * 60)
        assert access.current_patient(store, token, clock=fake_clock) is None

    def test_revoke_or_reissue_ends_device_sign_ins_and_three_devices_max(self, store, fake_clock):
        code, _ = access.issue_code(store, KEY, "P-017")
        lim = access.LoginLimiter(clock=fake_clock)
        tokens = [access.sign_in(store, KEY, code, f"d{i}", lim, clock=fake_clock, device=True) for i in range(4)]
        assert access.current_patient(store, tokens[0], clock=fake_clock) is None          # fourth device pushed the first out
        assert all(access.current_patient(store, t, clock=fake_clock) == "P-017" for t in tokens[1:])
        access.issue_code(store, KEY, "P-017")
        assert all(access.current_patient(store, t, clock=fake_clock) is None for t in tokens)
