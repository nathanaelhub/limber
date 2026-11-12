"""Feature 007 T026 — the session connection between the patient's browser and the service."""

import json
from datetime import date, timedelta

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from interfaces.patient_portal import create_app
from src.portal import access
from src.ptlog.store import SessionStore
from tests.fixtures.poses import keypoints_for_angle, rep_cycle

KEY = b"k" * 32
ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}


def frame(angle):
    return json.dumps({"type": "frame", "k": keypoints_for_angle(angle).reshape(-1).tolist(), "w": 640, "h": 480})


@pytest.fixture
def portal(tmp_db):
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-018")
        s.assign_program("P-017", "custom", "Knee Home Program", ["knee_extension", "squat"], 3,
                         date.today() - timedelta(days=7))
        codes = {p: access.issue_code(s, KEY, p)[0] for p in ("P-017", "P-018")}
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN], frame_rate_cap=100000)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, tmp_db, codes


def login(client, code):
    assert client.post("/api/login", json={"code": code}, headers=HEADERS).status_code == 200


def latest(db, patient="P-017"):
    with SessionStore(db).open() as s:
        rows = s.list_sessions(patient)
        return s.load_session(rows[0].id) if rows else None


def drain_until(ws, wanted):
    while True:
        msg = ws.receive_json()
        if msg["type"] == wanted:
            return msg


class TestHandshake:
    def test_needs_a_sign_in(self, portal):
        client, _, _ = portal
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/session", headers=HEADERS):
                pass

    def test_needs_an_allowed_origin(self, portal):
        client, _, codes = portal
        login(client, codes["P-017"])
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/session", headers={"Origin": "https://evil.example"}):
                pass


class TestSession:
    def test_reps_next_and_stop(self, portal):
        client, db, codes = portal
        login(client, codes["P-017"])
        with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
            ws.send_text(json.dumps({"type": "start", "pose_model": "movenet-lightning-4"}))
            state = ws.receive_json()
            assert (state["type"], state["exercise"], state["rep_count"], state["total"]) == ("state", "Knee Extension", 0, 2)
            for a in rep_cycle() * 2:
                ws.send_text(frame(a))
            ws.send_text(json.dumps({"type": "next"}))
            state = drain_until_exercise(ws, "Squat")
            assert state["rep_count"] == 0 and state["index"] == 2
            for a in rep_cycle():
                ws.send_text(frame(a))
            ws.send_text(json.dumps({"type": "stop"}))
            ended = drain_until(ws, "ended")
            assert ended["status"] == "completed" and ended["summary"]["total_reps"] == 3
        s = latest(db)
        assert s.status == "completed" and s.source_extras["origin"] == "portal"
        assert [(x.exercise_key, len(x.reps)) for x in s.sets] == [("knee_extension", 2), ("squat", 1)]

    def test_state_is_not_echoed_for_every_frame(self, portal):
        client, _, codes = portal
        login(client, codes["P-017"])
        with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
            ws.send_text(json.dumps({"type": "start"}))
            ws.receive_json()
            for _ in range(60):
                ws.send_text(frame(172.0))                         # nothing changes while standing still
            ws.send_text(json.dumps({"type": "stop"}))
            seen = 0
            while ws.receive_json()["type"] != "ended":
                seen += 1
            assert seen < 30

    def test_abrupt_close_interrupts_and_keeps_the_reps(self, portal):
        client, db, codes = portal
        login(client, codes["P-017"])
        with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
            ws.send_text(json.dumps({"type": "start"}))
            ws.receive_json()
            for a in rep_cycle() * 2:
                ws.send_text(frame(a))
            ws.send_text(json.dumps({"type": "next"}))
            drain_until_exercise(ws, "Squat")                      # everything before this was processed
        s = latest(db)
        assert (s.status, s.interrupted_reason, len(s.sets[0].reps)) == ("interrupted", "portal_disconnected", 2)

    def test_second_device_is_refused(self, portal):
        client, _, codes = portal
        login(client, codes["P-017"])
        with client.websocket_connect("/ws/session", headers=HEADERS) as first:
            first.send_text(json.dumps({"type": "start"}))
            first.receive_json()
            with client.websocket_connect("/ws/session", headers=HEADERS) as second:
                second.send_text(json.dumps({"type": "start"}))
                refused = second.receive_json()
                assert refused["type"] == "refused" and refused["reason"] == "second_device" and "another device" in refused["message"]
            first.send_text(json.dumps({"type": "stop"}))
            drain_until(first, "ended")

    def test_no_program_is_refused(self, portal):
        client, _, codes = portal
        login(client, codes["P-018"])
        with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
            ws.send_text(json.dumps({"type": "start"}))
            assert ws.receive_json()["reason"] == "no_program"

    def test_ten_bad_messages_close_the_connection(self, portal):
        client, db, codes = portal
        login(client, codes["P-017"])
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
                ws.send_text(json.dumps({"type": "start"}))
                ws.receive_json()
                for _ in range(10):
                    ws.send_text(json.dumps({"type": "frame", "k": [1, 2, 3], "w": 640, "h": 480}))
                while True:
                    ws.receive_json()
        assert closed.value.code == 1008
        with SessionStore(db).open() as s:
            events = [(a.event, a.detail) for a in s.portal_audit_list("P-017")]
        assert ("live_refused", "bad_frames") in events
        assert latest(db).status == "interrupted"

    def test_revoking_the_code_ends_the_session(self, portal):
        client, db, codes = portal
        login(client, codes["P-017"])
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
                ws.send_text(json.dumps({"type": "start"}))
                ws.receive_json()
                with SessionStore(db).open() as s:
                    access.revoke_code(s, "P-017")
                for a in rep_cycle() * 40:                         # the sign-in is re-checked as frames arrive
                    ws.send_text(frame(a))
                while True:
                    ws.receive_json()
        s = latest(db)
        assert (s.status, s.interrupted_reason) == ("interrupted", "access_revoked")


