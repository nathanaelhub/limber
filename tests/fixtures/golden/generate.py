#!/usr/bin/env python
"""
One-off generator for the legacy-format golden files.

Drives the four retired writers with tests/fixtures/golden/sequence.py and a fixed clock,
then copies their output next to this script:

    pta_log.txt        <- src.pta_raw_logger.PTARawLogger
    observation.json   <- src.observation_logger.ObservationLogger
    report.csv         <- src.session_tracker.SessionTracker._save_csv
    session.log        <- analyze.SessionLogger

Run once from the repo root:  .venv/bin/python tests/fixtures/golden/generate.py

Requires the legacy writer modules (including src/session_tracker.py), which last exist at
commit 4884fc4 on branch 001-unified-session-log (retired in the following commits). To regenerate, check
out that commit into a scratch worktree and run this script from there. Not collected
by pytest. The summary values passed to the writers at session end are the whole-session
values from expected_summary(), not the last tracker's values the legacy loops passed,
because the export contract (FR-009, FR-022) is legacy *format* with canonical *values*.
"""

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from tests.fixtures.golden.sequence import (  # noqa: E402
    CAMERA_ID, FRAME_SKIP, IMGSZ, PATIENT_ID, SEQUENCE, SETS, SOURCE, START,
    FixedClock, expected_summary, set_reps, ts_for,
)

import analyze  # noqa: E402
import src.observation_logger as obs_mod  # noqa: E402
import src.pta_raw_logger as pta_mod  # noqa: E402
import src.session_tracker as st_mod  # noqa: E402
from src.session_tracker import ExerciseRecord  # noqa: E402


def main() -> None:
    clock = FixedClock(START)
    for mod in (analyze, obs_mod, pta_mod, st_mod):
        mod.datetime = clock  # every datetime.now() in the legacy writers reads the fixed clock

    out = Path(tempfile.mkdtemp(prefix="ptlog-golden-"))
    cur = SETS["knee_extension"]

    # ---- session start (all writers) -------------------------------------------------
    clock.set(START)
    text = analyze.SessionLogger(log_dir=str(out / "logs"))
    text.log(f"SESSION START | Exercise: {cur['exercise_name']} | Camera: {CAMERA_ID} | imgsz: {IMGSZ} | skip: {FRAME_SKIP}")
    pta = pta_mod.PTARawLogger(log_dir=str(out / "pta"), source=SOURCE)
    pta.start_session(cur["exercise_name"])
    obs = obs_mod.ObservationLogger(log_dir=str(out / "obs"), source=SOURCE)
    obs.start_session(cur["exercise_name"], target_reps=cur["target_reps"])
    tracker = st_mod.SessionTracker(data_dir=str(out / "sessions"), patient_id=PATIENT_ID)
    tracker.start_session()

    reps_by_set = set_reps()

    def record_for(set_key: str) -> ExerciseRecord:
        info, reps = SETS[set_key], reps_by_set[set_key]
        n = len(reps)
        return ExerciseRecord(
            exercise_name=info["exercise_name"],
            reps_completed=n,
            target_reps=info["target_reps"],
            avg_form_score=sum(r["form_score"] for r in reps) / n if n else 0.0,
            min_rom=min(r["min_angle"] for r in reps) if n else 0.0,
            max_rom=max(r["max_angle"] for r in reps) if n else 0.0,
            rom_range=(max(r["max_angle"] for r in reps) - min(r["min_angle"] for r in reps)) if n else 0.0,
            avg_rep_duration=sum(r["duration_seconds"] for r in reps) / n if n else 0.0,
        )

    # ---- event stream ----------------------------------------------------------------
    for kind, p in SEQUENCE:
        clock.set(ts_for(p["frame_num"]))
        name = cur["exercise_name"]
        if kind == "sample":
            pta.log_observation(exercise=name, min_angle=cur["down_angle"], max_angle=cur["up_angle"],
                                angle=p["angle"], state=p["state"], count=p["rep_count"])
        elif kind == "rep":
            text.log(f"REP {p['rep_number']} | ROM: {p['rom']:.1f}° | Form: {p['form_score']:.0f}% | "
                     f"Duration: {p['duration_seconds']:.1f}s | Angle: {p['min_angle']:.0f}°-{p['max_angle']:.0f}°")
            obs.log_rep(rep_number=p["rep_number"], exercise=name, rom=p["rom"], form_score=p["form_score"],
                        duration_seconds=p["duration_seconds"], min_angle=p["min_angle"], max_angle=p["max_angle"])
            pta.log_rep_completed(name, p["rep_number"])
        elif kind == "partial":
            text.log(f"PARTIAL REP | ROM: {p['rom']:.1f}° | Angle: {p['min_angle']:.0f}°-{p['max_angle']:.0f}° | Reason: {p['reason']}")
            obs.log_partial_rep(exercise=name, rom=p["rom"], min_angle=p["min_angle"], max_angle=p["max_angle"],
                                duration_seconds=p["duration_seconds"], reason=p["reason"])
            pta.log_partial_rep(name, p["rom"], p["reason"])
        elif kind == "form":
            # Only the text logger recorded form feedback in the legacy loops.
            text.log(f"FORM {p['status'].upper()} | {p['message']}")
        elif kind == "switch":
            ip = p["interrupted_partial"]  # legacy 'n' key: interrupted partial to obs + pta only
            obs.log_partial_rep(exercise=name, rom=ip["rom"], min_angle=ip["min_angle"], max_angle=ip["max_angle"],
                                duration_seconds=ip["duration_seconds"], reason="interrupted")
            pta.log_partial_rep(name, ip["rom"], "interrupted")
            tracker.add_exercise_record(record_for(cur["exercise_key"]))
            new = SETS[p["to"]]
            obs.log_exercise_change(name, new["exercise_name"])
            pta.log_exercise_change(name, new["exercise_name"])
            text.log(f"SWITCH | {name} -> {new['exercise_name']}")
            cur = new
        elif kind == "reset":
            obs.log_reset(name, p["rep_count_at_reset"])
            pta.log_reset(name, p["rep_count_at_reset"])
            text.log(f"RESET | Reps cleared at count={p['rep_count_at_reset']}")
        elif kind == "end":
            s = expected_summary()
            text.close(f"Total Reps: {s['total_reps']} | Avg Form: {s['avg_form_score']:.0f}% | Avg ROM: {s['avg_rom']:.1f}°")
            obs.end_session(total_reps=s["total_reps"], avg_form_score=s["avg_form_score"], avg_rom=s["avg_rom"], warnings=[])
            pta.end_session(total_reps=s["total_reps"], avg_form_score=s["avg_form_score"], avg_rom=s["avg_rom"])
            tracker.add_exercise_record(record_for(cur["exercise_key"]))
            tracker.end_session()
            csv_path = tracker._save_csv()

    # ---- copy outputs ----------------------------------------------------------------
    shutil.copy(pta.file_path, HERE / "pta_log.txt")
    shutil.copy(obs.file_path, HERE / "observation.json")
    shutil.copy(csv_path, HERE / "report.csv")
    logs = sorted((out / "logs").glob("logfile-*.log"))
    for i, lf in enumerate(logs, 1):
        shutil.copy(lf, HERE / ("session.log" if i == 1 else f"session-{i:02d}.log"))
    print("golden files written:", [f.name for f in sorted(HERE.glob('*')) if f.suffix in ('.txt', '.json', '.csv', '.log')])
    shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    main()
