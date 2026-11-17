"""Feature 021 N4: People → History. Staff sign-in events record their account from v19 (an unknown username says so
and is never stored); History merges them with account changes, newest first, with names, a kind filter and 200 rows
a page; it is admin-only and shows no clinical field. Spec 021 User Story 4, scenarios 1 to 6, FR-013 and FR-014."""

from datetime import datetime, timedelta

import pytest

from src.clinic import people
from src.portal import accounts
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, PASSWORD, client, seed, sign_in
from tests.test_clinic_records import Clock


@pytest.fixture
def world(tmp_db):
    clock = Clock(datetime(2026, 3, 2, 9, 0))
    made = seed(tmp_db, clock)
    with client(tmp_db, clock) as c:
        yield c, tmp_db, clock, made


def _rows(db, clock, actor_name="sam", kind="all", page=0):
    with SessionStore(db, clock=clock).open() as s:
        return people.history(s, s.account_by_username(actor_name), kind, page)


def test_sign_ins_record_the_account_and_never_an_unknown_name(world):
    c, db, clock, made = world
    sign_in(c, "rivera")
    clock.set(datetime(2026, 3, 2, 9, 1))
    assert c.post("/therapist/api/logout", json={}, headers=H).status_code == 200
    clock.set(datetime(2026, 3, 2, 9, 2))
    c.post("/therapist/api/login", json={"username": "rivera", "password": "wrong"}, headers=H)
    c.post("/therapist/api/login", json={"username": "ghost-typo-hunter2", "password": "x"}, headers=H)
    with SessionStore(db, clock=clock).open() as s:
        events = s.admin_audit_list()
        rivera = made["rivera"].id
        assert [(e["event"], e["account_id"]) for e in events[:3]] == [
            ("login_failed", s.UNKNOWN_USERNAME), ("login_failed", rivera), ("logout", rivera)]
        flat = repr(s.conn.execute("SELECT * FROM admin_audit").fetchall()) + repr(
            [tuple(r) for r in s.conn.execute("SELECT * FROM admin_audit")])
        assert "ghost-typo-hunter2" not in flat
    rows = _rows(db, clock)["rows"]
    whos = [(r["what"], r["who"]) for r in rows if r["kind"] == "Sign-in"]
    assert ("Sign-in failed", "unknown username") in whos and ("Sign-in failed", "Rivera") in whos
    assert ("Signed out", "Rivera") in whos and ("Signed in", "Rivera") in whos


def test_account_changes_show_names_and_patient_codes(world):
    c, db, clock, made = world
    with SessionStore(db, clock=clock).open() as s:
        sam = s.account_by_username("sam")
        clock.set(datetime(2026, 3, 2, 10, 0))
        people.reassign(s, sam, "P-001", made["rivera"].id)
        clock.set(datetime(2026, 3, 2, 10, 5))
        people.set_status(s, sam, made["rivera"].id, "disabled")
    rows = _rows(db, clock, kind="accounts")["rows"]
    assert rows[0]["what"] == "Account disabled" and rows[0]["who"] == "Sam" and rows[0]["subject"] == "Rivera (therapist)"
    assert rows[1]["what"] == "Patient moved to another therapist" and rows[1]["subject"] == "P-001 to Rivera"
    assert all(r["kind"] == "Account" for r in rows)
    assert rows[0]["when"] == "2026-03-02 10:05"


def test_events_from_before_v19_say_the_account_was_not_recorded(world):
    c, db, clock, _ = world
    with SessionStore(db, clock=clock).open() as s:
        s.conn.execute("INSERT INTO admin_audit (at, event, client) VALUES ('2026-01-01T08:00:00', 'login_ok', NULL)")
        s.conn.commit()
    rows = _rows(db, clock, kind="signins")["rows"]
    assert rows[-1]["who"] == "account not recorded" and all(r["kind"] == "Sign-in" for r in rows)


def test_two_hundred_rows_a_page_then_show_older(world):
    c, db, clock, _ = world
    with SessionStore(db, clock=clock).open() as s:
        for i in range(250):
            clock.set(datetime(2026, 3, 3, 9, 0) + timedelta(minutes=i))
            s.admin_audit_add("login_ok", None, s.account_by_username("rivera").id)
    first = _rows(db, clock)
    assert len(first["rows"]) == 200 and first["older"] and first["rows"][0]["when"] == "2026-03-03 13:09"
    second = _rows(db, clock, page=1)
    assert second["rows"][0]["at"] < first["rows"][-1]["at"] or second["rows"][0]["at"] == first["rows"][-1]["at"]
    assert not second["older"]


def test_the_page_is_admin_only_and_carries_no_clinical_fields(world):
    c, db, clock, _ = world
    from tests.test_clinic_static import _checked
    sign_in(c, "rivera")
    assert c.get("/therapist/people/history").status_code == 403
    sign_in(c, "sam")
    r = c.get("/therapist/people/history?kind=signins")
    assert r.status_code == 200
    _checked(r.text, "history")
    assert "<h1>History</h1>" in r.text and 'value="signins" selected' in r.text
    assert 'href="/therapist/people/history"' in c.get("/therapist/people").text
    for clinical in ("Knee", "session", "message", "pain"):
        assert clinical not in r.text.split("<main")[1], clinical
