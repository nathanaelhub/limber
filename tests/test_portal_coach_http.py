"""Feature 018 slice B through the portal: the coach page and its API, the entry points on Today and Messages, and
the referral's hand-over into Messages. The model is always the fake client."""

import json
from datetime import date

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.assist import assistant, client as aclient, coach
from src.portal import accounts
from src.ptlog.store import SessionStore

KEY = b"k" * 32
ORIGIN = "http://testserver"
H = {"Origin": ORIGIN}
PASSWORD = "correct horse battery"


@pytest.fixture
def signed_in(tmp_db):
    with SessionStore(tmp_db).open() as s:
        boss = accounts.create_account(s, username="boss", display_name="Pat Admin", password=PASSWORD, role="admin")
        theo = accounts.create_account(s, username="theo", display_name="Theo", password=PASSWORD, role="therapist")
        token, _ = accounts.create_invite(s, s.account_get(boss.id), "patient", therapist_id=theo.id, patient_id="P-021")
        s.assign_program("P-021", "custom", "Knee Home Program", ["knee_extension", "squat"], 3,
                         start_date=date(2020, 1, 1))
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN], therapist_url="http://therapist.test:8501")
    with TestClient(app, base_url=ORIGIN) as c:
        c.post(f"/api/invites/{token}", headers=H, json={
            "display_name": "Kim", "username": "kim21", "password": PASSWORD, "password_again": PASSWORD, "prefs": {}})
        yield c, tmp_db


@pytest.fixture
def coach_on(signed_in, monkeypatch):
    c, db = signed_in
    monkeypatch.setenv("LIMBER_ANTHROPIC_API_KEY", "sk-test-not-real")
    with SessionStore(db).open() as s:
        assistant.set_switch(s, "P-021", "coach", True)
    fake = aclient.FakeClient([])
    monkeypatch.setattr(aclient, "make_client", lambda: fake)
    return c, db, fake


def _answer(text="Knee Extension: 10 reps. Straighten the knee slowly."):
    return aclient.Reply(json.dumps({"kind": "answer", "exercise": "Knee Extension", "answer": text}), "end_turn",
                         coach.MODEL, 900, 100)


class TestPage:
    def test_the_page_and_its_states(self, coach_on):
        c, *_ = coach_on
        html = c.get("/coach").text
        for piece in ('id="coach-off"', 'id="suggestions"', 'id="emergency-card"', 'id="referral-card"',
                      "Answers come from an AI assistant using your exercise program. Your therapist can read this chat.",
                      'href="tel:911"', "Find the nearest emergency room", "That's one for your therapist",
                      "Message your therapist", "You've reached today's question limit", 'src="/static/coach.js"'):
            assert piece in html, piece
        view = c.get("/api/coach").json()
        assert view["state"] == "on" and view["patient_id"] == "P-021" and len(view["suggestions"]) == 3
        assert view["turns"] == [] and view["left"] == 20
        assert view["er_url"].startswith("https://www.google.com/maps/search/") and "lat" not in view["er_url"]

    def test_off_without_a_key_or_the_switch(self, signed_in, monkeypatch):
        c, db = signed_in
        with SessionStore(db).open() as s:
            assistant.set_switch(s, "P-021", "coach", True)
        assert c.get("/api/coach").json()["state"] == "off"                 # no key configured
        monkeypatch.setenv("LIMBER_ANTHROPIC_API_KEY", "sk-test-not-real")
        with SessionStore(db).open() as s:
            assistant.set_switch(s, "P-021", "coach", False)
        assert c.get("/api/coach").json()["state"] == "off"

    def test_signed_out(self, tmp_db):
        app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN], therapist_url="http://therapist.test:8501")
        with TestClient(app, base_url=ORIGIN) as c:
            assert c.get("/api/coach").status_code == 401
            assert c.get("/coach", follow_redirects=False).status_code == 303


class TestAsking:
    def test_an_answer_then_it_is_in_todays_turns(self, coach_on):
        c, db, fake = coach_on
        fake.script.append(_answer())
        r = c.post("/api/coach", headers=H, json={"question": "How many knee extensions?"})
        assert r.status_code == 200
        body = r.json()
        assert (body["kind"], body["exercise"], body["ai"], body["left"]) == ("answer", "Knee Extension", True, 19)
        turns = c.get("/api/coach").json()["turns"]
        assert [(t["question"], t["kind"]) for t in turns] == [("How many knee extensions?", "answer")]

    def test_red_flag_is_the_emergency_card_and_no_call(self, coach_on):
        c, db, fake = coach_on
        r = c.post("/api/coach", headers=H, json={"question": "My calf is swollen and hot"}).json()
        assert (r["kind"], r["ai"]) == ("emergency", False) and fake.bodies == []

    def test_red_flag_without_a_key_still_gets_the_card(self, signed_in):
        c, _ = signed_in
        assert c.post("/api/coach", headers=H, json={"question": "I can't breathe"}).json()["kind"] == "emergency"
        assert c.post("/api/coach", headers=H, json={"question": "How many?"}).json()["kind"] == "off"

    def test_refused_from_another_origin_or_empty(self, coach_on):
        c, *_ = coach_on
        assert c.post("/api/coach", headers={"Origin": "http://evil.test"}, json={"question": "x"}).status_code == 403
        assert c.post("/api/coach", headers=H, json={"question": "  "}).status_code == 400
        assert c.post("/api/coach", headers=H, json={}).status_code == 400


class TestEntryPoints:
    def test_today_and_messages_show_the_entry_only_when_on(self, signed_in, monkeypatch):
        c, db = signed_in
        assert c.get("/api/today").json()["coach"] == {"enabled": False}
        for page in ("/today", "/messages"):
            assert 'id="coach-entry"' in c.get(page).text and 'href="/coach"' in c.get(page).text
        monkeypatch.setenv("LIMBER_ANTHROPIC_API_KEY", "sk-test-not-real")
        with SessionStore(db).open() as s:
            assistant.set_switch(s, "P-021", "coach", True)
        assert c.get("/api/today").json()["coach"] == {"enabled": True}

    def test_the_referral_copies_the_question_into_messages(self, coach_on):
        """The referral card's link carries the question; the messages page fills the box from it."""
        c, *_ = coach_on
        js = c.get("/static/coach.js").text
        assert '"/messages?text=" + encodeURIComponent(question)' in js
        assert 'get("text")' in c.get("/static/messages.js").text
