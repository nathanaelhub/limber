"""Feature 019 slice 5c (T027): the Tracker in the clinic app. Re-expresses what tests/test_app_pages.py pinned for
Streamlit's Tracker, plus queue links and admin-only changes to the clinic-wide thresholds."""

from datetime import date, datetime

import pytest

from src.clinic import tracker
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in
from tests.test_clinic_records import Clock

REPS = [(80, 50, 2.0), (70, 45, 2.5)]


@pytest.fixture
def world(tmp_db, make_session):
    clock = Clock(datetime(2026, 3, 1, 9, 0))
    seed(tmp_db, clock)
    with SessionStore(tmp_db, clock=clock).open() as s:
        make_session(s, clock, "P-001", "Knee Extension", datetime(2026, 3, 16, 9, 0), REPS)
        make_session(s, clock, "P-002", "Squat", datetime(2026, 3, 16, 10, 0), REPS)
    clock.set(datetime(2026, 3, 23, 9, 15))
    with client(tmp_db, clock) as c:
        sign_in(c)
        yield c, tmp_db, clock


def test_every_section_renders_and_obeys_the_policy(world):
    c, *_ = world
    from tests.test_clinic_static import _checked
    assert c.get("/therapist/tracker").status_code == 200
    for key, _ in tracker.SECTIONS:
        r = c.get(f"/therapist/tracker/{key}")
        assert r.status_code == 200, key
        _checked(r.text, key)
    assert c.get("/therapist/tracker/nothing").status_code == 404


def test_the_roster_shows_the_columns_and_only_the_caseload(world):
    c, *_ = world
    page = c.get("/therapist/tracker/roster").text
    assert "Pending reviews (count)" in page and "Unread messages (count)" in page
    assert ">P-001<" in page and ">P-002<" not in page
    assert "No active patients match." in c.get("/therapist/tracker/roster?program=custom").text


def test_the_queue_links_each_item_to_where_it_is_dealt_with(world):
    c, *_ = world
    page = c.get("/therapist/tracker/queue").text
    assert "Adherence attention threshold" in page and "Pending reviews" in page
    assert "/therapist/review/P-001/session?session=" in page and "P-002" not in page


def test_targets_become_links():
    class Item:
        def __init__(self, target, pid="P-1"):
            self.target, self.patient_id = target, pid
    assert tracker.item_href(Item("session:7")) == "/therapist/review/P-1/session?session=7"
    assert tracker.item_href(Item("flags:P-1")) == "/therapist/review/P-1/flags"
    assert tracker.item_href(Item("inbox:P-1")) == "/therapist/inbox/P-1"
    assert tracker.item_href(Item("adherence:P-1")) == "/therapist/tracker/adherence?patient=P-1"
    assert tracker.item_href(Item("questionnaires:P-1")) == "/therapist/review/P-1/from-patient"
    assert tracker.item_href(Item("nonsense")) is None


def test_adherence_states(world):
    c, db, clock = world
    assert "No program assigned to P-001" in c.get("/therapist/tracker/adherence?patient=P-001").text
    with SessionStore(db, clock=clock).open() as s:
        s.assign_program("P-001", "custom", "Custom", ["knee_extension"], 3, date(2026, 3, 2), None)
    page = c.get("/therapist/tracker/adherence?patient=P-001").text
    assert "Recorded / planned (count)" in page and "Attention threshold" in page
    assert c.get("/therapist/tracker/adherence?patient=P-002").status_code == 404


def test_discharged_and_reactivate(world):
    c, db, clock = world
    with SessionStore(db, clock=clock).open() as s:
        s.discharge("P-001", date(2026, 3, 20), "goals met")
    page = c.get("/therapist/tracker/discharged").text
    assert "goals met" in page and 'data-api="/api/patients/P-001/reactivate"' in page


def test_the_roster_csv(world):
    c, *_ = world
    r = c.get("/therapist/tracker/export/roster.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and "P-001" in r.text
    assert "P-002" not in r.text


def test_clinic_thresholds_are_read_by_all_and_changed_by_admins(world):
    c, db, clock = world
    from src.ptlog import thresholds
    values = {k: d.default for k, d in thresholds.THRESHOLDS.items()}
    values["form_drop"] = 8
    r = c.post("/therapist/api/tracker/thresholds", json=values, headers=H)
    assert r.json()["notice"] == "Clinic thresholds saved."
    with SessionStore(db, clock=clock).open() as s:
        assert s.get_installation_thresholds() == {"form_drop": 8}
    assert "Change history" in c.get("/therapist/tracker/settings").text
    assert c.post("/therapist/api/tracker/thresholds/restore", json={}, headers=H).status_code == 200
    c.post("/therapist/api/logout", json={}, headers=H)
    sign_in(c, "rivera")                                       # a therapist who is not an admin
    assert "Only an admin can change these" in c.get("/therapist/tracker/settings").text
    assert c.post("/therapist/api/tracker/thresholds", json=values, headers=H).status_code == 403


def test_footer_lines():
    lines = ["Prog — 3", "week 1 ...", "Adherence: 50% over 2 complete weeks", "other"]
    assert tracker.adherence_footer_lines(lines) == ["Adherence: 50% over 2 complete weeks"]
