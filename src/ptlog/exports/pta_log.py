"""PTA-Log pipe-delimited text export (contracts/exports.md §1). Pure function of a Session."""

from __future__ import annotations

from typing import List, Optional

from ..models import Session
from ._common import merged_events, parse_ts, session_end_time, sort_key, summary_numbers

VERSION = "1.00"


def _pta_ts(iso: str) -> str:
    dt = parse_ts(iso)
    return dt.strftime("%Y:%m:%d:%H:%M:%S:") + f"{dt.microsecond // 1000:03d}"


def _line(ts: str, msg_type: str, message: str, data: Optional[str] = None) -> str:
    parts = [ts, f" {msg_type} ", f' "{message}"']
    if data:
        parts.append(f" {data}")
    return " |".join(parts)


def to_pta_log_text(session: Session, ordinal: int = 1) -> str:
    filename = f"PTA-Log-{ordinal:04d}.txt"
    start_ts = _pta_ts(session.start_time)
    first = session.sets[0] if session.sets else None
    lines: List[str] = [
        "PTA Observation Log",
        filename,
        f"Version: {VERSION}",
        f"Start time: {start_ts}",
        "",
        "Timestamp | Message Type | Message Text | [Data CSV of key=value pairs]",
        "",
        "Timestamp is in YYYY:MM:DD:HH:MM:SS:sss format",
        "Message Types are: SYSTEM, LOG, ERROR",
        "Fields are separated by '|' character",
        "Fields marked with [] are optional",
        "************",
        _line(start_ts, "SYSTEM", "Camera Detected."),
        _line(start_ts, "SYSTEM", f"System started successfully. Source: {session.source}"),
        _line(start_ts, "LOG", f"{first.exercise_name if first else ''} exercise selected",
              "min=0.0, max=0.0, angle=0.0, state=INIT, count=0"),
    ]

    stream = []
    for es in session.sets:
        for x in es.samples:
            stream.append((sort_key(x.timestamp, x.frame_num, "sample"), _line(
                _pta_ts(x.timestamp), "LOG", f"Observing {es.exercise_name}",
                f"min={es.down_angle:.1f}, max={es.up_angle:.1f}, angle={x.angle:.1f}, "
                f"state={x.state.upper()}, count={x.rep_count}")))
    for kind, ts, frame, es, obj in merged_events(session):
        name = es.exercise_name if es else ""
        if kind == "rep":
            stream.append((sort_key(ts, frame, kind), _line(_pta_ts(ts), "LOG", "Rep Completed",
                           f'exercise="{name}", repCount={obj.rep_number}')))
        elif kind == "partial_rep":
            stream.append((sort_key(ts, frame, kind), _line(_pta_ts(ts), "LOG", "Partial Rep",
                           f'exercise="{name}", rom={obj.rom:.1f}, reason="{obj.reason}"')))
        elif kind == "switch":
            stream.append((sort_key(ts, frame, kind), _line(_pta_ts(ts), "LOG", "Exercise Changed",
                           f'from="{obj.from_exercise}", to="{obj.to_exercise}"')))
        elif kind == "reset":
            stream.append((sort_key(ts, frame, kind), _line(_pta_ts(ts), "LOG", "Counter Reset",
                           f'exercise="{name}", repCountAtReset={obj.rep_count_at_reset}')))
        # form events were never written to the PTA log
    stream.sort(key=lambda r: r[0])
    lines += [line for _, line in stream]

    end_ts = _pta_ts(session_end_time(session))
    total, avg_form, avg_rom = summary_numbers(session)
    lines.append(_line(end_ts, "LOG", "Session Summary",
                       f"totalReps={total}, avgFormScore={avg_form:.1f}, avgRom={avg_rom:.1f}"))
    if session.status == "interrupted":
        lines.append(_line(end_ts, "ERROR", "Session interrupted"))
    lines.append(_line(end_ts, "SYSTEM", "System halted."))
    return "\n".join(lines) + "\n"
