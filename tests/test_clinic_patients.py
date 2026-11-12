"""Feature 019 slice 3a (T016): the Patients page's rules, tested without a server."""

from datetime import date, datetime

import pytest

from src.clinic import patients
from src.portal import accounts, messages, plans
from src.ptlog.store import SessionStore
from tests.clinic_helpers import seed


@pytest.fixture
def world(tmp_db, fake_clock):
    made = seed(tmp_db, fake_clock)
    store = SessionStore(tmp_db, clock=fake_clock).open()
    accounts.restrict(store, made["therapist"])
    yield store, made, fake_clock
    store.close()


def test_the_header_names_the_open_plan_and_the_others(world):
    store, _, clock = world
    first = store.plans("P-001")[0]
    today = clock.peek().date()
    assert patients.header(store, "P-001", today) == f"{first.title} · started today"
    plans.open_plan(store, "P-001", "Left ankle")
    later = date.fromordinal(today.toordinal() + 20)
    assert patients.header(store, "P-001", later) == f"{first.title} · started 2 weeks ago · Also: Left ankle"
    plans.complete(store, first.id)
    plans.complete(store, store.plans("P-001")[1].id)
    assert patients.header(store, "P-001", today) == "No open plan of care."


def checkin(store, pid, pain, at, n):
    store.entry_add(pid, "checkin", {"pain": pain}, float(pain), at, f"c-{n}", "before", None, False, False)


def test_pain_and_its_change_from_a_week_before(world):
    store, _, _ = world
    assert patients.pain(store, "P-001") is None
    checkin(store, "P-001", 3, "2026-03-10T09:00:00", 1)
    assert patients.pain(store, "P-001")["words"] is None                 # nothing a week before to compare
    checkin(store, "P-001", 6, "2026-03-20T09:00:00", 2)
    found = patients.pain(store, "P-001")
    assert found["score"] == 6 and found["change"] == 3 and found["words"] == "Up 3 from last week"


def test_list_rows_put_attention_first_and_discharged_last(world):
    store, _, clock = world
    for pid in ("P-005", "P-006", "P-007"):
        accounts.add_patient(store, store.account_by_username("therapist"), pid)
    messages.set_enabled(store, "P-006", True)
    messages.send(store, "P-006", "patient", "I have chest pain", plan_id=store.plans("P-006")[0].id)
    store.discharge("P-007")
    rows = patients.rows(store, clock.peek())
    assert [r.patient_id for r in rows][:1] == ["P-006"] and rows[0].warn and rows[0].status == "! Urgent message"
    assert rows[-1].patient_id == "P-007" and rows[-1].discharged
    assert next(r for r in rows if r.patient_id == "P-005").status == "New · No records yet"
    assert "P-002" not in [r.patient_id for r in rows]                  # another therapist's patient
    assert all(not r.patient_id.startswith("unassigned") for r in rows)


def test_plan_actions_follow_the_plan_status(world):
    store, _, _ = world
    plan = store.plans("P-001")[0]
    assert patients.plan_actions(plan) == ["edit", "complete"]
    plans.complete(store, plan.id)
    assert patients.plan_actions(store.plan_get(plan.id)) == ["edit", "reopen", "archive"]
    plans.archive(store, plan.id)
    assert patients.plan_actions(store.plan_get(plan.id)) == []


class Status:
    def __init__(self, state, expires_at=None, last_used_at=None):
        self.state, self.expires_at, self.last_used_at = state, expires_at, last_used_at


def test_home_access_line():
    assert patients.access_line(Status("none")) == "No access code yet"
    assert patients.access_line(Status("active", "2026-12-01T00:00:00", "2026-11-12T08:40:00")) == \
        "Access code in use until 2026-12-01 · Last used 2026-11-12 08:40"
    assert patients.access_line(Status("revoked")) == "The access code was revoked"


def test_medication_lines():
    assert patients.medication_lines("ibuprofen 400 mg\n\n paracetamol \n") == ["ibuprofen 400 mg", " paracetamol "]
    assert patients.medication_lines(None) == []


def test_registering_on_a_caseload_limited_store(world):
    """A store limited to a caseload (every clinic request) could not register: the record read the new patient
    back through the caseload check before it was on the caseload."""
    store, made, _ = world
    patient = accounts.add_patient(store, made["therapist"], "P-031", label="Ankle")
    assert patient.id == "P-031" and store.get_patient("P-031") is not None
    assert "P-031" in accounts.visible_patient_ids(store, made["therapist"])
    from src.ptlog.models import PTLogError
    with pytest.raises(PTLogError):
        accounts.add_patient(store, made["therapist"], "P-002")          # taken, by another caseload
    assert store.get_patient("P-002") is None                           # still not visible here
