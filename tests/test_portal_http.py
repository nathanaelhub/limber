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
        s.add_patient("P-018", label="Rotator cuff repair")
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
        from src.portal import messages as conversation
        with SessionStore(seeded[0]).open() as s:
            for pid in ("P-017", "P-018"):
                conversation.set_enabled(s, pid, True)
            conversation.send(s, "P-018", "patient", "a private note from the other patient")
            conversation.send(s, "P-017", "therapist", "well done this week")
        login(client, seeded[1]["P-017"])
        with SessionStore(seeded[0]).open() as s:
            s.entry_add("P-018", "checkin", {"pain": 9, "note": "other patient's private note"}, 9.0,
                        "2026-09-20T09:00:00", "x", "standalone", None, False, False)
        for route in ("/api/today", "/api/health", "/", "/today", "/api/progress", "/progress", "/api/messages", "/messages",
                      "/api/entries", "/checkin", "/manifest.webmanifest", "/api/media", "/clip"):
            r = client.get(route)
            text = r.text
            assert "P-018" not in text and "P-019" not in text, route
            for secret in ("Post-op knee", "prefers mornings", "hip hiking", "Rotator cuff repair", "other patient", "private note"):
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
            # The camera is for a guided session, the microphone for a voice note (feature 014); both are
            # this page's own and nobody else's, and geolocation is refused outright.
            assert "camera=(self)" in h["permissions-policy"] and "microphone=(self)" in h["permissions-policy"]
            assert "geolocation=()" in h["permissions-policy"]

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

    def test_hidden_elements_stay_hidden(self, client):
        """Found in a browser run: classes that set `display` overrode the hidden attribute, so the
        unread badge and other hidden elements still showed."""
        css = client.get("/static/portal.css").text
        assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", css)

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


class TestProgress:
    def test_needs_a_sign_in_and_returns_the_view(self, client, seeded):
        assert client.get("/api/progress").status_code == 401
        login(client, seeded[1]["P-017"])
        r = client.get("/api/progress")
        body = r.json()
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store" and body["patient_id"] == "P-017"
        assert body["exercises"][0]["name"] == "Knee Extension" and "clinic" in body["exercises"][0]["series"]
        assert "P-018" not in r.text and "hip hiking" not in r.text and "Post-op" not in r.text
        page = client.get("/progress").text
        assert 'id="progress"' in page and "Coming soon" not in page


# ----------------------------------------------------------------------------- feature 008: the patient's conversation

from src.portal import messages as pmsg  # noqa: E402


def _post_message(client, text, confirm=False):
    return client.post("/api/messages", json={"text": text, "confirm": confirm}, headers={"Origin": ORIGIN})


