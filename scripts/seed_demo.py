"""Build a simulated caseload for demos and manual testing.

    .venv/bin/python scripts/seed_demo.py                 # writes data/demo.db (replaced if present)
    PTASSIST_DB=data/demo.db streamlit run interfaces/app.py

Everything is invented. Patients have pseudonymous IDs and clinical labels only, never names.
The real record (data/ptassist.db) is never touched: the script refuses to write to it.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.ptlog.models import ExerciseSetInfo, FormEvent, PartialRepEvent, RepEvent  # noqa: E402
from src.ptlog.store import SessionStore  # noqa: E402

EXERCISES = {  # display name -> (key, up angle, down angle, side)
    "Knee Extension": ("knee_extension", 170.0, 90.0, "left"),
    "Squat": ("squat", 170.0, 90.0, "bilateral"),
    "Partial Squat": ("partial_squat", 170.0, 120.0, "bilateral"),
    "Shoulder Flexion": ("shoulder_flexion", 170.0, 20.0, "left"),
    "Hip Abduction": ("hip_abduction", 45.0, 10.0, "left"),
    "Push-Up": ("pushup", 170.0, 90.0, "left"),
    "Elbow Flexion": ("elbow_flexion", 40.0, 160.0, "left"),
}
WARNINGS = ["Keep knee aligned over toes", "Trunk leaning forward", "Shoulders uneven", "Slow the lowering phase"]


class Clock:
    def __init__(self):
        self.now = datetime.now()

    def __call__(self):
        return self.now


def record(store, clock, rng, pid, name, days_ago, form, rom, reps=10, target=10, partials=0,
           warnings=0, stop=False, hour=9, source="webcam", interrupted=False):
    start = (datetime.now() - timedelta(days=days_ago)).replace(hour=hour, minute=rng.choice((0, 15, 30, 45)),
                                                                 second=0, microsecond=0)
    if start > datetime.now():
        start = datetime.now() - timedelta(hours=2)
    clock.now = start
    key, up, down, side = EXERCISES[name]
    extras = {"camera_id": 0, "imgsz": 320, "frame_skip": 1} if source == "webcam" else None
    sid = store.start_session(pid, source, "0" if source == "webcam" else "home_clip.mp4", extras)
    set_id = store.open_set(sid, ExerciseSetInfo(key, name, side, target, up, down))
    t = start
    for n in range(1, reps + 1):
        t += timedelta(seconds=rng.uniform(3.5, 5.0))
        r = max(5.0, rom + rng.uniform(-1.2, 1.2))
        low = min(up, down)
        store.add_rep(set_id, RepEvent(n, round(low, 1), round(low + r, 1), round(r, 1), round(rng.uniform(2.1, 3.2), 2),
                                       round(min(100.0, max(0.0, form + rng.uniform(-2.5, 2.5))), 1), t.isoformat(), 60 * n))
    for _ in range(partials):
        t += timedelta(seconds=3)
        store.add_partial_rep(set_id, PartialRepEvent("reversed_early", 130.0, 165.0, 35.0, 1.4, t.isoformat(), 0))
    for i in range(warnings):
        store.add_form_event(set_id, FormEvent("warning", "warning", rng.choice(WARNINGS),
                                               (start + timedelta(seconds=15 + 20 * i)).isoformat(), 300 + 600 * i, "trunk"))
    if stop:
        store.add_form_event(set_id, FormEvent("stop", "stop", "Knee collapsing inward: stop and reset",
                                               (start + timedelta(seconds=30)).isoformat(), 900, "knee"))
    clock.now = t + timedelta(seconds=6)
    if not interrupted:
        store.end_session(sid)
    return sid


def ramp(a, b, n):
    return [a + (b - a) * i / max(1, n - 1) for i in range(n)]


def build(db_path: Path, seed: int = 7) -> None:
    rng = random.Random(seed)
    clock = Clock()
    today = date.today()
    with SessionStore(db_path, clock=clock).open() as s:

        def review_all(pid, step="continue", leave=0):
            rows = s.list_sessions(pid)                       # newest first
            for row in rows[leave:]:
                s.set_review(row.id, step if row.id % 4 else "progress")

        # P-017: post-op knee. Good early progress, knee ROM slipped this week; squat stuck under target.
        s.add_patient("P-017", label="Post-op knee, week 6")
        days = [40, 37, 34, 30, 27, 23, 20, 16, 12, 9, 6, 2]
        knee_rom = ramp(62, 86, 9) + [85, 87, 80]
        for d, rom, form in zip(days, knee_rom, ramp(78, 89, 11) + [85]):
            record(s, clock, rng, "P-017", "Knee Extension", d, form, rom, warnings=1 if d == 2 else 0)
            record(s, clock, rng, "P-017", "Squat", d, 82, 92 + (40 - d) * 0.15, reps=9, hour=10, partials=1 if d < 8 else 0)
        review_all("P-017", leave=2)
        s.assign_program("P-017", "knee_rehab", "Knee Rehabilitation", ["knee_extension", "squat"], 3, today - timedelta(days=35))
        s.set_goal("P-017", "Knee Extension", target_rom=95.0, target_reps=10)

        # P-018: shoulder. Progressed well, then nothing for 12 days.
        s.add_patient("P-018", label="Shoulder impingement")
        for d, rom in zip([38, 35, 31, 28, 24, 21, 17, 12], ramp(108, 140, 8)):
            record(s, clock, rng, "P-018", "Shoulder Flexion", d, 90, rom)
        review_all("P-018", step="progress")
        s.assign_program("P-018", "shoulder_mobility", "Shoulder Mobility", ["shoulder_flexion"], 2, today - timedelta(days=35))
        s.set_goal("P-018", "Shoulder Flexion", target_rom=150.0)

        # P-019: conditioning. Steady and adherent; a quiet row on the roster.
        s.add_patient("P-019", label="General conditioning")
        for d in [33, 31, 29, 26, 24, 22, 19, 17, 15, 12, 10, 8, 5, 3, 1]:
            record(s, clock, rng, "P-019", "Squat", d, 91, 98, reps=12, target=12)
            if d % 2:
                record(s, clock, rng, "P-019", "Push-Up", d, 88, 82, reps=10, hour=11)
        review_all("P-019")
        s.assign_program("P-019", "general_conditioning", "General Conditioning", ["squat", "pushup"], 3, today - timedelta(days=35))

        # P-021: hip. Form score falling session after session, partial reps rising.
        s.add_patient("P-021", label="Hip replacement, week 10")
        for d, form, partials in zip([22, 18, 15, 11, 8, 4, 1], [92, 91, 90, 86, 82, 77, 71], [0, 0, 0, 1, 1, 3, 5]):
            record(s, clock, rng, "P-021", "Hip Abduction", d, form, 32, partials=partials, warnings=2 if d < 9 else 0)
        review_all("P-021", leave=3)
        s.assign_program("P-021", "hip_strengthening", "Hip Strengthening", ["hip_abduction"], 3, today - timedelta(days=21))

        # P-022: knee OA. ROM flat for weeks while below the goal (plateau).
        s.add_patient("P-022", label="Knee osteoarthritis")
        for d, rom in zip([26, 22, 19, 15, 12, 8, 5, 2], [70, 72, 73, 74, 74.5, 74, 75, 74.5]):
            record(s, clock, rng, "P-022", "Partial Squat", d, 87, rom, source="video" if d % 3 == 0 else "webcam")
        review_all("P-022", step="hold", leave=1)
        s.set_goal("P-022", "Partial Squat", target_rom=90.0)
        s.assign_program("P-022", "custom", "Knee OA home program", ["partial_squat"], 3, today - timedelta(days=28))

        # P-023: ACL return to sport. A safety stop last session, and low adherence.
        s.add_patient("P-023", label="ACL reconstruction, month 5")
        for d in [27, 20, 13, 3]:
            record(s, clock, rng, "P-023", "Squat", d, 84, 101, stop=(d == 3))
        review_all("P-023", leave=1)
        s.assign_program("P-023", "knee_rehab", "Knee Rehabilitation", ["squat", "knee_extension"], 3, today - timedelta(days=28))

        # P-024: elbow. A session interrupted by a closed tab, otherwise fine.
        s.add_patient("P-024", label="Elbow fracture, post-cast")
        for d, rom in zip([14, 11, 7, 4], ramp(85, 104, 4)):
            record(s, clock, rng, "P-024", "Elbow Flexion", d, 89, rom)
        lost = record(s, clock, rng, "P-024", "Elbow Flexion", 1, 88, 105, reps=4, interrupted=True)
        s.interrupt_session(lost, "stream_lost")
        review_all("P-024", leave=1)

        # P-020: new referral, nothing recorded yet.  P-016: discharged after meeting goals.
        s.add_patient("P-020", label="New referral")
        s.add_patient("P-016", label="Ankle sprain")
        for d in [60, 56, 52, 48]:
            record(s, clock, rng, "P-016", "Partial Squat", d, 93, 88)
        review_all("P-016", step="progress")
        s.discharge("P-016", on=today - timedelta(days=45), reason="Goals met, independent with home program")

        # Threshold settings with a history to look at.
        clock.now = datetime.now() - timedelta(days=9)
        s.set_installation_threshold("adherence", 65)
        clock.now = datetime.now() - timedelta(days=6)
        s.set_patient_threshold("P-019", "adherence", 50)
        s.set_patient_threshold("P-018", "practice_gap", 10)
        clock.now = datetime.now() - timedelta(days=1)
        s.set_exercise_threshold("P-017", "Knee Extension", "rom_regression", 5)
        clock.now = datetime.now()
        patients = len(s.list_patients())
        sessions = s.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    print(f"Wrote {db_path}: {patients} patients, {sessions} sessions (all simulated).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=str(REPO / "data" / "demo.db"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    db = Path(args.db).resolve()
    if db.name == "ptassist.db":
        print("Refusing to write simulated data into the real record (ptassist.db). Choose another --db.")
        return 1
    db.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    build(db, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
