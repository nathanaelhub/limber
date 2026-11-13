"""Video analysis on browser pose (feature 019 slice 6, FR-014; owner's G2 decision, 13 November 2026).

The therapist's browser plays the clip, finds the body points with MoveNet every 1/15 s, and sends only those
numbers in one request: the video never leaves the browser. Here the points go through the engine exactly as the
G2 comparison replayed them (`LiveSession`, 15 frames a second, a 1/15 s clock), so the session's duration is the
clip's and repeated form messages are spaced as in real time. The session is recorded as a video, measured by
browser pose, with its own origin so its range of motion is never compared with the clinic model's.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Dict, List, Optional

from src.ptlog.models import PTLogError
from src.ptlog.store import SessionStore

FPS = 15
MAX_FRAMES = FPS * 60 * 15            # a 15-minute clip; about 4 MB in the compact form the page sends
MAX_BODY = 4_400_000                  # under Vercel's 4.5 MB request limit, and the same cap locally
MAX_BAD_SHARE = 0.10                  # more than this share of malformed frames refuses the whole request
DEFAULT_MODEL = "movenet-lightning-4"
CAMERA_NOTE = ("The camera angle may have hidden the movement: this set has more partial reps than full ones. "
               "Check the clip before relying on the count.")


class VideoRefused(PTLogError):
    pass


def exercises(config_path: str = "config.yaml") -> List[tuple]:
    """(key, name) for every exercise the engine can count, in the config's order."""
    from analyze import load_config
    return [(key, cfg.name) for key, cfg in load_config(config_path).items()]


def clean_label(label) -> str:
    """A short description of the clip, never its file name (a name may identify the patient)."""
    text = label if isinstance(label, str) else ""
    text = re.sub(r"[^\w .,()-]", "", text)[:60].strip()
    return text or "clip"


def frames_from(payload: Any) -> tuple:
    """(frames, width, height, model) from the page's request, checked: 51 numbers or null per frame."""
    from src.portal import frames as pframes
    if not isinstance(payload, dict):
        raise VideoRefused("Send the body points as JSON.")
    raw, w, h = payload.get("frames"), payload.get("w"), payload.get("h")
    if not isinstance(raw, list) or not raw:
        raise VideoRefused("No frames were sent. Choose a clip and try again.")
    if len(raw) > MAX_FRAMES:
        raise VideoRefused("This clip is longer than 15 minutes. Trim it and try again.")
    out, bad = [], 0
    for k in raw:
        if k is None:
            out.append(None)
            continue
        try:
            kp, fw, fh = pframes.validate_frame({"k": k, "w": w, "h": h})
            out.append(pframes.to_engine_keypoints(kp, fw, fh))
        except pframes.FrameError:
            bad += 1
            out.append(None)
    if bad > MAX_BAD_SHARE * len(raw):
        raise VideoRefused("The body points from this clip could not be read. Try the clip again.")
    model = payload.get("pose_model")
    model = model[:40] if isinstance(model, str) and model else DEFAULT_MODEL
    return out, model


