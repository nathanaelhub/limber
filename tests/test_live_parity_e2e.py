"""Feature 004 SC-001 — opt-in parity on a real clip: LiveSession versus the command-line video runner.

Needs the pose model and the sample clip, so it runs only with PTASSIST_E2E=1 (quickstart step 2).
Both paths use the same inference settings and the clip's frame rate, so any difference comes from
the per-frame engine and recording steps, which is what the two runners duplicate.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIP = REPO_ROOT / "videos" / "Squats.demo.video.mp4"
MODEL = REPO_ROOT / "models" / "yolo11m-pose.pt"

pytestmark = pytest.mark.skipif(
    os.environ.get("PTASSIST_E2E") != "1" or not CLIP.exists() or not MODEL.exists(),
    reason="set PTASSIST_E2E=1 with the model and sample clip present")


def _events(session):
    reps = [(r.rep_number, r.min_angle, r.max_angle, r.rom, r.duration_seconds, r.form_score, r.frame_num)
            for s in session.sets for r in s.reps]
    partials = [(p.min_angle, p.max_angle, p.rom, p.duration_seconds, p.reason)
                for s in session.sets for p in s.partial_reps]
    return reps, partials


def test_live_session_records_what_the_command_line_records(tmp_db, monkeypatch):
    import cv2
    from ultralytics import YOLO

    import analyze
    from src.live_session import LiveSession
    from src.ptlog.store import SessionStore

    monkeypatch.setenv("PTASSIST_DB", str(tmp_db))
    monkeypatch.chdir(REPO_ROOT)
    analyze.main(str(CLIP), exercise_name="squat", show_video=False)

    model = YOLO(str(MODEL))

    def infer(frame):
        results = model(frame, verbose=False)
        if results and results[0].keypoints is not None and len(results[0].keypoints) > 0:
            return results[0].keypoints.data[0].cpu().numpy()
        return None

    cap = cv2.VideoCapture(str(CLIP))
    fps = cap.get(cv2.CAP_PROP_FPS)
    store = SessionStore(tmp_db, check_same_thread=False).open()
    live = LiveSession(store, None, "squat", None, "Default", infer, fps=fps, draw=False)
    live.start()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        live.process(frame)
    cap.release()
    web = live.end()
    cli = store.load_session(web.id - 1)
    store.close()

    assert cli.source == "video" and web.source == "webcam"
    assert _events(web) == _events(cli)
    assert len(_events(web)[0]) > 0
    assert (web.total_reps, web.avg_rom, web.avg_form_score) == (cli.total_reps, cli.avg_rom, cli.avg_form_score)
