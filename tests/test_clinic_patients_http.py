"""Feature 019 slice 3a (T017, T018): the Patients page through the clinic app. Each action the Streamlit page had
works here with the same rules; an archived plan takes nothing new (409); another caseload is not found."""

import pytest

from src.portal import plans
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in


@pytest.fixture
def world(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        yield c, tmp_db, fake_clock


def post(c, path, body=None):
    return c.post("/therapist/api/patients" + path, json=body or {}, headers=H)


def store(db, clock):
    return SessionStore(db, clock=clock).open()


def test_the_list_and_the_tabs(world):
    c, _, _ = world
    page = c.get("/therapist/patients").text
    assert 'href="/therapist/patients/P-001"' in page and "P-002" not in page and "Pick a patient" in page
    for tab in ("", "/exercises", "/details"):
        r = c.get("/therapist/patients/P-001" + tab)
        assert r.status_code == 200, tab
        assert 'href="/therapist/inbox/P-001">Messages' in r.text
    from tests.test_clinic_static import _checked
    for tab in ("", "/exercises", "/details"):
        _checked(c.get("/therapist/patients/P-001" + tab).text, tab)


def test_register_a_patient(world):
    c, db, clock = world
    assert "Register a patient" in c.get("/therapist/patients/new").text
    r = post(c, "", {"patient_id": "P-031", "label": "Ankle", "notes": ""})
    assert r.status_code == 201 and r.json() == {"redirect": "/therapist/patients/P-031"}
    assert c.get("/therapist/patients/P-031").status_code == 200
    assert post(c, "", {"patient_id": "P-031"}).status_code == 400            # taken
    assert post(c, "", {"patient_id": "no spaces allowed"}).status_code == 400


def test_label_notes_and_delete(world):
    c, db, clock = world
    assert post(c, "/P-001/details", {"label": "Knee", "notes": "Prefers mornings"}).status_code == 200
    assert "Prefers mornings" in c.get("/therapist/patients/P-001/details").text
    assert post(c, "/P-001/delete", {"confirm": "P-01"}).status_code == 400
    assert post(c, "/P-001/delete", {"confirm": "P-001"}).json() == {"redirect": "/therapist/patients"}
    with store(db, clock) as s:
        assert s.get_patient("P-001") is None


def test_plans_and_the_archived_rule(world):
    c, db, clock = world
    assert post(c, "/P-001/plans", {"title": "Left ankle", "diagnosis": "Sprain", "diagnosis_visible": True}).status_code == 200
    with store(db, clock) as s:
        ankle = [p for p in s.plans("P-001") if p.title == "Left ankle"][0]
    assert ankle.diagnosis_visible
    assert post(c, f"/P-001/plans/{ankle.id}/archive").status_code == 409     # complete it first
    assert post(c, f"/P-001/plans/{ankle.id}/complete").status_code == 200
    assert post(c, f"/P-001/plans/{ankle.id}/archive").status_code == 200
    assert post(c, f"/P-001/plans/{ankle.id}/edit", {"title": "x"}).status_code == 409
    r = post(c, "/P-001/visits", {"date": "2026-03-30", "time": "09:00", "minutes": 45, "plan_id": ankle.id})
    assert r.status_code == 409 and r.json()["archived"] is True              # 017: nothing new in an archived plan


def test_visits(world):
    c, db, clock = world
    plan = None
    with store(db, clock) as s:
        plan = s.plans("P-001")[0].id
    assert post(c, "/P-001/visits", {"date": "2026-03-30", "time": "09:00", "minutes": 45, "note": "Re-check",
                                     "plan_id": plan}).status_code == 200
    with store(db, clock) as s:
        a = s.appointments("P-001")[0]
        plans.request_reschedule(s, "P-001", a.id, "Afternoons")
    page = c.get("/therapist/patients/P-001").text
    assert "Mon 30 Mar, 09:00" in page and "asked to reschedule: “Afternoons”" in page
    assert post(c, f"/P-001/visits/{a.id}/move", {"date": "2026-03-31", "time": "14:30"}).status_code == 200
    assert post(c, f"/P-001/visits/{a.id}/cancel").status_code == 200
    with store(db, clock) as s:
        a = s.appointment_get(a.id)
        assert a.status == "cancelled" and not a.reschedule_requested


def test_program_and_questionnaires(world, monkeypatch):
    c, db, clock = world
    from src.ptlog import programs
    catalog = programs.list_programs()
    if catalog:
        assert post(c, "/P-001/program", {"program": catalog[0].id, "per_week": 3, "start": "2026-03-23",
                                          "end": ""}).status_code == 200
    keys = list(programs.load_catalog().exercises)[:2]
    assert post(c, "/P-001/program", {"program": "custom", "keys": keys, "per_week": 2, "start": "2026-03-24"}).status_code == 200
    assert post(c, "/P-001/program", {"program": "custom", "keys": ["not_an_exercise"], "per_week": 2}).status_code == 400
    page = c.get("/therapist/patients/P-001/exercises").text
    assert "Custom" in page
    from src.ptlog import instruments
    installed = instruments.load().listed()
    if installed:
        assert post(c, "/P-001/questionnaires", {"instrument": installed[0].key, "interval": "weekly"}).status_code == 200
        assert post(c, "/P-001/questionnaires", {"instrument": installed[0].key, "interval": "hourly"}).status_code == 400
        with store(db, clock) as s:
            assignment = s.assignments("P-001")[0]
        assert post(c, f"/P-001/questionnaires/{assignment.id}/end").status_code == 200


def test_logging_and_home_access(world):
    c, db, clock = world
    r = post(c, "/P-001/logging", {"diary": True, "medications": "ibuprofen 400 mg\nCall 615 555 0142"})
    assert r.status_code == 200 and "identifying" in r.json()["notice"]
    with store(db, clock) as s:
        assert s.diary_enabled("P-001") and s.medication_list("P-001")[0] == "ibuprofen 400 mg"
    code = post(c, "/P-001/access/issue").json()
    assert len(code["show"]) >= 12 and "only once" in code["note"]
    page = c.get("/therapist/patients/P-001/details").text
    assert code["show"] not in page and "Access code in use" in page            # shown once, never again
    assert post(c, "/P-001/access/revoke").status_code == 200
    assert "revoked" in c.get("/therapist/patients/P-001/details").text


def test_discharge_and_reactivate(world):
    c, db, clock = world
    assert post(c, "/P-001/discharge", {"on": "2026-03-23", "reason": "Goals met"}).status_code == 200
    assert "Discharged" in c.get("/therapist/patients/P-001/details").text
    assert "Show discharged (1)" in c.get("/therapist/patients").text
    assert post(c, "/P-001/reactivate").status_code == 200


def test_the_builtin_patient_has_no_page(world):
    c, _, _ = world
    assert c.get("/therapist/patients/unassigned").status_code == 404
    assert post(c, "/unassigned/delete", {"confirm": "unassigned"}).status_code == 404


def test_another_caseload_is_not_found(world):
    c, db, clock = world
    c.post("/therapist/api/logout", json={}, headers=H)
    sign_in(c, "rivera")
    assert c.get("/therapist/patients/P-001").status_code == 404
    assert post(c, "/P-001/delete", {"confirm": "P-001"}).status_code == 404
    with store(db, clock) as s:
        their_plan = s.plans("P-001")[0].id
    assert post(c, f"/P-002/plans/{their_plan}/complete").status_code == 404   # rivera's patient, not their plan
    with store(db, clock) as s:
        assert s.get_patient("P-001") is not None and s.plan_get(their_plan).status == "active"
