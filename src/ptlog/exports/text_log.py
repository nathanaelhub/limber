"""Plain-text session log export (contracts/exports.md §4), the numbered logfile-NN.log layout."""

from __future__ import annotations

from typing import List

from ..models import Session
from ._common import merged_events, parse_ts, session_end_time, summary_numbers

MAX_LINES = 50


def to_text_log(session: Session) -> List[str]:
    """Return one string per 50-line file, exactly as the retired SessionLogger rolled them."""
    files: List[str] = []
    current: List[str] = [f"# logfile created: {parse_ts(session.start_time):%Y-%m-%d %H:%M:%S}"]

    def add(ts: str, message: str) -> None:
        nonlocal current
        if len(current) >= MAX_LINES:
            files.append("\n".join(current) + "\n")
            current = [f"# continued: {parse_ts(ts):%Y-%m-%d %H:%M:%S}"]
        current.append(f"[{parse_ts(ts):%H:%M:%S}] {message}")

    first = session.sets[0] if session.sets else None
    name = first.exercise_name if first else ""
    extras = session.source_extras or {}
    if session.source == "webcam":
        add(session.start_time, f"SESSION START | Exercise: {name} | Camera: {extras.get('camera_id', session.source_ref)} | "
                                f"imgsz: {extras.get('imgsz', '')} | skip: {extras.get('frame_skip', '')}")
    else:
        add(session.start_time, f"SESSION START | Exercise: {name} | Source: {session.source_ref}")

    for kind, ts, frame, es, obj in merged_events(session):
        if kind == "rep":
            add(ts, f"REP {obj.rep_number} | ROM: {obj.rom:.1f}° | Form: {obj.form_score:.0f}% | "
                    f"Duration: {obj.duration_seconds:.1f}s | Angle: {obj.min_angle:.0f}°-{obj.max_angle:.0f}°")
        elif kind == "partial_rep":
            if obj.reason == "interrupted":
                continue  # the legacy text logger never saw partials recorded at a switch or reset
            add(ts, f"PARTIAL REP | ROM: {obj.rom:.1f}° | Angle: {obj.min_angle:.0f}°-{obj.max_angle:.0f}° | Reason: {obj.reason}")
        elif kind == "form":
            add(ts, f"FORM {obj.status.upper()} | {obj.message}")
        elif kind == "switch":
            add(ts, f"SWITCH | {obj.from_exercise} -> {obj.to_exercise}")
        elif kind == "reset":
            add(ts, f"RESET | Reps cleared at count={obj.rep_count_at_reset}")

    total, avg_form, avg_rom = summary_numbers(session)
    label = "SESSION INTERRUPTED" if session.status == "interrupted" else "SESSION END"
    add(session_end_time(session), f"{label} | Total Reps: {total} | Avg Form: {avg_form:.0f}% | Avg ROM: {avg_rom:.1f}°")
    files.append("\n".join(current) + "\n")
    return files
