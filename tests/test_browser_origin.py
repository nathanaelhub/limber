"""019 G2 decision (13 November 2026): sessions measured by browser pose in the clinic get their own measurement
origin, `browser`, so their range of motion is never compared with the clinic model's (as home already is)."""

from types import SimpleNamespace

from src.ptlog import origin
from src.ptlog.store import SessionStore


def session(source="video", extras=None):
    return SimpleNamespace(source=source, source_extras=extras)


def test_the_origins():
    assert origin.capture_origin(session(extras={"pose_source": "browser", "pose_model": "movenet"})) == origin.BROWSER
    assert origin.capture_origin(session(extras={"origin": "portal", "pose_source": "browser"})) == origin.HOME
    assert origin.capture_origin(session(extras={"pose_model": "yolo"})) == origin.CLINIC
    assert origin.capture_origin(session(source="diary")) == origin.DIARY
    assert origin.BROWSER in origin.MEASURED_ORIGINS


def test_the_session_list_says_browser(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-001")
        sid = s.start_session("P-001", "video", "clip", {"pose_source": "browser", "pose_model": "movenet-lightning-4"})
        s.end_session(sid)
        assert s.list_sessions("P-001")[0].origin == "browser"