class TestMessages:
    def test_need_a_sign_in(self, client):
        assert client.get("/api/messages").status_code == 401
        assert _post_message(client, "hello").status_code == 401

    def test_off_by_default(self, client, seeded):
        login(client, seeded[1]["P-017"])
        assert client.get("/api/messages").json()["enabled"] is False
        assert client.get("/api/today").json()["messages"] == {"enabled": False, "unread": 0}
        assert _post_message(client, "hello").status_code == 403

    def test_send_read_warn_and_confirm(self, client, seeded):
        db, codes = seeded
        with SessionStore(db).open() as s:
            pmsg.set_enabled(s, "P-017", True)
            pmsg.set_enabled(s, "P-018", True)
            pmsg.send(s, "P-017", "therapist", "How did the stairs go?")
            pmsg.send(s, "P-018", "therapist", "A note for someone else entirely")
        login(client, codes["P-017"])
        assert client.get("/api/today").json()["messages"] == {"enabled": True, "unread": 1}
        r = _post_message(client, "Better today <3")
        assert r.status_code == 201 and r.json()["text"] == "Better today <3" and r.json()["from"] == "you"
        body = client.get("/api/messages").json()
        assert [(m["from"], m["text"]) for m in body["messages"]] == [("therapist", "How did the stairs go?"), ("you", "Better today <3")]
        assert body["notice"].startswith("Not for emergencies") and body["patient_id"] == "P-017"
        assert client.get("/api/today").json()["messages"]["unread"] == 0                # reading marked it
        assert "someone else" not in client.get("/api/messages").text and "P-018" not in client.get("/api/messages").text
        warned = _post_message(client, "call me on 615-555-0142")
        assert warned.status_code == 409 and warned.json()["reasons"] == ["phone number"]
        assert _post_message(client, "call me on 615-555-0142", confirm=True).status_code == 201
        assert _post_message(client, "").status_code == 400 and _post_message(client, "x" * 2001).status_code == 400
        assert client.post("/api/messages", json={"text": "hi"}, headers={"Origin": "https://evil.example"}).status_code == 403
        with SessionStore(db).open() as s:
            assert pmsg.unread_count(s, "P-017", viewer="therapist") == 2

    def test_page_always_shows_the_notice(self, client, seeded):
        assert client.get("/messages", follow_redirects=False).status_code == 303
        login(client, seeded[1]["P-017"])
        html = client.get("/messages").text
        assert "Not for emergencies" in html and 'id="thread"' in html


class TestHealthProvesTheRecordWorks:
    """Feature 009 FR-006: the health check reads and writes the record."""

    def test_ok(self, client):
        body = client.get("/api/health").json()
        assert body["ok"] is True and body["record"] == "ok"

    def test_unwritable_record_is_unhealthy(self, client, seeded, monkeypatch):
        from src.deploy import preflight
        monkeypatch.setattr(preflight, "_record_writable", lambda db: "attempt to write a readonly database")
        r = client.get("/api/health")
        assert r.status_code == 503 and r.json()["ok"] is False and r.json()["record"] == "unavailable"
        assert "readonly" not in r.text                     # no internals in a public response


