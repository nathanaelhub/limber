"""Feature 016 — accounts, roles, invitations, caseloads, and accessibility preferences (rules and record)."""

import sqlite3

import pytest

from src.portal import access, accounts, admin
from src.ptlog.models import Media, PortalError, PTLogError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

PASSWORD = "correct horse battery"


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        yield s


@pytest.fixture
def boss(store):
    """The first admin, made the way an installation makes one: from the command line."""
    return accounts.create_account(store, username="boss", display_name="Pat Admin", password=PASSWORD,
                                   role="admin")


def invite_and_accept(store, actor, role, username, fake_clock, **kw):
    token, _ = accounts.create_invite(store, actor, role, clock=fake_clock, **{
        k: v for k, v in kw.items() if k in ("therapist_id", "patient_id", "make_admin")})
    return accounts.accept_invite(store, token, display_name=kw.get("name", username.title()), username=username,
                                  password=PASSWORD, password_again=PASSWORD, prefs=kw.get("prefs"), clock=fake_clock)


# ----------------------------------------------------------------------------- schema and migration

class TestSchema:
    def test_v14_tables(self, store):
        tables = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert SCHEMA_VERSION >= 14 and [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION
        assert {"accounts", "invitations", "caseloads", "account_audit", "admin_signins"} <= tables
        assert "portal_admin" not in tables

    def test_upgrade_from_v13_with_a_password(self, tmp_db, fake_clock):
        import hashlib
        import secrets
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(PASSWORD.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32).hex()
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        for version, sql in MIGRATIONS:
            if version > 13:
                break
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_version VALUES (?, '2026-01-01')", (version,))
        conn.execute("INSERT INTO patients (id, created_at, is_builtin) VALUES ('P-017', '2026-01-01', 0)")
        conn.execute("INSERT INTO patients (id, created_at, is_builtin) VALUES ('P-021', '2026-01-01', 0)")
        conn.execute("INSERT INTO portal_admin VALUES (1, ?, ?, '2026-01-01')", (salt.hex(), digest))
        conn.commit()
        conn.close()
        with SessionStore(tmp_db, clock=fake_clock).open() as s:
            first = s.account_by_username("therapist")
            assert first.role == "therapist" and first.is_admin and first.status == "active"
            assert admin.verify_password(s, PASSWORD)                                   # the old password works
            assert accounts.authenticate(s, "therapist", PASSWORD, "c", access.LoginLimiter(clock=fake_clock)).id == first.id
            assert set(accounts.visible_patient_ids(s, first)) >= {"P-017", "P-021"}
            assert {r[0] for r in s.conn.execute("SELECT patient_id FROM caseloads")} == {"P-017", "P-021"}

    def test_upgrade_without_a_password_creates_no_account(self, store):
        assert store.account_list() == []


# ----------------------------------------------------------------------------- accounts and passwords

class TestAccounts:
    def test_create_and_authenticate(self, store, boss, fake_clock):
        lim = access.LoginLimiter(clock=fake_clock)
        assert boss.role == "admin" and boss.is_admin and not boss.is_therapist
        assert accounts.authenticate(store, "BOSS", PASSWORD, "c", lim).id == boss.id    # usernames ignore case
        dump = "\n".join(str(tuple(r)) for r in store.conn.execute("SELECT * FROM accounts"))
        assert PASSWORD not in dump

    @pytest.mark.parametrize("username", ["ab", "has space", "x" * 33, "", None, "-dash-first", "émile"])
    def test_username_rules(self, store, username):
        with pytest.raises(PortalError):
            accounts.create_account(store, username=username, display_name="A", password=PASSWORD, role="therapist")

    @pytest.mark.parametrize("name", ["", "   ", "x" * 61, "two\nlines", None])
    def test_display_name_rules(self, store, name):
        with pytest.raises(PortalError):
            accounts.create_account(store, username="someone", display_name=name, password=PASSWORD, role="therapist")

    @pytest.mark.parametrize("bad", ["short", "a" * 11, " " * 20, "x" * 300, None])
    def test_password_rules(self, store, bad):
        with pytest.raises(PortalError):
            accounts.create_account(store, username="someone", display_name="A", password=bad, role="therapist")

    def test_duplicate_username_is_refused_whatever_the_case(self, store, boss):
        with pytest.raises(PortalError, match="taken"):
            accounts.create_account(store, username="Boss", display_name="B", password=PASSWORD, role="therapist")

    def test_wrong_password_and_unknown_user_read_the_same(self, store, boss, fake_clock):
        lim = access.LoginLimiter(clock=fake_clock)
        with pytest.raises(access.AccessDenied) as wrong:
            accounts.authenticate(store, "boss", "not the password", "c1", lim)
        with pytest.raises(access.AccessDenied) as unknown:
            accounts.authenticate(store, "nobody", PASSWORD, "c2", lim)
        assert str(wrong.value) == str(unknown.value)

    def test_one_username_is_limited_from_any_client(self, store, boss, fake_clock):
        lim = access.LoginLimiter(clock=fake_clock)
        for n in range(5):
            with pytest.raises(access.AccessDenied):
                accounts.authenticate(store, "boss", "not the password", f"client-{n}", lim)
        with pytest.raises(access.LockedOut):
            accounts.authenticate(store, "boss", PASSWORD, "a-fresh-client", lim)

    def test_disabled_accounts_cannot_sign_in(self, store, boss, fake_clock):
        t = accounts.create_account(store, username="theo", display_name="Theo", password=PASSWORD, role="therapist")
        accounts.set_status(store, boss, t.id, "disabled")
        with pytest.raises(access.AccessDenied):
            accounts.authenticate(store, "theo", PASSWORD, "c", access.LoginLimiter(clock=fake_clock))

    def test_the_last_active_admin_cannot_be_disabled(self, store, boss):
        with pytest.raises(PortalError, match="last"):
            accounts.set_status(store, boss, boss.id, "disabled")
        second = accounts.create_account(store, username="boss2", display_name="B2", password=PASSWORD, role="admin")
        accounts.set_status(store, boss, second.id, "disabled")
        with pytest.raises(PortalError, match="last"):
            accounts.set_status(store, boss, boss.id, "disabled")

    def test_only_admins_manage_people(self, store, boss, fake_clock):
        t = accounts.create_account(store, username="theo", display_name="Theo", password=PASSWORD, role="therapist")
        with pytest.raises(accounts.NotAllowed):
            accounts.create_invite(store, t, "therapist", clock=fake_clock)
        with pytest.raises(accounts.NotAllowed):
            accounts.people(store, t)
        with pytest.raises(accounts.NotAllowed):
            accounts.set_status(store, t, boss.id, "disabled")


# ----------------------------------------------------------------------------- invitations and onboarding

class TestInvitations:
    def test_invite_then_onboard_a_therapist(self, store, boss, fake_clock):
        token, inv = accounts.create_invite(store, boss, "therapist", clock=fake_clock)
        assert len(token) >= 22 and inv.state == "invited"
        assert token not in "\n".join(str(tuple(r)) for r in store.conn.execute("SELECT * FROM invitations"))
        rows = accounts.people(store, boss)
        assert [r["status"] for r in rows].count("invited") == 1
        assert accounts.check_invite(store, token, clock=fake_clock).role == "therapist"
        theo = accounts.accept_invite(store, token, display_name="Theo Ray", username="theo", password=PASSWORD,
                                      password_again=PASSWORD, prefs={"larger_text": True}, clock=fake_clock)
        assert theo.role == "therapist" and theo.is_therapist and not theo.is_admin
        assert accounts.get_prefs(store, theo.id)["larger_text"] is True
        with pytest.raises(accounts.InviteInvalid) as used:
            accounts.check_invite(store, token, clock=fake_clock)
        assert used.value.reason == "used"
        assert [r["status"] for r in accounts.people(store, boss)].count("invited") == 0

    def test_expired_revoked_and_unknown(self, store, boss, fake_clock):
        old, _ = accounts.create_invite(store, boss, "therapist", clock=fake_clock)
        fake_clock.advance(7 * 24 * 3600 + 1)
        with pytest.raises(accounts.InviteInvalid) as expired:
            accounts.check_invite(store, old, clock=fake_clock)
        assert expired.value.reason == "expired" and "expired" in str(expired.value)
        fresh, inv = accounts.create_invite(store, boss, "therapist", clock=fake_clock)
        accounts.revoke_invite(store, boss, inv.id)
        with pytest.raises(accounts.InviteInvalid) as revoked:
            accounts.check_invite(store, fresh, clock=fake_clock)
        assert str(revoked.value) == str(expired.value)           # a revoked link reads like an expired one
        with pytest.raises(accounts.InviteInvalid):
            accounts.check_invite(store, "made-up", clock=fake_clock)

    def test_a_failed_onboarding_does_not_use_the_link(self, store, boss, fake_clock):
        token, _ = accounts.create_invite(store, boss, "therapist", clock=fake_clock)
        with pytest.raises(PortalError, match="match"):
            accounts.accept_invite(store, token, display_name="T", username="theo", password=PASSWORD,
                                   password_again=PASSWORD + "x", clock=fake_clock)
        with pytest.raises(PortalError, match="taken"):
            accounts.accept_invite(store, token, display_name="T", username="boss", password=PASSWORD,
                                   password_again=PASSWORD, clock=fake_clock)
        assert accounts.check_invite(store, token, clock=fake_clock).state == "invited"

    def test_patient_invite_joins_the_chosen_therapists_caseload(self, store, boss, fake_clock):
        theo = invite_and_accept(store, boss, "therapist", "theo", fake_clock)
        pat = invite_and_accept(store, boss, "patient", "sam17", fake_clock, therapist_id=theo.id, patient_id="P-017")
        assert pat.role == "patient" and pat.patient_id == "P-017"
        assert store.get_patient("P-017") is not None                  # the record is created with the invite
        assert accounts.visible_patient_ids(store, theo) == {"P-017"}
        row = next(r for r in accounts.people(store, boss) if r["username"] == "sam17")
        assert row["therapist"] == "theo" and row["patient_id"] == "P-017"

    def test_patient_invite_rules(self, store, boss, fake_clock):
        theo = invite_and_accept(store, boss, "therapist", "theo", fake_clock)
        with pytest.raises(PortalError, match="therapist"):
            accounts.create_invite(store, boss, "patient", patient_id="P-017", clock=fake_clock)
        with pytest.raises(PortalError, match="therapist"):
            accounts.create_invite(store, boss, "patient", therapist_id=boss.id, patient_id="P-017", clock=fake_clock)
        with pytest.raises(PTLogError):                                 # a name is not a pseudonymous ID
            accounts.create_invite(store, boss, "patient", therapist_id=theo.id, patient_id="Jane Doe", clock=fake_clock)
        invite_and_accept(store, boss, "patient", "sam17", fake_clock, therapist_id=theo.id, patient_id="P-017")
        with pytest.raises(PortalError, match="already"):
            accounts.create_invite(store, boss, "patient", therapist_id=theo.id, patient_id="P-017", clock=fake_clock)

    def test_an_admin_invite_can_also_be_a_therapist(self, store, boss, fake_clock):
        both = invite_and_accept(store, boss, "therapist", "lead", fake_clock, make_admin=True)
        assert both.is_admin and both.is_therapist

    def test_audit_has_events_but_no_names(self, store, boss, fake_clock):
        theo = invite_and_accept(store, boss, "therapist", "theo", fake_clock, name="Theodora Quill")
        accounts.set_status(store, boss, theo.id, "disabled")
        events = [e["event"] for e in accounts.history(store)]
        assert {"invite_created", "invite_used", "account_disabled"} <= set(events)
        assert "Theodora" not in str(accounts.history(store)) and "Pat Admin" not in str(accounts.history(store))


# ----------------------------------------------------------------------------- caseloads

class TestCaseloads:
    @pytest.fixture
    def two(self, store, boss, fake_clock):
        a = invite_and_accept(store, boss, "therapist", "anna", fake_clock)
        b = invite_and_accept(store, boss, "therapist", "ben", fake_clock)
        for pid, t in (("P-017", a), ("P-021", a), ("P-023", b)):
            store.add_patient(pid)
            accounts.assign(store, pid, t.id)
        return a, b

    def test_each_therapist_sees_only_their_own(self, store, two):
        a, b = two
        assert accounts.visible_patient_ids(store, a) == {"P-017", "P-021"}
        assert accounts.visible_patient_ids(store, b) == {"P-023"}
        assert accounts.can_see(store, a, "P-017") and not accounts.can_see(store, a, "P-023")

    def test_a_restricted_record_hides_the_others_everywhere(self, store, two):
        a, _ = two
        store.message_add("P-023", "patient", "hello from ben's patient", warned=False)
        store.entry_add("P-023", "checkin", {"pain": 3}, 3.0, "2026-03-23T09:00:00", "c-1", "before", None, False, False)
        store.media_add(Media(id="m1", patient_id="P-023", kind="clip", ext="mp4", container="mp4", codec="h264",
                              bytes=10, duration=1.0))
        accounts.restrict(store, a)
        assert {p.id for p in store.list_patients()} <= {"P-017", "P-021", "unassigned"}
        assert "P-023" not in {p.id for p in store.list_patients()}
        assert "P-023" not in {p.id for p in store.active_patients()}
        assert store.get_patient("P-023") is None
        assert "P-023" not in {r["patient_id"] for r in store.conversation_rows()}
        assert "P-023" not in store.messages_unread("patient")
        assert all(s.patient_id != "P-023" for s in store.list_sessions())
        assert "P-023" not in store.entries_all("checkin")
        assert all(m.patient_id != "P-023" for m in store.media_list())

    def test_an_admin_without_the_therapist_role_sees_no_patients(self, store, boss, two):
        assert accounts.visible_patient_ids(store, boss) == set()

    def test_patients_with_no_therapist_are_seen_by_admin_therapists_only(self, store, boss, two, fake_clock):
        a, _ = two
        lead = invite_and_accept(store, boss, "therapist", "lead", fake_clock, make_admin=True)
        store.add_patient("P-099")
        assert "P-099" in accounts.visible_patient_ids(store, lead)
        assert "P-099" not in accounts.visible_patient_ids(store, a)

    def test_reassign_moves_the_whole_history(self, store, boss, two):
        a, b = two
        accounts.reassign(store, boss, "P-017", b.id)
        assert "P-017" not in accounts.visible_patient_ids(store, a)
        assert "P-017" in accounts.visible_patient_ids(store, b)
        assert "patient_reassigned" in [e["event"] for e in accounts.history(store)]
        with pytest.raises(accounts.NotAllowed):
            accounts.reassign(store, a, "P-021", b.id)

    def test_a_new_patient_joins_the_therapist_who_added_it(self, store, two):
        a, _ = two
        accounts.add_patient(store, a, "P-030")
        assert "P-030" in accounts.visible_patient_ids(store, a)

    def test_deleting_a_patient_removes_its_account_and_caseload(self, store, boss, two, fake_clock):
        a, _ = two
        invite_and_accept(store, boss, "patient", "sam", fake_clock, therapist_id=a.id, patient_id="P-017")
        store.delete_patient("P-017")
        assert store.account_by_username("sam") is None
        assert store.conn.execute("SELECT COUNT(*) FROM caseloads WHERE patient_id = 'P-017'").fetchone()[0] == 0


# ----------------------------------------------------------------------------- preferences

class TestPreferences:
    def test_defaults_set_and_unknown_keys_dropped(self, store, boss):
        assert accounts.get_prefs(store, boss.id) == {"larger_text": False, "high_contrast": False, "reduced_motion": False}
        got = accounts.set_prefs(store, boss.id, {"high_contrast": True, "bogus": True, "reduced_motion": "yes"})
        assert got == {"larger_text": False, "high_contrast": True, "reduced_motion": False}

    def test_a_patient_keeps_settings_with_or_without_an_account(self, store, boss, fake_clock):
        store.add_patient("P-040")
        assert accounts.set_patient_prefs(store, "P-040", {"larger_text": True})["larger_text"] is True
        assert accounts.get_patient_prefs(store, "P-040")["larger_text"] is True
        theo = invite_and_accept(store, boss, "therapist", "theo", fake_clock)
        invite_and_accept(store, boss, "patient", "sam", fake_clock, therapist_id=theo.id, patient_id="P-041",
                          prefs={"reduced_motion": True})
        assert accounts.get_patient_prefs(store, "P-041")["reduced_motion"] is True
        assert store.diary_enabled("P-041") is True                      # the other settings keep their defaults

    def test_css_classes(self):
        assert accounts.css_classes({"larger_text": True, "high_contrast": True, "reduced_motion": False}) == \
            "a11y-large a11y-contrast"
        assert accounts.css_classes(None) == ""


# ----------------------------------------------------------------------------- the therapist door, per account

class TestStaffSignIn:
    def test_pass_and_sign_in_carry_the_account(self, store, boss, fake_clock):
        theo = invite_and_accept(store, boss, "therapist", "theo", fake_clock)
        lim = access.LoginLimiter(clock=fake_clock)
        who = admin.check_password(store, PASSWORD, "c", lim, username="theo")
        assert who.id == theo.id
        token = admin.redeem_pass(store, admin.issue_pass(store, who.id, clock=fake_clock), clock=fake_clock)
        assert admin.signed_in(store, token, clock=fake_clock).id == theo.id

    def test_disabling_ends_the_sign_in(self, store, boss, fake_clock):
        theo = invite_and_accept(store, boss, "therapist", "theo", fake_clock)
        token = admin.sign_in(store, PASSWORD, "c", access.LoginLimiter(clock=fake_clock), clock=fake_clock,
                              username="theo")
        accounts.set_status(store, boss, theo.id, "disabled")
        assert admin.signed_in(store, token, clock=fake_clock) is None

    def test_patients_cannot_use_the_therapist_door(self, store, boss, fake_clock):
        theo = invite_and_accept(store, boss, "therapist", "theo", fake_clock)
        invite_and_accept(store, boss, "patient", "sam", fake_clock, therapist_id=theo.id, patient_id="P-017")
        with pytest.raises(access.AccessDenied):
            admin.check_password(store, PASSWORD, "c", access.LoginLimiter(clock=fake_clock), username="sam")


# ----------------------------------------------------------------------------- patients sign in with a password

class TestPatientPasswordSignIn:
    def test_a_patient_account_opens_the_portal_without_a_code(self, store, boss, fake_clock):
        theo = invite_and_accept(store, boss, "therapist", "theo", fake_clock)
        invite_and_accept(store, boss, "patient", "sam", fake_clock, therapist_id=theo.id, patient_id="P-017")
        lim = access.LoginLimiter(clock=fake_clock)
        token = accounts.patient_sign_in(store, "sam", PASSWORD, "c", lim, clock=fake_clock)
        assert access.current_patient(store, token, clock=fake_clock) == "P-017"
        acct = store.account_by_username("sam")
        accounts.set_status(store, boss, acct.id, "disabled")
        assert access.current_patient(store, token, clock=fake_clock) is None

    def test_staff_cannot_use_the_patient_door(self, store, boss, fake_clock):
        with pytest.raises(access.AccessDenied):
            accounts.patient_sign_in(store, "boss", PASSWORD, "c", access.LoginLimiter(clock=fake_clock), clock=fake_clock)
