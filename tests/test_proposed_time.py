"""Feature 021 N2: the patient proposes a time when asking to move a visit. The time must be ahead, within 90 days
and on a 5-minute step; Accept moves the visit there with its length kept and says so to the patient; a time that
has passed is not offered; an overlap asks first; a request without a time works as before; a second request replaces
the first. Spec 021 User Story 2, scenarios 1 to 7, and FR-006 to FR-009."""

from datetime import datetime

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app as portal_app
from src.clinic import inbox as clinic_inbox
from src.portal import access, plans
from src.ptlog.models import PortalError
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, KEY, ORIGIN, client, seed, sign_in
from tests.test_clinic_records import Clock


@pytest.fixture
def world(tmp_db):
    clock = Clock(datetime(2026, 3, 2, 9, 0))
    seed(tmp_db, clock)
    with SessionStore(tmp_db, clock=clock).open() as s:
        plans.set_clinic_zone(s, "America/Chicago")
        visit = plans.schedule(s, "P-001", "2026-03-10T09:00", 45, "Re-check")
        other = plans.schedule(s, "P-002", "2026-03-12T10:00", 30)          # rivera's patient
        code = access.issue_code(s, KEY, "P-001")[0]
    return tmp_db, clock, visit.id, other.id, code


def _store(db, clock):
    return SessionStore(db, clock=clock).open()


# ---- the rules ---------------------------------------------------------------------------------------------------

def test_a_request_stores_the_time_and_the_note(world):
    db, clock, vid, *_ = world
    with _store(db, clock) as s:
        a = plans.request_reschedule(s, "P-001", vid, "Afternoons please", "2026-03-11T14:30")
        view = plans.appointment_json(s, a)
        assert a.reschedule_requested and a.request_note == "Afternoons please"
        assert datetime.fromisoformat(a.requested_starts_at).utcoffset().total_seconds() == 0     # stored in UTC
        assert view["requested_local"] == "2026-03-11T14:30" and view["requested_label"] == "Wed 11 Mar, 14:30"
        assert view["requested_passed"] is False


@pytest.mark.parametrize("bad, words", [("2026-03-01T09:00", "in the future"), ("2026-07-01T09:00", "90 days"),
                                        ("2026-03-11T14:32", "5-minute step"), ("tomorrow", "day and a time")])
def test_a_bad_time_is_refused_plainly(world, bad, words):
    db, clock, vid, *_ = world
    with _store(db, clock) as s:
        with pytest.raises(PortalError) as err:
            plans.request_reschedule(s, "P-001", vid, "", bad)
        assert words in str(err.value)
        assert not s.appointment_get(vid).reschedule_requested


def test_without_a_time_it_works_as_before(world):
    db, clock, vid, *_ = world
    with _store(db, clock) as s:
        a = plans.request_reschedule(s, "P-001", vid, "Any afternoon")
        assert a.reschedule_requested and a.requested_starts_at is None
        assert plans.appointment_json(s, a)["requested_label"] is None
        with pytest.raises(PortalError):
            plans.accept_request(s, vid)


def test_accept_moves_the_visit_keeps_its_length_and_tells_the_patient(world):
    db, clock, vid, *_ = world
    with _store(db, clock) as s:
        plans.request_reschedule(s, "P-001", vid, "", "2026-03-11T14:30")
        a = plans.accept_request(s, vid, "See you then.")
        view = plans.appointment_json(s, a)
        assert view["starts_local"] == "2026-03-11T14:30" and a.minutes == 45
        assert not a.reschedule_requested and a.requested_starts_at is None
        assert a.response_note == "Moved at your request. See you then."


def test_a_second_request_replaces_the_first(world):
    db, clock, vid, *_ = world
    with _store(db, clock) as s:
        plans.request_reschedule(s, "P-001", vid, "first", "2026-03-11T14:30")
        a = plans.request_reschedule(s, "P-001", vid, "second", "2026-03-13T08:00")
        assert a.request_note == "second" and plans.appointment_json(s, a)["requested_local"] == "2026-03-13T08:00"


def test_offer_another_time_or_keep_clears_the_proposed_time(world):
    db, clock, vid, *_ = world
    with _store(db, clock) as s:
        plans.request_reschedule(s, "P-001", vid, "", "2026-03-11T14:30")
        assert plans.decline_request(s, vid, "Keep it, please").requested_starts_at is None
        plans.request_reschedule(s, "P-001", vid, "", "2026-03-11T14:30")
        assert plans.move(s, vid, "2026-03-12T08:00").requested_starts_at is None


def test_a_passed_time_is_not_accepted(world):
    db, clock, vid, *_ = world
    with _store(db, clock) as s:
        plans.request_reschedule(s, "P-001", vid, "", "2026-03-03T09:00")
    clock.set(datetime(2026, 3, 4, 9, 0))
    with _store(db, clock) as s:
        a = s.appointment_get(vid)
        assert plans.appointment_json(s, a)["requested_passed"] is True
        with pytest.raises(PortalError) as err:
            plans.accept_request(s, vid)
        assert "has passed" in str(err.value)


def test_overlaps_are_found_across_the_visible_caseload(world):
    db, clock, vid, other, _ = world
    with _store(db, clock) as s:
        a = plans.request_reschedule(s, "P-001", vid, "", "2026-03-12T09:30")      # 09:30-10:15 meets 10:00
        found = plans.overlaps(s, a)
        assert [o.id for o in found] == [other]
        assert plans.overlap_warning(s, found) == "This overlaps P-002's visit at 10:00."
        a = plans.request_reschedule(s, "P-001", vid, "", "2026-03-12T09:15")      # ends 10:00 exactly
        assert plans.overlaps(s, a) == []


