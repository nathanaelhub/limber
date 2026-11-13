"""Feature 019 slice 7 (T031, FR-013): the therapist's live session. Driven with the G2 squat points (MoveNet, 15
a second), it counts like video analysis; it switches, resets and changes target; it resumes across connections;
and the socket admits only a signed-in therapist, for a patient on their caseload."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from src.clinic import live
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in
from tests.test_clinic_records import Clock

POSE = Path(__file__).resolve().parent / "fixtures" / "pose" / "Squats.demo.video.mp4.movenet.json"


def frames():
    d = json.loads(POSE.read_text())
    return [{"type": "frame", "k": k, "w": d["w"], "h": d["h"]} for k in d["frames"]]


@pytest.fixture
def world(tmp_db):
    clock = Clock(datetime(2026, 3, 23, 9, 0))
    seed(tmp_db, clock)
    return tmp_db, clock


def feed(session, clock, messages):
    state = None
    for m in messages:
        clock.set(clock() + timedelta(seconds=1 / 15))
        state = session.handle_frame(m) or state
    return state


def test_it_counts_the_squats_and_records_a_browser_session(world):
    db, clock = world
    s = live.ClinicLiveSession.start(db, "P-001", "squat", 10, clock=clock)
    state = feed(s, clock, frames())
    assert state["rep_count"] == 4 and state["exercise_key"] == "squat" and state["target_reps"] == 10
    result = s.stop()
    assert result["type"] == "ended" and result["summary"]["total_reps"] == 4
    with SessionStore(db, clock=clock).open() as store:
        row = store.list_sessions("P-001")[0]
        assert row.origin == "browser" and row.source == "webcam"


def test_switch_reset_and_target(world):
    db, clock = world
    s = live.ClinicLiveSession.start(db, "P-001", "squat", None, clock=clock)
    feed(s, clock, frames())
    assert s.reset()["rep_count"] == 0
    assert s.set_target(7)["target_reps"] == 7 and s.set_target(0)["target_reps"] == 7    # 0 is ignored
    switched = s.switch("knee_extension")
    assert switched["exercise_key"] == "knee_extension" and switched["rep_count"] == 0
    assert s.switch("not_an_exercise")["exercise_key"] == "knee_extension"
    s.stop()


def test_refusals(world):
    db, clock = world
    with pytest.raises(live.LiveRefused):
        live.ClinicLiveSession.start(db, "P-001", "nope", None, clock=clock)
    first = live.ClinicLiveSession.start(db, "P-001", "squat", None, clock=clock)
    with pytest.raises(live.LiveRefused) as refused:
        live.ClinicLiveSession.start(db, "P-001", "squat", None, clock=clock)
    assert refused.value.reason == "running"
    first.stop()


def test_a_cut_connection_resumes_and_keeps_the_count(world):
    db, clock = world
    s = live.ClinicLiveSession.start(db, "P-001", "squat", 10, clock=clock)
    half = frames()
    feed(s, clock, half[:60])
    before = s.state()["rep_count"]
    assert s.detach()["type"] == "segment"
    again = live.ClinicLiveSession.resume(db, "P-001", s.session_id, clock=clock)
    assert again.state()["rep_count"] == before and again.state()["target_reps"] == 10
    feed(again, clock, half[60:])
    assert again.stop()["summary"]["total_reps"] >= before
    with pytest.raises(live.LiveRefused):
        live.ClinicLiveSession.resume(db, "P-002", s.session_id, clock=clock)


class Ticking(Clock):
    """Moves on 0.1 s each time it is read: frames sent all at once still arrive spaced, as a real browser's
    15-a-second frames do, so the rate cap does not drop them."""

    def __call__(self):
        self.now = self.now + timedelta(seconds=0.1)
        return self.now


def test_the_socket(world):
    db, _ = world
    clock = Ticking(datetime(2026, 3, 23, 9, 0))
    with client(db, clock) as c:
        with pytest.raises(WebSocketDisconnect):                      # not signed in
            with c.websocket_connect("/therapist/ws/live", headers=H) as ws:
                ws.receive_json()
        sign_in(c)
        page = c.get("/therapist/live?patient=P-001").text
        assert "data-live-setup" in page and "/therapist/static/vendor/pose-detection.min.js" in page
        from tests.test_clinic_static import _checked
        _checked(page, "live")
        with c.websocket_connect("/therapist/ws/live", headers=H) as ws:
            ws.send_text(json.dumps({"type": "start", "patient_id": "P-002", "exercise": "squat"}))
            assert ws.receive_json()["reason"] == "not_found"            # rivera's patient
        with c.websocket_connect("/therapist/ws/live", headers=H) as ws:
            ws.send_text(json.dumps({"type": "start", "patient_id": "P-001", "exercise": "squat", "target_reps": 10}))
            assert ws.receive_json()["type"] == "state"
            for m in frames():
                ws.send_text(json.dumps(m))
            ws.send_text(json.dumps({"type": "stop"}))
            message = ws.receive_json()
            while message["type"] != "ended":
                message = ws.receive_json()
            assert message["summary"]["total_reps"] == 4
        with pytest.raises(WebSocketDisconnect):                      # another site's page
            with c.websocket_connect("/therapist/ws/live", headers={"Origin": "https://elsewhere.example"}) as ws:
                ws.receive_json()
