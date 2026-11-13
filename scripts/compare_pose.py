#!/usr/bin/env python3
"""Gate G2 (019) = G5 (020): browser pose (MoveNet Lightning) against the clinic model (YOLO11m-pose) on the same clips.

Each model's body points, one frame every 1/15 s, are replayed through the real engine (`LiveSession`, the path the
hosted demo uses), so the only difference is the pose model. Reports reps, range of motion, form score, partial
reps and form events per clip and exercise, beside the hand-counted reps.

    # 1. MoveNet points come from the browser (headless Chrome stepping each clip; see specs/019 research note).
    # 2. YOLO points are made here once and cached next to them:
    python scripts/compare_pose.py --points tests/fixtures/pose --videos videos --yolo models/yolo11m-pose.pt
    python scripts/compare_pose.py --points tests/fixtures/pose            # replay only, no YOLO needed
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# clip -> (exercise keys to measure, hand-counted full reps)
CLIPS = {
    "Squats.demo.video.mp4": (["squat"], 4),
    "Pushups.demo.video.mp4": (["pushup", "pushup_right"], 4),               # issue #24: the side matters
    "Legextension.demo.video.mp4": (["knee_extension", "knee_extension_right"], 3),   # issue #23: hand count 3
}
FPS = 15


def yolo_points(video: Path, weights: Path) -> dict:
    """YOLO body points at 15 frames per second, the most confident person in each frame."""
    import cv2
    from ultralytics import YOLO
    model = YOLO(str(weights))
    cap = cv2.VideoCapture(str(video))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames, i, next_t = [], 0, 0.0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        t = i / src_fps
        i += 1
        if t + 1e-9 < next_t:
            continue
        next_t += 1 / FPS
        result = model(img, verbose=False)[0]
        kp = result.keypoints
        if kp is None or kp.data.shape[0] == 0:
            frames.append(None)
            continue
        best = int(result.boxes.conf.argmax()) if result.boxes is not None and len(result.boxes) else 0
        frames.append([round(float(v), 2) for row in kp.data[best].tolist() for v in row])
    cap.release()
    return {"clip": video.name, "w": w, "h": h, "fps": FPS, "model": "yolo11m-pose", "frames": frames}


def replay(points: dict, exercise_key: str) -> dict:
    """Run the engine over the points with a 1/15 s clock, as the hosted video analysis will."""
    import numpy as np
    from src.live_session import LiveSession
    from src.portal import frames as pframes
    from src.ptlog.store import SessionStore

    start = datetime(2026, 1, 5, 9, 0)
    tick = {"i": 0}
    clock = lambda: start + timedelta(seconds=tick["i"] / FPS)            # noqa: E731
    current = {"kp": None}
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "g2.db", clock=clock).open()
        live = LiveSession(store, "unassigned", exercise_key, 10, "g2", lambda _f: current["kp"], fps=float(FPS),
                           draw=False, clock=clock, extras={"pose_model": points["model"]})
        live.start()
        dummy = np.zeros((1, 1, 3), dtype=np.uint8)
        for n, k in enumerate(points["frames"], 1):
            tick["i"] = n
            if k is None:
                current["kp"] = None
            else:
                kp, w, h = pframes.validate_frame({"k": k, "w": points["w"], "h": points["h"]})
                current["kp"] = pframes.to_engine_keypoints(kp, w, h)
            live.process(dummy, frame_num=n)
        session = live.end()
        partials = sum(len(s.partial_reps) for s in session.sets)
        form_events = sum(len(s.form_events) for s in session.sets)
        store.close()
    return {"reps": session.total_reps or 0, "rom": session.avg_rom, "form": session.avg_form_score,
            "partials": partials, "form_events": form_events}


def compare(points_dir: Path) -> list:
    rows = []
    for clip, (keys, hand) in CLIPS.items():
        for model in ("yolo11m-pose", "movenet-lightning-4"):
            suffix = "yolo" if model.startswith("yolo") else "movenet"
            path = points_dir / f"{clip}.{suffix}.json"
            if not path.is_file():
                continue
            points = json.loads(path.read_text())
            for key in keys:
                rows.append({"clip": clip, "exercise": key, "model": model, "hand_count": hand, **replay(points, key)})
    return rows


def table(rows: list) -> str:
    out = ["| Clip | Exercise | Model | Reps (hand count) | Avg ROM | Avg form | Partial reps | Form events |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        rom = "—" if r["rom"] is None else f"{r['rom']:.1f}°"
        form = "—" if r["form"] is None else f"{r['form']:.1f}"
        out.append(f"| {r['clip'].split('.')[0]} | {r['exercise']} | {r['model']} | {r['reps']} ({r['hand_count']}) | "
                   f"{rom} | {form} | {r['partials']} | {r['form_events']} |")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--points", type=Path, default=REPO / "tests" / "fixtures" / "pose")
    p.add_argument("--videos", type=Path, default=REPO / "videos")
    p.add_argument("--yolo", type=Path, help="YOLO weights: make and cache the YOLO points first")
    p.add_argument("--json", type=Path, help="Also write the rows as JSON")
    args = p.parse_args(argv)
    if args.yolo:
        for clip in CLIPS:
            video = args.videos / clip
            if video.is_file():
                (args.points / f"{clip}.yolo.json").write_text(json.dumps(yolo_points(video, args.yolo)))
    rows = compare(args.points)
    print(table(rows))
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
