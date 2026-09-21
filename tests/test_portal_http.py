"""Feature 007 T013 — the patient service over HTTP, in-process (no network): sign-in, today's
program, the security baseline, and the rule that a patient only ever sees their own data."""

import json
import re
from datetime import date, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.portal import access
from src.ptlog.models import ExerciseSetInfo, RepEvent
from src.ptlog.store import SessionStore

KEY = b"k" * 32
ORIGIN = "http://testserver"
FORBIDDEN_KEYS = {"flags", "flag", "notes_private", "review", "next_step", "threshold", "thresholds", "label"}


@pytest.fixture
def seeded(tmp_db):
    """Three patients; P-017 has a program, a goal, a label, notes, a reviewed session, and an override."""
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-017", label="Post-op knee", notes="prefers mornings")
        s.add_patient("P-018", label="Shoulder")
        s.add_patient("P-019")
        s.assign_program("P-017", "custom", "Knee Home Program", ["knee_extension", "squat"], 3,
                         date.today() - timedelta(days=10))
        s.set_goal("P-017", "Knee Extension", target_rom=95.0, target_reps=12)
        s.set_patient_threshold("P-017", "rom_regression", 5)
        for pid in ("P-017", "P-018"):
            sid = s.start_session(pid, "video", "clip.mp4")
            set_id = s.open_set(sid, ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0))
            s.add_rep(set_id, RepEvent(1, 90.0, 170.0, 80.0, 2.5, 88.0, datetime.now().isoformat(), 60))
            s.end_session(sid)
            s.set_review(sid, "continue", notes="Watch the hip hiking")
        codes = {pid: access.issue_code(s, KEY, pid)[0] for pid in ("P-017", "P-018")}
    return tmp_db, codes


@pytest.fixture
def client(seeded):
    db, _ = seeded
    app = create_app(db_path=db, key=KEY, allowed_origins=[ORIGIN])
    with TestClient(app, base_url=ORIGIN) as c:
        yield c


def login(client, code, origin=ORIGIN):
    return client.post("/api/login", json={"code": code}, headers={"Origin": origin})


def audit(db):
    with SessionStore(db).open() as s:
        return [(a.event, a.patient_id, a.detail) for a in s.portal_audit_list()]


