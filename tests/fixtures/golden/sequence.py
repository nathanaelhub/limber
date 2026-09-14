"""T008 — the fixed synthetic session used for legacy-format golden files and parity tests.

The same SEQUENCE drives (a) the legacy writers once, to produce the golden files, and
(b) the canonical store + recorder in tests, whose exports must match those files exactly.
Everything here is synthetic; no patient data.
"""

from datetime import datetime, timedelta

PATIENT_ID = "P-001"
SOURCE = "webcam"
CAMERA_ID = 0
IMGSZ = 320
FRAME_SKIP = 1
START = datetime(2026, 3, 23, 9, 15, 0, 0)

SETS = {
    "knee_extension": dict(exercise_key="knee_extension", exercise_name="Knee Extension",
                           side="left", target_reps=10, up_angle=170.0, down_angle=90.0),
    "squat": dict(exercise_key="squat", exercise_name="Squat",
                  side="bilateral", target_reps=10, up_angle=170.0, down_angle=90.0),
}

# Each step is (kind, payload). Kinds: sample, rep, partial, form, switch, reset, end.
# frame numbers are monotonic; samples land on multiples of 15.
SEQUENCE = [
    ("sample", dict(frame_num=15, angle=92.0, state="down", rep_count=0)),
    ("sample", dict(frame_num=30, angle=130.5, state="idle", rep_count=0)),
    ("sample", dict(frame_num=45, angle=168.9, state="up", rep_count=0)),
    ("rep", dict(frame_num=60, rep_number=1, min_angle=10.2, max_angle=88.6, rom=78.4,
                 form_score=95.0, duration_seconds=3.1)),
    ("sample", dict(frame_num=75, angle=91.2, state="down", rep_count=1)),
    ("rep", dict(frame_num=120, rep_number=2, min_angle=9.8, max_angle=88.9, rom=79.1,
                 form_score=94.0, duration_seconds=3.0)),
    ("partial", dict(frame_num=150, reason="reversed_early", min_angle=95.0, max_angle=135.2,
                     rom=40.2, duration_seconds=1.3)),
    ("form", dict(frame_num=165, status="warning", priority="WARNING",
                  message="Keep your back straight against the chair", body_part="trunk")),
    ("rep", dict(frame_num=180, rep_number=3, min_angle=11.0, max_angle=88.8, rom=77.8,
                 form_score=93.0, duration_seconds=3.2)),
    ("switch", dict(frame_num=200, to="squat",
                    interrupted_partial=dict(min_angle=100.0, max_angle=140.0, rom=40.0,
                                             duration_seconds=0.8))),
    ("sample", dict(frame_num=210, angle=172.0, state="up", rep_count=0)),
    ("rep", dict(frame_num=240, rep_number=1, min_angle=88.0, max_angle=171.0, rom=83.0,
                 form_score=88.0, duration_seconds=2.4)),
    ("rep", dict(frame_num=300, rep_number=2, min_angle=87.5, max_angle=170.5, rom=83.0,
                 form_score=86.0, duration_seconds=2.5)),
    ("reset", dict(frame_num=320, rep_count_at_reset=2)),
    ("rep", dict(frame_num=380, rep_number=1, min_angle=89.0, max_angle=170.0, rom=81.0,
                 form_score=90.0, duration_seconds=2.6)),
    ("end", dict(frame_num=400)),
]

ALL_REPS = [p for k, p in SEQUENCE if k == "rep"]


def expected_summary() -> dict:
    """Session-level summary the store must compute from SEQUENCE."""
    n = len(ALL_REPS)
    return {
        "total_reps": n,
        "avg_form_score": round(sum(r["form_score"] for r in ALL_REPS) / n, 1),
        "avg_rom": round(sum(r["rom"] for r in ALL_REPS) / n, 1),
    }


def ts_for(frame_num: int) -> datetime:
    """Timestamp of a step: session start plus frame_num / 30 seconds (30 fps)."""
    return START + timedelta(seconds=frame_num / 30.0)


class FixedClock:
    """Clock that returns one fixed timestamp until `set()` is called.

    Used by both the golden generator (patched over the `datetime` name in the legacy
    modules) and the parity tests (passed to SessionStore/SessionRecorder), so every
    legacy line and every stored event carry the same timestamp for the same step.
    """

    def __init__(self, start: datetime = START):
        self._now = start

    def set(self, dt: datetime) -> None:
        self._now = dt

    def __call__(self) -> datetime:
        return self._now

    def now(self, tz=None) -> datetime:  # datetime.now() stand-in
        return self._now

    def __getattr__(self, name):  # strptime, fromisoformat, ... fall through to datetime
        return getattr(datetime, name)


def set_reps() -> dict:
    """Reps grouped by exercise set key, in SEQUENCE order."""
    groups, current = {"knee_extension": []}, "knee_extension"
    for kind, payload in SEQUENCE:
        if kind == "switch":
            current = payload["to"]
            groups.setdefault(current, [])
        elif kind == "rep":
            groups[current].append(payload)
    return groups
