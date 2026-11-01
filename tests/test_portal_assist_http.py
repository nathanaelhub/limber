"""Feature 018 T011: when a therapist turns an AI switch on, the patient's Settings page says in plain words what is
processed and by whom (constitution III, v1.3.0). With no key, or switches off, it says nothing."""

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.assist import assistant
from src.portal import accounts
from src.ptlog.store import SessionStore

KEY = b"k" * 32
ORIGIN = "http://testserver"
PASSWORD = "correct horse battery"


@pytest.fixture
def signed_in(tmp_db):
    with SessionStore(tmp_db).open() as s:
        boss = accounts.create_account(s, username="boss", display_name="Pat Admin", password=PASSWORD, role="admin")
        theo = accounts.create_account(s, username="theo", display_name="Theo", password=PASSWORD, role="therapist")
        token, _ = accounts.create_invite(s, s.account_get(boss.id), "patient", therapist_id=theo.id, patient_id="P-021")
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN], therapist_url="http://therapist.test:8501")
    with TestClient(app, base_url=ORIGIN) as c:
        c.post(f"/api/invites/{token}", headers={"Origin": ORIGIN}, json={
            "display_name": "Kim", "username": "kim21", "password": PASSWORD, "password_again": PASSWORD, "prefs": {}})
        yield c, tmp_db


def test_nothing_without_a_key(signed_in):
    c, db = signed_in
    with SessionStore(db).open() as s:
        assistant.set_switch(s, "P-021", "summaries", True)
    assert c.get("/api/me/assistant").json() == {"notices": []}


def test_the_notice_for_each_switch_that_is_on(signed_in, monkeypatch):
    c, db = signed_in
    monkeypatch.setenv("LIMBER_ANTHROPIC_API_KEY", "sk-test-not-real")
    assert c.get("/api/me/assistant").json() == {"notices": []}
    with SessionStore(db).open() as s:
        assistant.set_switch(s, "P-021", "summaries", True)
    notices = c.get("/api/me/assistant").json()["notices"]
    assert len(notices) == 1 and "Anthropic" in notices[0] and "never your name" in notices[0]
    assert 'id="assistant-notice"' in c.get("/settings").text


def test_signed_out(tmp_db):
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN], therapist_url="http://therapist.test:8501")
    with TestClient(app, base_url=ORIGIN) as c:
        assert c.get("/api/me/assistant").status_code == 401