def drain_until_exercise(ws, name):
    while True:
        msg = ws.receive_json()
        if msg["type"] == "state" and msg["exercise"] == name:
            return msg


# ---- feature 020 slice F (T034): segments on hosts that cut connections (Vercel: 300 s) ---------------------------

@pytest.fixture
def segmented(tmp_db):
    from tests.conftest import FakeClock
    clock = FakeClock(step=0.0)
    from datetime import datetime
    clock._now = datetime.now()
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-018")
        for p in ("P-017", "P-018"):
            s.assign_program(p, "custom", "Knee Home Program", ["knee_extension", "squat"], 3,
                             date.today() - timedelta(days=7))
        codes = {p: access.issue_code(s, KEY, p)[0] for p in ("P-017", "P-018")}
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN], frame_rate_cap=100000, clock=clock,
                     ws_segment_seconds=60)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, tmp_db, codes, clock


def test_a_session_continues_across_segments(segmented):
    client, db, codes, clock = segmented
    login(client, codes["P-017"])
    with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
        ws.send_text(json.dumps({"type": "start"}))
        assert ws.receive_json()["rep_count"] == 0
        for a in rep_cycle() * 2:
            ws.send_text(frame(a))
        while ws.receive_json().get("rep_count") != 2:            # let the server catch up before time moves
            pass
        clock.advance(61)                                          # the host's limit is near
        for a in rep_cycle():                                      # the segment ends as this rep completes
            ws.send_text(frame(a))
        segment = drain_until(ws, "segment")
    assert latest(db).status == "running"                          # nothing ended: the lease holds it
    with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
        ws.send_text(json.dumps({"type": "resume", "session_id": segment["session_id"]}))
        state = drain_until(ws, "state")
        assert (state["exercise"], state["rep_count"], state["target_reps"]) == ("Knee Extension", 3, 10)
        for a in rep_cycle():
            ws.send_text(frame(a))
        ws.send_text(json.dumps({"type": "stop"}))
        ended = drain_until(ws, "ended")
    assert ended["status"] == "completed" and ended["summary"]["total_reps"] == 4
    with SessionStore(db).open() as s:
        assert len(s.list_sessions("P-017")) == 1                  # one session, not two
    stored = latest(db)
    assert stored.id == segment["session_id"]
    assert [(x.exercise_key, len(x.reps)) for x in stored.sets] == [("knee_extension", 3), ("knee_extension", 1)]


def test_only_your_own_running_session_can_be_resumed(segmented):
    client, db, codes, clock = segmented
    login(client, codes["P-017"])
    with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
        ws.send_text(json.dumps({"type": "start"}))
        ws.receive_json()
        ws.send_text(json.dumps({"type": "stop"}))
        ended_id = latest(db).id
        drain_until(ws, "ended")
    with client.websocket_connect("/ws/session", headers=HEADERS) as ws:   # an ended session
        ws.send_text(json.dumps({"type": "resume", "session_id": ended_id}))
        assert drain_until(ws, "refused")["reason"] == "not_resumable"
    login(client, codes["P-018"])
    with client.websocket_connect("/ws/session", headers=HEADERS) as ws:   # P-018 reaching for P-017's
        ws.send_text(json.dumps({"type": "resume", "session_id": ended_id}))
        assert drain_until(ws, "refused")["reason"] == "not_resumable"


def test_without_a_segment_limit_nothing_changes(portal):
    """Local installs: no `segment` message, sessions run to the usual 60-minute limit."""
    client, _, codes = portal
    login(client, codes["P-017"])
    with client.websocket_connect("/ws/session", headers=HEADERS) as ws:
        ws.send_text(json.dumps({"type": "start"}))
        assert ws.receive_json()["type"] == "state"
        ws.send_text(json.dumps({"type": "stop"}))
        assert drain_until(ws, "ended")["status"] == "completed"