# ---- through the portal ------------------------------------------------------------------------------------------

def test_the_portal_takes_a_day_and_a_time(world):
    db, clock, vid, _, code = world
    app = portal_app(db_path=db, key=KEY, allowed_origins=[ORIGIN], clock=clock)
    with TestClient(app, base_url=ORIGIN) as c:
        assert c.post("/api/login", json={"code": code}, headers=H).status_code == 200
        r = c.post(f"/api/appointments/{vid}/reschedule", json={"note": "x", "date": "2026-03-11", "time": "14:30"},
                   headers=H)
        assert r.status_code == 200 and r.json()["requested_label"] == "Wed 11 Mar, 14:30"
        r = c.post(f"/api/appointments/{vid}/reschedule", json={"date": "2026-03-11", "time": ""}, headers=H)
        assert r.status_code == 400 and "both" in r.json()["error"]
        r = c.post(f"/api/appointments/{vid}/reschedule", json={"date": "2026-01-11", "time": "14:30"}, headers=H)
        assert r.status_code == 400 and "future" in r.json()["error"]


# ---- through the clinic ------------------------------------------------------------------------------------------

@pytest.fixture
def clinic(world):
    db, clock, vid, other, _ = world
    with _store(db, clock) as s:
        plans.request_reschedule(s, "P-001", vid, "Afternoons please", "2026-03-11T14:30")
    with client(db, clock) as c:
        sign_in(c)
        yield c, db, clock, vid


def test_needs_you_names_the_proposed_time(clinic):
    c, db, clock, vid = clinic
    with _store(db, clock) as s:
        s.restrict(None)
        (item,) = [i for i in clinic_inbox.needs_you(s) if i.kind == "reschedule"]
        assert "to Wed 11 Mar, 14:30" in item.line and item.visit_id == vid and item.proposed == "Wed 11 Mar, 14:30"


def test_inbox_schedule_dashboard_and_overview_offer_accept(clinic):
    c, *_ = clinic
    from tests.test_clinic_static import _checked
    inbox = c.get("/therapist/inbox/P-001").text
    assert "Asks for Wed 11 Mar, 14:30" in inbox and 'value="accept" checked' in inbox
    schedule = c.get("/therapist/schedule").text
    _checked(schedule, "schedule")
    assert "Accept Wed 11 Mar, 14:30" in schedule and "Offer another time" in schedule
    dashboard = c.get("/therapist").text
    _checked(dashboard, "dashboard")
    assert "Accept Wed 11 Mar, 14:30" in dashboard and "forms.js" in dashboard
    assert "Accept Wed 11 Mar, 14:30" in c.get("/therapist/patients/P-001").text


def test_accept_from_the_inbox_and_the_patient_sees_it(clinic):
    c, db, clock, vid = clinic
    r = c.post(f"/therapist/api/inbox/P-001/visits/{vid}/answer", json={"answer": "accept", "note": ""}, headers=H)
    assert r.status_code == 200, r.text
    with _store(db, clock) as s:
        view = plans.appointment_json(s, s.appointment_get(vid))
        assert view["starts_local"] == "2026-03-11T14:30" and view["response_note"] == "Moved at your request."


def test_an_overlap_asks_first_then_accepts(clinic):
    c, db, clock, vid = clinic
    with _store(db, clock) as s:
        plans.schedule(s, "P-001", "2026-03-11T14:00", 60, "Another visit")
    r = c.post(f"/therapist/api/patients/P-001/visits/{vid}/accept", json={"confirm": ""}, headers=H)
    assert r.status_code == 409 and r.json()["needs_confirm"] and "P-001's visit at 14:00" in r.json()["error"]
    with _store(db, clock) as s:
        assert s.appointment_get(vid).reschedule_requested
    r = c.post(f"/therapist/api/patients/P-001/visits/{vid}/accept", json={"confirm": "yes"}, headers=H)
    assert r.status_code == 200


def test_a_passed_time_shows_no_accept_but_keep_still_works(clinic):
    c, db, clock, vid = clinic
    clock.set(datetime(2026, 3, 12, 16, 0))               # a day after, in any machine's time zone
    sign_in(c)                                            # the staff sign-in has lapsed over nine days
    inbox = c.get("/therapist/inbox/P-001").text
    assert "The time they asked for has passed" in inbox and 'value="accept"' not in inbox
    assert "Accept Wed" not in c.get("/therapist/schedule").text
    r = c.post(f"/therapist/api/patients/P-001/visits/{vid}/accept", json={"confirm": "yes"}, headers=H)
    assert r.status_code == 400 and "has passed" in r.json()["error"]
    assert c.post(f"/therapist/api/patients/P-001/visits/{vid}/decline", json={"note": "Keep it"},
                  headers=H).status_code == 200


def test_another_caseload_cannot_accept(clinic):
    c, db, clock, _ = clinic
    with _store(db, clock) as s:
        theirs = plans.schedule(s, "P-002", "2026-03-15T09:00", 30)
        plans.request_reschedule(s, "P-002", theirs.id, "", "2026-03-16T09:00")
    assert c.post(f"/therapist/api/patients/P-002/visits/{theirs.id}/accept", json={}, headers=H).status_code == 404