class TestDeviceLogin:
    def test_device_flag_gives_a_long_cookie(self, client, seeded):
        r = client.post("/api/login", json={"code": seeded[1]["P-017"], "device": True}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "max-age=2592000" in cookie and "httponly" in cookie
        r = client.post("/api/login", json={"code": seeded[1]["P-017"]}, headers={"Origin": ORIGIN})
        assert "max-age=43200" in r.headers["set-cookie"].lower()


# ----------------------------------------------------------------------------- feature 010: check-ins

CHECKIN = {"pain": 4, "area": "knee", "stiffness": "mild", "swelling": "none", "note": ""}


def _checkin(client, body):
    return client.post("/api/entries", json=body, headers={"Origin": ORIGIN})


class TestCheckins:
    def test_needs_a_sign_in(self, client):
        assert _checkin(client, {"kind": "checkin", "client_id": "c1", "data": CHECKIN}).status_code == 401
        assert client.get("/api/entries").status_code == 401

    def test_store_list_and_resend_once(self, client, seeded):
        login(client, seeded[1]["P-017"])
        r = _checkin(client, {"kind": "checkin", "client_id": "c1", "data": CHECKIN, "phase": "standalone",
                              "recorded_at": "2020-01-01T09:00:00"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["kind"] == "checkin" and body["score"] == 4 and body["time_adjusted"] is True and body["payload"]["area"] == "knee"
        again = _checkin(client, {"kind": "checkin", "client_id": "c1", "data": {**CHECKIN, "pain": 9}})
        assert again.status_code == 200 and again.json()["id"] == body["id"] and again.json()["score"] == 4
        listing = client.get("/api/entries").json()
        assert [e["id"] for e in listing["entries"]] == [body["id"]] and listing["definitions"]["checkin"]["pain"]["unit"] == "0-10"
        assert client.get("/api/today").json()["checkin"] == {"prompt": True, "today": 1}

    def test_validation_warning_and_confirm(self, client, seeded):
        login(client, seeded[1]["P-017"])
        assert _checkin(client, {"kind": "checkin", "client_id": "c2", "data": {**CHECKIN, "pain": 11}}).status_code == 400
        assert _checkin(client, {"kind": "horoscope", "client_id": "c3", "data": CHECKIN}).status_code == 400
        assert _checkin(client, {"kind": "checkin", "data": CHECKIN}).status_code == 400          # client_id required
        warned = _checkin(client, {"kind": "checkin", "client_id": "c4", "data": {**CHECKIN, "note": "call me on 615-555-0142"}})
        assert warned.status_code == 409 and warned.json()["reasons"] == ["phone number"]
        ok = _checkin(client, {"kind": "checkin", "client_id": "c4", "data": {**CHECKIN, "note": "call me on 615-555-0142"}, "confirm": True})
        assert ok.status_code == 201 and ok.json()["warned"] is True

    def test_session_link_must_be_the_patients_own(self, client, seeded):
        db, codes = seeded
        with SessionStore(db).open() as s:
            mine = s.list_sessions("P-017")[0].id
            theirs = s.list_sessions("P-018")[0].id
        login(client, codes["P-017"])
        assert _checkin(client, {"kind": "checkin", "client_id": "c5", "data": CHECKIN, "phase": "before", "session_id": mine}).status_code == 201
        assert _checkin(client, {"kind": "checkin", "client_id": "c6", "data": CHECKIN, "phase": "before", "session_id": theirs}).status_code == 400

    def test_discharged_patient_is_refused(self, client, seeded):
        db, codes = seeded
        login(client, codes["P-017"])
        with SessionStore(db).open() as s:
            s.discharge("P-017")
        assert _checkin(client, {"kind": "checkin", "client_id": "c7", "data": CHECKIN}).status_code == 401

    def test_progress_carries_pain(self, client, seeded):
        login(client, seeded[1]["P-017"])
        _checkin(client, {"kind": "checkin", "client_id": "c8", "data": CHECKIN})
        body = client.get("/api/progress").json()
        assert body["pain"]["series"][0]["pain"] == 4 and body["pain"]["definition"]["unit"] == "0-10"
        assert client.get("/checkin").status_code == 200


# ----------------------------------------------------------------------------- feature 011: clips

import hashlib  # noqa: E402
from tests.fixtures import media as media_fx  # noqa: E402


def _upload_clip(client, path, caption="", confirm=False, chunk=4096):
    data = path.read_bytes()
    r = client.post("/api/uploads", json={"kind": "clip", "total_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                           "chunk_bytes": chunk}, headers={"Origin": ORIGIN})
    if r.status_code != 201:
        return r
    up = r.json()
    for n, start in enumerate(range(0, len(data), chunk)):
        pr = client.put(f"/api/uploads/{up['id']}/parts/{n}", content=data[start:start + chunk],
                        headers={"Origin": ORIGIN, "Content-Type": "application/octet-stream"})
        assert pr.status_code == 200, pr.text
    return client.post(f"/api/uploads/{up['id']}/finish", json={"caption": caption, "confirm": confirm}, headers={"Origin": ORIGIN})


@pytest.fixture
def clip_file(tmp_path):
    return media_fx.make_video(tmp_path / "clip.mp4", seconds=2.0)


class TestClipRoutes:
    def test_upload_list_play_delete(self, client, seeded, clip_file):
        login(client, seeded[1]["P-017"])
        r = _upload_clip(client, clip_file, caption="Knee catching")
        assert r.status_code == 201, r.text
        m = r.json()
        assert m["kind"] == "clip" and m["caption"] == "Knee catching" and m["duration"] >= 1.5 and "path" not in m and "sha256" not in m
        listing = client.get("/api/media").json()
        assert [x["id"] for x in listing["media"]] == [m["id"]] and listing["notice"]
        play = client.get(f"/api/media/{m['id']}")
        assert play.status_code == 200 and play.headers["content-type"] == "video/mp4" and play.headers["cache-control"] == "private, no-store"
        assert play.headers["content-security-policy"] == "sandbox" and play.headers["accept-ranges"] == "bytes"
        assert play.content == clip_file.read_bytes()
        ranged = client.get(f"/api/media/{m['id']}", headers={"Range": "bytes=0-99"})
        assert ranged.status_code == 206 and len(ranged.content) == 100
        assert client.delete(f"/api/media/{m['id']}", headers={"Origin": ORIGIN}).status_code == 200
        assert client.get(f"/api/media/{m['id']}").status_code == 404
        assert client.get("/api/media").json()["media"][0]["deleted"] is True
        assert client.get("/api/today").json()["clips"] == {"count": 1, "waiting": 0}

    def test_resume_reports_missing_parts(self, client, seeded, clip_file):
        login(client, seeded[1]["P-017"])
        data = clip_file.read_bytes()
        up = client.post("/api/uploads", json={"kind": "clip", "total_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                                "chunk_bytes": 1024}, headers={"Origin": ORIGIN}).json()
        client.put(f"/api/uploads/{up['id']}/parts/0", content=data[:1024], headers={"Origin": ORIGIN, "Content-Type": "application/octet-stream"})
        st = client.get(f"/api/uploads/{up['id']}").json()
        assert st["received"] == [0] and st["total_parts"] == up["total_parts"]
        assert client.post(f"/api/uploads/{up['id']}/finish", json={}, headers={"Origin": ORIGIN}).status_code == 409
        assert client.delete(f"/api/uploads/{up['id']}", headers={"Origin": ORIGIN}).status_code == 200
        assert client.get(f"/api/uploads/{up['id']}").status_code == 404

    def test_refusals(self, client, seeded, tmp_path):
        login(client, seeded[1]["P-017"])
        png = media_fx.make_png_named_mp4(tmp_path / "x.mp4")
        r = _upload_clip(client, png)
        assert r.status_code == 415 and r.json()["reason"] == "not_media"
        assert client.get("/api/media").json()["media"] == []
        big = client.post("/api/uploads", json={"kind": "clip", "total_bytes": 90 * 1024 * 1024, "sha256": "0" * 64}, headers={"Origin": ORIGIN})
        assert big.status_code == 400
        assert client.put("/api/uploads/not-an-id/parts/0", content=b"x", headers={"Origin": ORIGIN, "Content-Type": "application/octet-stream"}).status_code == 404
        assert client.put("/api/uploads/00000000-0000-4000-8000-000000000000/parts/0", content=b"x",
                          headers={"Origin": "https://evil.example", "Content-Type": "application/octet-stream"}).status_code == 403

    def test_caption_warning(self, client, seeded, clip_file):
        login(client, seeded[1]["P-017"])
        r = _upload_clip(client, clip_file, caption="Filmed by Jane Smith")
        assert r.status_code == 409 and r.json()["reasons"] == ["name"]
        assert client.get("/api/media").json()["media"] == []                    # nothing kept after the warning
        r = _upload_clip(client, clip_file, caption="Filmed by Jane Smith", confirm=True)
        assert r.status_code == 201 and r.json()["warned"] is True

    def test_other_patients_clip_is_not_found(self, client, seeded, clip_file):
        db, codes = seeded
        login(client, codes["P-017"])
        m = _upload_clip(client, clip_file).json()
        client.post("/api/logout", json={}, headers={"Origin": ORIGIN})
        login(client, codes["P-018"])
        assert client.get(f"/api/media/{m['id']}").status_code == 404
        assert client.delete(f"/api/media/{m['id']}", headers={"Origin": ORIGIN}).status_code == 404
        assert m["id"] not in client.get("/api/media").text
        assert client.get("/clip").status_code == 200 and "stored on the Limber" in client.get("/clip").text
