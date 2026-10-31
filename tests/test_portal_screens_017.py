"""Feature 017 patient screens (T009): the Visits page, the five-item navigation on every page, Today's
plan cards and next visit, and the "Seen" receipt on the patient's own messages."""

import re

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.portal import access, messages, plans, pwa
from src.ptlog.store import SessionStore

KEY = b"k" * 32
ORIGIN = "http://testserver"
H = {"Origin": ORIGIN}
INNER = ["today", "progress", "messages", "visits", "settings", "checkin", "clip", "diary", "log",
         "questionnaire", "voice", "session"]


@pytest.fixture
def setup(tmp_db):
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-021")
        s.conversation_set_enabled("P-021", True)
        knee = s.plans("P-021")[0]
        plans.edit_plan(s, knee.id, title="Right knee, post-op")
        shoulder = plans.open_plan(s, "P-021", "Left shoulder")
        code = access.issue_code(s, KEY, "P-021")[0]
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN])
    with TestClient(app, base_url=ORIGIN) as c:
        assert c.post("/api/login", json={"code": code}, headers=H).status_code == 200
        yield c, tmp_db, knee, shoulder


class TestNavigation:
    @pytest.mark.parametrize("page", INNER)
    def test_every_page_has_the_five_destinations(self, setup, page):
        c, *_ = setup
        html = c.get(f"/{page}").text
        nav = re.search(r'<nav class="tabs"[^>]*>(.*?)</nav>', html, re.S)
        assert nav, page
        assert re.findall(r'href="(/[a-z]+)"', nav.group(1)) == ["/today", "/progress", "/messages", "/visits",
                                                                "/settings"]

    def test_the_current_page_is_marked(self, setup):
        c, *_ = setup
        assert re.search(r'href="/visits"[^>]*aria-current="page"', c.get("/visits").text)

    def test_visits_needs_sign_in_and_is_in_the_installed_app(self, setup):
        c, *_ = setup
        assert "/visits" in pwa.PAGES
        c.cookies.clear()
        r = c.get("/visits", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/"


class TestTodayPlans:
    def test_a_card_per_active_plan_and_the_next_visit(self, setup):
        c, db, knee, shoulder = setup
        with SessionStore(db).open() as s:
            messages.send(s, "P-021", "therapist", "How were the stairs?", plan_id=knee.id)
            later = plans.schedule(s, "P-021", "2030-11-11T10:00", 30, plan_id=knee.id)
            plans.schedule(s, "P-021", "2030-11-04T09:00", 45, "Re-check range of motion", plan_id=knee.id)
            plans.cancel(s, plans.schedule(s, "P-021", "2030-11-01T09:00", 45, plan_id=knee.id).id)
            done = plans.open_plan(s, "P-021", "Left ankle")
            plans.complete(s, done.id)
        d = c.get("/api/today").json()
        assert [(p["title"], p["unread"]) for p in d["plans"]] == [("Right knee, post-op", 1), ("Left shoulder", 0)]
        assert all(p["has_program"] is False for p in d["plans"])     # no program assigned in this record
        assert (d["next_visit"]["date"], d["next_visit"]["time"]) == ("2030-11-04", "09:00")
        assert d["next_visit"]["id"] != later.id

    def test_no_visit_booked(self, setup):
        c, *_ = setup
        assert c.get("/api/today").json()["next_visit"] is None


class TestSeen:
    def test_own_messages_say_when_the_therapist_has_read_them(self, setup):
        c, db, knee, _ = setup
        c.post(f"/api/plans/{knee.id}/messages", json={"text": "first"}, headers=H)
        (m,) = c.get(f"/api/plans/{knee.id}/messages").json()["messages"]
        assert m["seen"] is False
        with SessionStore(db).open() as s:
            messages.thread(s, "P-021", viewer="therapist", plan_id=knee.id)
        (m,) = c.get(f"/api/plans/{knee.id}/messages").json()["messages"]
        assert m["seen"] is True


class TestPagesCarryTheirControls:
    def test_messages_page_has_the_switcher_and_the_attachment_inputs(self, setup):
        c, *_ = setup
        html = c.get("/messages").text
        assert 'id="plan-switcher"' in html and 'id="tray"' in html and 'id="past-plan"' in html
        assert re.search(r'<input[^>]*id="take-photo"[^>]*capture="environment"', html)
        assert re.search(r'<input[^>]*id="pick-pdf"[^>]*accept="application/pdf"', html)
        assert 'src="/static/messages.js"' in html

    def test_visits_page_has_the_list_month_and_reschedule_sheet(self, setup):
        c, *_ = setup
        html = c.get("/visits").text
        for el in ("upcoming", "month", "reschedule-sheet", "reschedule-note"):
            assert f'id="{el}"' in html
        assert 'src="/static/visits.js"' in html
