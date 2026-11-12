"""Feature 019 slice 4 (T021 to T023): Schedule and People in the clinic app.

Schedule keeps the current page's order (requests first, then upcoming, then past and cancelled). People is for
admins only; it invites, revokes, disables and re-enables (never the last admin, never yourself here) and moves
patients between therapists, and it shows no clinical field."""

import pytest

from src.clinic import people, schedule
from src.portal import accounts, plans
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in


@pytest.fixture
def made(tmp_db, fake_clock):
    return seed(tmp_db, fake_clock)


def _visits(db, clock):
    with SessionStore(db, clock=clock).open() as s:
        plan = s.plans("P-001")[0].id
        late = plans.schedule(s, "P-001", "2026-04-02T09:00", 45, plan_id=plan)
        soon = plans.schedule(s, "P-001", "2026-03-30T10:00", 30, "Re-check", plan_id=plan)
        gone = plans.schedule(s, "P-001", "2026-03-31T10:00", 30, plan_id=plan)
        past = plans.schedule(s, "P-001", "2026-03-20T10:00", 30, plan_id=plan)
        plans.cancel(s, gone.id)
        plans.request_reschedule(s, "P-001", late.id, "Afternoons")
        plans.schedule(s, "P-002", "2026-03-30T08:00", 30, plan_id=s.plans("P-002")[0].id)   # rivera's
        return late, soon, gone, past


def test_the_schedule_order(tmp_db, fake_clock, made):
    late, soon, gone, past = _visits(tmp_db, fake_clock)
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        accounts.restrict(s, made["therapist"])
        groups = schedule.visits(s)
    assert [v["id"] for v in groups["requests"]] == [late.id]
    assert [v["id"] for v in groups["upcoming"]] == [soon.id, late.id]
    assert [v["id"] for v in groups["rest"]] == [gone.id, past.id]         # newest first
    assert all(v["patient_id"] == "P-001" for g in groups.values() for v in g)


def test_the_schedule_page(tmp_db, fake_clock, made):
    late, _, _, _ = _visits(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        page = c.get("/therapist/schedule").text
        assert page.index("Reschedule requests") < page.index("Upcoming") < page.index("Past and cancelled (2)")
        assert "“Afternoons”" in page and f'data-api="/api/patients/P-001/visits/{late.id}/move"' in page
        assert "08:00" not in page                                           # rivera's visit
        from tests.test_clinic_static import _checked
        _checked(page, "schedule")


def test_people_is_for_admins_only(tmp_db, fake_clock, made):
    with client(tmp_db, fake_clock) as c:
        sign_in(c, "rivera")
        assert c.get("/therapist/people").status_code == 403
        assert c.post("/therapist/api/people/invite", json={"role": "therapist"}, headers=H).status_code == 403
        c.post("/therapist/api/logout", json={}, headers=H)
        sign_in(c, "sam")                                                     # admin, not a therapist
        page = c.get("/therapist/people").text
        assert "Rivera" in page and "Therapist and admin" in page
        assert "P-001 (now Therapist)" in page and "P-002 (now Rivera)" in page   # codes, for moving them


def test_invite_revoke_disable_and_reassign(tmp_db, fake_clock, made):
    with client(tmp_db, fake_clock) as c:
        sign_in(c, "sam")
        r = c.post("/therapist/api/people/invite", json={"role": "patient", "therapist_id": str(made["rivera"].id),
                                                         "patient_id": "P-040", "make_admin": False}, headers=H)
        assert r.status_code == 201 and r.json()["show"].startswith("http://localhost:8600/invite/")
        page = c.get("/therapist/people").text
        assert "Patient P-040, with rivera" in page and r.json()["show"] not in page   # the link is shown once
        with SessionStore(tmp_db, clock=fake_clock).open() as s:
            invite_id = people.invites(s, made["sam"])[0]["id"]
        assert c.post(f"/therapist/api/people/invites/{invite_id}/revoke", json={}, headers=H).status_code == 200
        assert c.post(f"/therapist/api/people/accounts/{made['rivera'].id}/status", json={"status": "disabled"},
                      headers=H).status_code == 200
        assert c.post(f"/therapist/api/people/accounts/{made['sam'].id}/status", json={"status": "disabled"},
                      headers=H).status_code == 400                          # not yourself
        assert c.post(f"/therapist/api/people/accounts/{made['rivera'].id}/status", json={"status": "active"},
                      headers=H).status_code == 200
        assert c.post("/therapist/api/people/reassign", json={"patient_id": "P-002",
                                                              "therapist_id": str(made["therapist"].id)},
                      headers=H).status_code == 200
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        assert s.caseload_of("P-002") == made["therapist"].id


def test_the_last_admin_stays(tmp_db, fake_clock, made):
    with client(tmp_db, fake_clock) as c:
        sign_in(c, "sam")
        assert c.post(f"/therapist/api/people/accounts/{made['therapist'].id}/status", json={"status": "disabled"},
                      headers=H).status_code == 200
        c.post("/therapist/api/logout", json={}, headers=H)
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        with pytest.raises(Exception, match="last active admin"):
            accounts.set_status(s, made["sam"], made["sam"].id, "disabled")


def test_people_shows_no_clinical_field(tmp_db, fake_clock, made):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        plans.open_plan(s, "P-001", "Secret knee plan", "Torn ACL")
        s.update_patient("P-001", label="Knee label", notes="Private note")
    with client(tmp_db, fake_clock) as c:
        sign_in(c, "sam")
        page = c.get("/therapist/people").text
        for clinical in ("Secret knee plan", "Torn ACL", "Knee label", "Private note"):
            assert clinical not in page, clinical
