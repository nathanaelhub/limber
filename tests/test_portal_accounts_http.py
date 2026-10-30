"""Feature 016 through the portal: username sign-in at both doors, the invite page, and settings."""

import re

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.portal import accounts, admin
from src.ptlog.store import SessionStore

KEY = b"k" * 32
ORIGIN = "http://testserver"
PASSWORD = "correct horse battery"
H = {"Origin": ORIGIN}


@pytest.fixture
def setup(tmp_db):
    with SessionStore(tmp_db).open() as s:
        boss = accounts.create_account(s, username="boss", display_name="Pat Admin", password=PASSWORD, role="admin")
        theo = accounts.create_account(s, username="theo", display_name="Theo", password=PASSWORD, role="therapist")
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN], therapist_url="http://therapist.test:8501")
    with TestClient(app, base_url=ORIGIN) as c:
        yield c, tmp_db, boss, theo


def invite(db, boss, role, **kw):
    with SessionStore(db).open() as s:
        token, _ = accounts.create_invite(s, s.account_get(boss.id), role, **kw)
    return token


def onboard(c, token, username, prefs=None, again=PASSWORD):
    return c.post(f"/api/invites/{token}", headers=H, json={
        "display_name": username.title(), "username": username, "password": PASSWORD, "password_again": again,
        "prefs": prefs or {}})


class TestTherapistDoor:
    def test_username_and_password_hand_over_that_account(self, setup):
        c, db, _, theo = setup
        r = c.post("/api/admin/login", headers=H, json={"username": "theo", "password": PASSWORD})
        assert r.status_code == 200
        a_pass = re.search(r"pass=([\w-]+)", r.json()["redirect"]).group(1)
        with SessionStore(db).open() as s:
            assert admin.signed_in(s, admin.redeem_pass(s, a_pass)).id == theo.id

    def test_wrong_password_is_refused(self, setup):
        c, *_ = setup
        r = c.post("/api/admin/login", headers=H, json={"username": "theo", "password": "not it at all"})
        assert r.status_code == 401

    def test_the_front_page_asks_for_a_username(self, setup):
        c, *_ = setup
        html = c.get("/").text
        assert 'id="staff-username"' in html and 'id="patient-username"' in html


class TestPatientDoor:
    def test_a_patient_account_signs_in_with_a_username(self, setup):
        c, db, boss, theo = setup
        token = invite(db, boss, "patient", therapist_id=theo.id, patient_id="P-017")
        assert onboard(c, token, "sam").status_code == 200
        c.cookies.clear()
        r = c.post("/api/login", headers=H, json={"username": "sam", "password": PASSWORD})
        assert r.status_code == 200 and r.json()["patient_id"] == "P-017"
        assert c.get("/api/today").status_code == 200

    def test_staff_cannot_open_the_patient_side(self, setup):
        c, *_ = setup
        r = c.post("/api/login", headers=H, json={"username": "theo", "password": PASSWORD})
        assert r.status_code == 401


class TestInvitePage:
    def test_page_status_and_onboarding_a_therapist(self, setup):
        c, db, boss, _ = setup
        token = invite(db, boss, "therapist")
        assert c.get(f"/invite/{token}").status_code == 200
        assert c.get(f"/api/invites/{token}").json()["role"] == "therapist"
        r = onboard(c, token, "nora", prefs={"larger_text": True})
        assert r.status_code == 200 and "pass=" in r.json()["redirect"]
        assert c.get(f"/api/invites/{token}").status_code == 410
        with SessionStore(db).open() as s:
            nora = s.account_by_username("nora")
            assert nora.role == "therapist" and accounts.get_prefs(s, nora.id)["larger_text"] is True

    def test_mistakes_keep_the_link(self, setup):
        c, db, boss, _ = setup
        token = invite(db, boss, "therapist")
        r = onboard(c, token, "nora", again="something else entirely")
        assert r.status_code == 400 and "match" in r.json()["error"]
        r = onboard(c, token, "theo")
        assert r.status_code == 400 and "taken" in r.json()["error"]
        assert c.get(f"/api/invites/{token}").status_code == 200

    def test_patient_onboarding_signs_the_patient_in(self, setup):
        c, db, boss, theo = setup
        token = invite(db, boss, "patient", therapist_id=theo.id, patient_id="P-021")
        r = onboard(c, token, "jo21", prefs={"high_contrast": True})
        assert r.status_code == 200 and r.json()["redirect"] == "/today"
        assert c.get("/api/me/preferences").json()["high_contrast"] is True

    def test_unknown_link(self, setup):
        c, *_ = setup
        r = c.get("/api/invites/made-up")
        assert r.status_code == 410 and "expired" in r.json()["error"]
        assert onboard(c, "made-up", "nora").status_code == 410

    def test_onboarding_needs_the_page_origin(self, setup):
        c, db, boss, _ = setup
        token = invite(db, boss, "therapist")
        r = c.post(f"/api/invites/{token}", json={"username": "x"}, headers={"Origin": "http://evil.test"})
        assert r.status_code == 403


class TestSettings:
    @pytest.fixture
    def signed_in(self, setup):
        c, db, boss, theo = setup
        token = invite(db, boss, "patient", therapist_id=theo.id, patient_id="P-030")
        onboard(c, token, "kim")
        return c

    def test_change_and_apply_on_first_render(self, signed_in):
        c = signed_in
        assert c.get("/api/me/preferences").json() == {"larger_text": False, "high_contrast": False,
                                                        "reduced_motion": False}
        r = c.post("/api/me/preferences", headers=H, json={"larger_text": True, "reduced_motion": True})
        assert r.status_code == 200 and r.json()["larger_text"] is True
        html = c.get("/today").text
        assert '<html lang="en" class="a11y-large a11y-calm">' in html
        assert c.get("/settings").status_code == 200

    def test_signed_out_gets_nothing(self, setup):
        c, *_ = setup
        assert c.get("/api/me/preferences").status_code == 401
        assert c.post("/api/me/preferences", headers=H, json={}).status_code == 401