class TestSignIn:
    def test_health_needs_no_sign_in(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200 and r.json()["ok"] is True and "pose_assets" in r.json()

    def test_login_sets_a_private_cookie(self, client, seeded):
        r = login(client, seeded[1]["P-017"])
        assert r.status_code == 200 and r.json() == {"patient_id": "P-017"}
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
        assert seeded[1]["P-017"].lower() not in cookie
        assert ("login_ok", "P-017", None) in audit(seeded[0])

    def test_every_refusal_reads_the_same(self, client, seeded):
        db, codes = seeded
        with SessionStore(db).open() as s:
            s.portal_revoke("P-018")
        bodies = {login(client, c).text for c in ("0000-0000-0000", "nonsense", codes["P-018"])}
        assert len(bodies) == 1 and "did not work" in bodies.pop()
        assert login(client, "0000-0000-0000").status_code == 401

    def test_sixth_failure_is_locked_out(self, client, seeded):
        for _ in range(5):
            assert login(client, "0000-0000-0000").status_code == 401
        r = login(client, seeded[1]["P-017"])                       # even the right code must wait
        assert r.status_code == 429 and r.json()["retry_after_seconds"] >= 60 and "retry-after" in r.headers
        assert audit(seeded[0])[0][0] == "locked_out"

    def test_posts_need_an_allowed_origin_and_json(self, client, seeded):
        code = seeded[1]["P-017"]
        assert login(client, code, origin="https://evil.example").status_code == 403
        assert client.post("/api/login", json={"code": code}).status_code == 403                   # no Origin at all
        r = client.post("/api/login", content=f"code={code}", headers={"Origin": ORIGIN,
                        "Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 415
        assert client.post("/api/login", content="{not json", headers={"Origin": ORIGIN,
                           "Content-Type": "application/json"}).status_code == 400

    def test_logout_and_revocation_end_the_sign_in(self, client, seeded):
        db, codes = seeded
        login(client, codes["P-017"])
        assert client.get("/api/today").status_code == 200
        assert client.post("/api/logout", json={}, headers={"Origin": ORIGIN}).status_code == 200
        assert client.get("/api/today").status_code == 401
        login(client, codes["P-017"])
        with SessionStore(db).open() as s:
            access.revoke_code(s, "P-017")
        assert client.get("/api/today").status_code == 401
        assert ("logout", "P-017", None) in audit(db) and ("code_revoked", "P-017", None) in audit(db)


class TestToday:
    def test_needs_a_sign_in(self, client):
        r = client.get("/api/today")
        assert r.status_code == 401 and r.json() == {"error": "Please sign in."}

    def test_contract_shape(self, client, seeded):
        login(client, seeded[1]["P-017"])
        r = client.get("/api/today")
        body = r.json()
        assert r.headers["cache-control"] == "no-store"
        assert body["patient_id"] == "P-017" and body["program"] == {"name": "Knee Home Program", "sessions_per_week": 3}
        assert body["exercises"][0] == {"key": "knee_extension", "name": "Knee Extension", "target_reps": 12,
                                        "done_today": True}
        assert body["exercises"][1]["done_today"] is False and body["week"]["planned"] == 3

    def test_patient_without_a_program(self, client, seeded):
        login(client, seeded[1]["P-018"])
        body = client.get("/api/today").json()
        assert body["program"] is None and "not assigned" in body["message"]


class TestOnlyOwnData:
    """SC-002: no response contains another patient's ID or a forbidden field."""

    def _walk(self, value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from self._walk(v)
        elif isinstance(value, list):
            for v in value:
                yield from self._walk(v)

    def test_no_leak_on_any_route(self, client, seeded):
        login(client, seeded[1]["P-017"])
        for route in ("/api/today", "/api/health", "/", "/today"):
            r = client.get(route)
            text = r.text
            assert "P-018" not in text and "P-019" not in text, route
            for secret in ("Post-op knee", "prefers mornings", "hip hiking", "Shoulder"):
                assert secret not in text, (route, secret)
            if r.headers["content-type"].startswith("application/json"):
                assert not (set(self._walk(r.json())) & FORBIDDEN_KEYS), route

    def test_a_patient_id_in_the_request_is_ignored(self, client, seeded):
        login(client, seeded[1]["P-017"])
        assert client.get("/api/today", params={"patient_id": "P-018", "patient": "P-018"}).json()["patient_id"] == "P-017"


class TestPagesAndHeaders:
    def test_security_headers_everywhere(self, client):
        for route in ("/", "/api/health", "/static/portal.css"):
            h = client.get(route).headers
            csp = h["content-security-policy"]
            assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp
            assert "unsafe-inline" not in csp and "http:" not in csp and "https:" not in csp, route
            assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"
            assert "camera=(self)" in h["permissions-policy"]

    def test_inner_pages_redirect_when_signed_out(self, client, seeded):
        for route in ("/today", "/session", "/progress"):
            r = client.get(route, follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == "/"
        login(client, seeded[1]["P-017"])
        assert client.get("/today", follow_redirects=False).status_code == 200

    def test_sign_in_page_says_what_is_sent(self, client):
        html = client.get("/").text.lower()
        for phrase in ("never leaves", "body points", "demo and study"):
            assert phrase in html, phrase

    def test_brand(self, client):
        html = client.get("/").text
        assert "Limber" in html and "/static/limber-mark.svg" in html and "PT Assist" not in html
        mark = client.get("/static/limber-mark.svg")
        assert mark.status_code == 200 and "#0E6B64" in mark.text and "#F2684A" in mark.text
        assert client.get("/favicon.ico").headers["content-type"] == "image/png"

    def test_pages_load_nothing_from_other_sites(self):
        """FR-018: every script, style, and model file comes from the service itself."""
        from interfaces import patient_portal
        for page in patient_portal.STATIC_DIR.glob("*.html"):
            html = page.read_text()
            assert not re.findall(r"""(?:src|href)=["'](?:https?:)?//""", html), page.name
            assert "<script>" not in html and "onclick=" not in html, page.name      # no inline script (CSP)
        for script in patient_portal.STATIC_DIR.glob("*.js"):
            text = script.read_text().replace('"http://www.w3.org/2000/svg"', "")     # an XML namespace, never fetched
            assert not re.findall(r"""["']https?://""", text), script.name
