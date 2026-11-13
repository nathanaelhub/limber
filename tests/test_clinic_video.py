"""Feature 019 slice 6 (T028, FR-014): video analysis on browser pose. The same MoveNet points as gate G2 must give
the same counts here; the session is a video measured by browser pose, with its own origin; the camera-angle note
appears when a set has more partial reps than full ones (owner's G2 decisions)."""

import json
from pathlib import Path

import pytest

from src.clinic import video
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in

POSE = Path(__file__).resolve().parent / "fixtures" / "pose"


def points(clip):
    d = json.loads((POSE / f"{clip}.demo.video.mp4.movenet.json").read_text())
    return {"w": d["w"], "h": d["h"], "pose_model": d["model"], "frames": d["frames"]}


@pytest.fixture
def store(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        yield s


def test_the_squats_count_as_in_g2(store):
    result = video.analyze_points(store, "P-001", "squat", 10, points("Squats"), label="Squats, side view")
    assert result["reps"] == 4 and result["warnings"] == []
    s = store.load_session(result["session_id"])
    assert s.source == "video" and s.status == "completed"
    assert s.source_extras["pose_source"] == "browser" and s.source_extras["pose_model"] == "movenet-lightning-4"
    assert store.list_sessions("P-001")[0].origin == "browser"
    assert s.duration_seconds == pytest.approx(len(points("Squats")["frames"]) / 15, abs=0.2)   # the clip's length


def test_the_angled_leg_extension_gets_the_camera_note(store):
    result = video.analyze_points(store, "P-001", "knee_extension", None, points("Legextension"))
    assert result["reps"] == 0 and any("camera angle" in w for w in result["warnings"])


def test_refusals(store):
    with pytest.raises(video.VideoRefused):
        video.analyze_points(store, "P-001", "not_an_exercise", None, points("Squats"))
    with pytest.raises(video.VideoRefused):
        video.analyze_points(store, "P-001", "squat", None, {"w": 640, "h": 480, "frames": [[1, 2, 3]] * 20})
    with pytest.raises(video.VideoRefused):
        video.analyze_points(store, "P-001", "squat", None, {"w": 640, "h": 480, "frames": []})
    sid = store.start_session("P-001", "webcam", "0", {"pid": 0})
    with pytest.raises(video.VideoRefused, match="being recorded"):
        video.analyze_points(store, "P-001", "squat", None, points("Squats"))
    assert store.load_session(sid).status == "running"              # the running session is left alone


def test_the_label_never_carries_a_file_name_character(store):
    assert video.clean_label("<script>Jane_Doe.mp4") == "scriptJane_Doe.mp4"[:60]
    assert video.clean_label(None) == "clip"


def test_the_page_and_the_route(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        page = c.get("/therapist/video").text
        assert "data-video" in page and "/therapist/static/vendor/pose-detection.min.js" in page
        from tests.test_clinic_static import _checked
        _checked(page, "video")
        r = c.post("/therapist/api/video", json={"patient_id": "P-001", "exercise": "squat", "target_reps": 10,
                                                 "label": "Squats", **points("Squats")}, headers=H)
        assert r.status_code == 201 and r.json()["redirect"].startswith("/therapist/logs/")
        assert c.get(r.json()["redirect"]).status_code == 200
        assert c.post("/therapist/api/video", json={"patient_id": "P-002", "exercise": "squat", **points("Squats")},
                      headers=H).status_code == 404                          # rivera's patient
        r = c.post("/therapist/api/video", content=b"x" * (video.MAX_BODY + 1),
                   headers={**H, "Content-Type": "application/json"})
        assert r.status_code == 413


def test_how_it_works_is_real(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        page = c.get("/therapist/how-it-works").text
        assert "Range, 40 points" in page and "Smoothness, 30 points" in page and "Balance, 30 points" in page
        main = page.split("<main", 1)[1]
        assert "placeholder" not in main and "<img" not in main and "MoveNet Lightning" in main
        from tests.test_clinic_static import _checked
        _checked(page, "how")
