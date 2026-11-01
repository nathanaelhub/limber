"""Feature 017 US4 — appointments stored in UTC, shown in the clinic's time zone, with a reschedule request."""

import pytest

from src.portal import plans
from src.ptlog.models import PortalError
from src.ptlog.store import SessionStore


@pytest.fixture
def store(tmp_db, fake_clock):            # the clock reads 2026-03-23T09:15:00, naive local
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-018")
        yield s


def test_the_clinic_time_is_what_everyone_sees(store):
    """Scenario 1: 9:00 at the clinic is 9:00 on the patient's screen, whatever the device's zone, because
    the server sends the clinic's wall-clock time and never asks the device."""
    plans.set_clinic_zone(store, "America/Chicago")
    a = plans.schedule(store, "P-017", "2026-11-04T09:00", 45, "Re-check range of motion")
    assert a.starts_at == "2026-11-04T15:00:00+00:00"                         # CST is UTC-6 in November
    summer = plans.schedule(store, "P-017", "2026-07-01T09:00", 30)
    assert summer.starts_at == "2026-07-01T14:00:00+00:00"                    # CDT is UTC-5
    view = plans.appointment_json(store, a)
    assert (view["date"], view["time"], view["time_zone"]) == ("2026-11-04", "09:00", "America/Chicago")
    plans.set_clinic_zone(store, "Europe/London")                             # the clinic moves; the instant does not
    assert plans.appointment_json(store, a)["time"] == "15:00"


def test_the_default_zone_and_a_bad_one(store):
    assert str(plans.clinic_zone(store)) == plans.DEFAULT_TIME_ZONE
    with pytest.raises(PortalError, match="Unknown time zone"):
        plans.set_clinic_zone(store, "Mars/Olympus")


def test_inputs_are_checked(store):
    with pytest.raises(PortalError, match="5 to 480"):
        plans.schedule(store, "P-017", "2026-11-04T09:00", 2)
    with pytest.raises(PortalError, match="YYYY-MM-DD"):
        plans.schedule(store, "P-017", "next tuesday", 45)
    with pytest.raises(PortalError, match="200"):
        plans.schedule(store, "P-017", "2026-11-04T09:00", 45, "x" * 201)


def test_a_reschedule_request_is_flagged_and_answered_by_a_new_time(store):
    """Scenario 2."""
    a = plans.schedule(store, "P-017", "2026-11-04T09:00", 45)
    asked = plans.request_reschedule(store, "P-017", a.id, "Can we do the afternoon?")
    assert asked.reschedule_requested and asked.request_note == "Can we do the afternoon?"
    assert [r.id for r in plans.reschedule_requests(store)] == [a.id]
    moved = plans.move(store, a.id, "2026-11-04T14:00")
    assert not moved.reschedule_requested and plans.appointment_json(store, moved)["time"] == "14:00"
    assert plans.reschedule_requests(store) == []


def test_the_therapist_can_decline_with_a_note(store):
    a = plans.schedule(store, "P-017", "2026-11-04T09:00", 45)
    plans.request_reschedule(store, "P-017", a.id, "Later please")
    declined = plans.decline_request(store, a.id, "That's the only slot this week")
    assert not declined.reschedule_requested and declined.response_note == "That's the only slot this week"
    assert declined.starts_at == a.starts_at


def test_a_cancelled_appointment_stays_visible(store):
    """Scenario 3."""
    a = plans.schedule(store, "P-017", "2026-11-04T09:00", 45)
    plans.cancel(store, a.id)
    (view,) = plans.appointments_view(store, "P-017")
    assert view["status"] == "cancelled" and view["state"] == "cancelled"
    with pytest.raises(PortalError, match="cancelled"):
        plans.request_reschedule(store, "P-017", a.id, "")


def test_a_past_unmarked_appointment_is_past_not_missed(store):
    old = plans.schedule(store, "P-017", "2026-03-01T09:00", 45)
    assert plans.appointment_json(store, old)["state"] == "past"
    assert plans.appointment_json(store, plans.schedule(store, "P-017", "2026-12-01T09:00", 45))["state"] == "upcoming"
    with pytest.raises(PortalError, match="already happened"):
        plans.request_reschedule(store, "P-017", old.id, "")


def test_a_patient_cannot_touch_another_patients_appointment(store):
    a = plans.schedule(store, "P-018", "2026-11-04T09:00", 45)
    with pytest.raises(PortalError, match="No such appointment"):
        plans.request_reschedule(store, "P-017", a.id, "")
    assert plans.appointments_view(store, "P-017") == []


def test_appointments_belong_to_a_plan(store):
    shoulder = plans.open_plan(store, "P-017", "Left shoulder")
    knee = store.plans("P-017")[0]
    a = plans.schedule(store, "P-017", "2026-11-04T09:00", 45, plan_id=knee.id)
    b = plans.schedule(store, "P-017", "2026-11-05T09:00", 45)
    assert (a.plan_id, b.plan_id) == (knee.id, shoulder.id)
    assert [x["id"] for x in plans.appointments_view(store, "P-017", shoulder.id)] == [b.id]
