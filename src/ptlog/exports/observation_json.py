"""Observation JSON export (contracts/exports.md §2). The dict feeds src.session_summary unchanged."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..models import Session
from ._common import merged_events, parse_ts, sort_key, summary_numbers


def to_observation_dict(session: Session) -> Dict[str, Any]:
    start = parse_ts(session.start_time)
    end = parse_ts(session.end_time) if session.end_time else None
    duration = round((end - start).total_seconds(), 1) if end else None
    first = session.sets[0] if session.sets else None

    events: List[tuple] = [(sort_key(session.start_time, 0, "session_start"), {
        "type": "session_start", "timestamp": session.start_time,
        "exercise": first.exercise_name if first else None,
        "target_reps": first.target_reps if first else None,
    })]
    for kind, ts, frame, es, obj in merged_events(session):
        name = es.exercise_name if es else None
        if kind == "rep":
            ev = {"type": "rep", "timestamp": ts, "rep_number": obj.rep_number, "exercise": name,
                  "rom": round(float(obj.rom), 1), "form_score": round(float(obj.form_score), 1),
                  "duration_seconds": round(float(obj.duration_seconds), 2),
                  "min_angle": round(float(obj.min_angle), 1), "max_angle": round(float(obj.max_angle), 1)}
        elif kind == "partial_rep":
            ev = {"type": "partial_rep", "timestamp": ts, "exercise": name,
                  "rom": round(float(obj.rom), 1), "min_angle": round(float(obj.min_angle), 1),
                  "max_angle": round(float(obj.max_angle), 1),
                  "duration_seconds": round(float(obj.duration_seconds), 2), "reason": obj.reason}
        elif kind == "switch":
            ev = {"type": "exercise_change", "timestamp": ts,
                  "from_exercise": obj.from_exercise, "to_exercise": obj.to_exercise}
        elif kind == "reset":
            ev = {"type": "reset", "timestamp": ts, "exercise": name, "rep_count_at_reset": obj.rep_count_at_reset}
        else:
            continue  # form events were never part of the observation log
        events.append((sort_key(ts, frame, kind), ev))

    total, avg_form, avg_rom = summary_numbers(session)
    if end is not None and session.status != "running":
        events.append((sort_key(session.end_time, 10 ** 9, "session_end"), {
            "type": "session_end", "timestamp": session.end_time, "total_reps": total,
            "avg_form_score": avg_form, "avg_rom": avg_rom, "duration_seconds": duration}))
    events.sort(key=lambda e: e[0])

    groups: Dict[str, Dict[str, Any]] = {}
    for _, ev in events:
        if ev["type"] == "rep":
            g = groups.setdefault(ev["exercise"], {"reps": 0, "form": [], "rom": []})
            g["reps"] += 1
            g["form"].append(ev["form_score"])
            g["rom"].append(ev["rom"])
    exercises_performed = [{
        "exercise": name, "reps": g["reps"],
        "avg_form_score": round(sum(g["form"]) / len(g["form"]), 1) if g["form"] else 0.0,
        "avg_rom": round(sum(g["rom"]) / len(g["rom"]), 1) if g["rom"] else 0.0,
    } for name, g in groups.items()]

    return {
        "session_id": f"session_{start:%Y-%m-%d_%H%M%S}",
        "source": session.source,
        "start_time": session.start_time,
        "end_time": session.end_time,
        "duration_seconds": duration,
        "initial_exercise": first.exercise_name if first else None,
        "target_reps": first.target_reps if first else None,
        "events": [ev for _, ev in events],
        "summary": {
            "total_reps": total,
            "exercises_performed": exercises_performed,
            "avg_form_score": avg_form,
            "avg_rom": avg_rom,
            "warnings": ["Session interrupted"] if session.status == "interrupted" else [],
        },
    }


def to_observation_json(session: Session) -> str:
    return json.dumps(to_observation_dict(session), indent=2)