def analyze_points(store: SessionStore, patient_id: str, exercise_key: str, target_reps: Optional[int],
                   payload: Any, label: Any = None) -> Dict[str, Any]:
    """Count and score the clip; record it under the patient. The caller has checked the patient is on the
    caseload. Refuses an archived plan, a session already running for the patient, or an unknown exercise."""
    import numpy as np
    from src.live_session import LiveSession
    if exercise_key not in dict(exercises()):
        raise VideoRefused("Choose an exercise.")
    if store.current_plan(patient_id) is None and store.plans(patient_id):
        raise VideoRefused("This patient's plan of care is archived, so nothing new can be recorded.")
    if store.conn.execute("SELECT 1 FROM sessions WHERE patient_id = ? AND status = 'running'",
                          (patient_id,)).fetchone():
        raise VideoRefused("A session is being recorded for this patient right now. Try again when it ends.")
    points, model = frames_from(payload)
    target = target_reps if isinstance(target_reps, int) and 1 <= target_reps <= 100 else None

    start = store.clock()
    tick = {"i": 0}

    def clock():
        return start + timedelta(seconds=tick["i"] / FPS)

    current = {"kp": None}
    real_clock = store.clock
    store.clock = clock                      # the session's times follow the clip, not the request
    try:
        live = LiveSession(store, patient_id, exercise_key, target, clean_label(label), lambda _f: current["kp"],
                           fps=float(FPS), draw=False, clock=clock, source="video",
                           extras={"pose_model": model, "pose_source": "browser", "fps_nominal": FPS,
                                   "origin": "clinic-video", "camera_id": "browser"})
        live.recorder.sample_flush_seconds = 30.0     # one write every 30 clip-seconds, not every second
        session_id = live.start()
        dummy = np.zeros((1, 1, 3), dtype=np.uint8)
        for n, kp in enumerate(points, 1):
            tick["i"] = n
            current["kp"] = kp
            live.process(dummy, frame_num=n)
        session = live.end()
    finally:
        store.clock = real_clock
    return {"session_id": session_id, "reps": session.total_reps or 0, "rom": session.avg_rom,
            "form": session.avg_form_score, "warnings": camera_warnings(session)}


def camera_warnings(session) -> List[str]:
    """The owner's G2 decision: a set with more partial reps than full ones gets the camera-angle note. Applies to
    every session, whichever model measured it."""
    out = []
    for s in session.sets:
        if len(s.partial_reps) > len(s.reps):
            out.append(f"{s.exercise_name}: {CAMERA_NOTE}")
    return out


# ----------------------------------------------------------------------------- local installs: the clinic model

YOLO_WEIGHTS = "models/yolo11m-pose.pt"
YOLO_MAX_BYTES = 500 * 1024 * 1024    # a clip sent to this computer (never on the hosted demo)


def yolo_available(weights: str = YOLO_WEIGHTS) -> bool:
    """Owner's G2 decision: a local install with the clinic model keeps analysing video with it, so its results stay
    comparable with past ones. Never on the hosted demo, which can't run it and never receives a video."""
    import importlib.util
    from pathlib import Path
    from src.ptlog import backend
    return (not backend.hosted() and Path(weights).is_file()
            and importlib.util.find_spec("ultralytics") is not None)


def analyze_with_yolo(store: SessionStore, db_path, patient_id: str, exercise_key: str, data: bytes,
                      label: Any = None, weights: str = YOLO_WEIGHTS) -> Dict[str, Any]:
    """Run the clinic model over an uploaded clip, as video analysis always has locally, and record it. The clip is
    written to a temporary file and deleted afterwards; only the measurements are kept."""
    import os
    import tempfile
    if exercise_key not in dict(exercises()):
        raise VideoRefused("Choose an exercise.")
    if store.current_plan(patient_id) is None and store.plans(patient_id):
        raise VideoRefused("This patient's plan of care is archived, so nothing new can be recorded.")
    if store.conn.execute("SELECT 1 FROM sessions WHERE patient_id = ? AND status = 'running'",
                          (patient_id,)).fetchone():
        raise VideoRefused("A session is being recorded for this patient right now. Try again when it ends.")
    if not data:
        raise VideoRefused("Choose a clip first.")
    before = {r.id for r in store.list_sessions(patient_id)}
    fd, path = tempfile.mkstemp(suffix=".mp4")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        run_yolo(path, exercise_key, patient_id, db_path, clean_label(label), weights)
    finally:
        os.unlink(path)
    new = [r for r in store.list_sessions(patient_id) if r.id not in before]
    if not new:
        raise VideoRefused("The clip could not be analysed. Try another clip or the browser option.")
    session = store.load_session(new[0].id)
    return {"session_id": session.id, "reps": session.total_reps or 0, "rom": session.avg_rom,
            "form": session.avg_form_score, "warnings": camera_warnings(session)}


def run_yolo(path: str, exercise_key: str, patient_id: str, db_path, label: str, weights: str) -> None:
    import analyze
    analyze.main(path, exercise_name=exercise_key, output_path=None, model_path=weights, show_video=False,
                 patient_id=patient_id, db_path=db_path, source_ref=label)
