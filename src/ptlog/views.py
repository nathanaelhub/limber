"""
Presentation helpers shared by the CLI and the web app.

Every number shown to a clinician carries its unit (constitution V, FR-012). Interface
files call these functions and only render what they return. This module also feeds the
legacy trend math in src/session_tracker.py from the canonical record (research D13).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import METRIC_DEFINITIONS, ExerciseSet, Session
from .store import SessionStore

NOT_AVAILABLE = "not available"


def metric_label(field: str) -> str:
    """'rom' -> 'ROM (degrees)'; the unit always comes from METRIC_DEFINITIONS."""
    unit = METRIC_DEFINITIONS[field]["unit"]
    pretty = {"rom": "ROM", "avg_rom": "avg ROM", "avg_form_score": "avg form score"}.get(field, field.replace("_", " "))
    return f"{pretty} ({unit})"


def metric_definition(field: str) -> str:
    return METRIC_DEFINITIONS[field]["definition"]


def clock_time(ts: Optional[str]) -> str:
    """HH:MM:SS from an ISO timestamp."""
    if not ts:
        return "--:--:--"
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except ValueError:
        return ts[11:19]


def date_minute(ts: Optional[str]) -> str:
    """'2026-03-23 09:15' from an ISO timestamp."""
    return (ts or "")[:16].replace("T", " ")


def fmt_form(value: Optional[float]) -> str:
    return NOT_AVAILABLE if value is None else f"{value:.1f}/100"


def fmt_rom(value: Optional[float]) -> str:
    return NOT_AVAILABLE if value is None else f"{value:.1f}°"


def fmt_seconds(value: Optional[float]) -> str:
    return NOT_AVAILABLE if value is None else f"{value:.1f} s"


# ------------------------------------------------------------------ set-level statistics

def set_summary(es: ExerciseSet) -> Dict[str, Any]:
    """Per-set numbers over reps not flagged out of range (shared with the CSV export)."""
    reps = [r for r in es.reps if not r.out_of_range]
    n = len(reps)
    if n == 0:
        return {"reps": 0, "target_reps": es.target_reps, "avg_form_score": 0.0, "min_angle": 0.0,
                "max_angle": 0.0, "rom_range": 0.0, "avg_duration": 0.0, "avg_rom": 0.0}
    min_angle = min(r.min_angle for r in reps)
    max_angle = max(r.max_angle for r in reps)
    return {
        "reps": n,
        "target_reps": es.target_reps,
        "avg_form_score": sum(r.form_score for r in reps) / n,
        "min_angle": min_angle,
        "max_angle": max_angle,
        "rom_range": max_angle - min_angle,
        "avg_duration": sum(r.duration_seconds for r in reps) / n,
        "avg_rom": sum(r.rom for r in reps) / n,
    }


def legacy_flags(session: Session) -> List[str]:
    """The review flags the retired session tracker generated, plus the interrupted flag."""
    flags: List[str] = []
    for es in session.sets:
        st = set_summary(es)
        if st["avg_form_score"] < 60:
            flags.append(f"{es.exercise_name}: Low form score ({st['avg_form_score']:.0f}%)")
        if st["reps"] < st["target_reps"] * 0.5:
            flags.append(f"{es.exercise_name}: Completed only {st['reps']}/{st['target_reps']} reps")
    if session.status == "interrupted":
        flags.append("Session interrupted")
    return flags


# ------------------------------------------------------------------ rendering

def session_header_lines(session: Session) -> List[str]:
    src = f"{session.source} ({session.source_ref})" if session.source_ref else session.source
    lines = [
        f"Session {session.id} | patient {session.patient_id} | {src}",
        f"Started {date_minute(session.start_time)} | Ended {date_minute(session.end_time) or NOT_AVAILABLE} | "
        f"Duration {fmt_seconds(session.duration_seconds)}",
        f"Total reps {session.total_reps if session.total_reps is not None else 0} | "
        f"avg form {fmt_form(session.avg_form_score)} | avg ROM {fmt_rom(session.avg_rom)}",
        f"STATUS: {session.status}",
    ]
    return lines


def event_log_lines(store: SessionStore, session_id: int) -> List[str]:
    """One human-readable line per event, every metric with its unit; ends with STATUS."""
    session = store.load_session(session_id)
    lines: List[str] = []
    for row in store.event_log(session_id):
        d, t = row.data, clock_time(row.timestamp)
        if row.type == "session_start":
            lines.append(f"[{t}] SESSION START | {d['exercise']} ({d['side']}) | target {d['target_reps']} | {d['source']} {d['source_ref']}")
        elif row.type == "rep":
            flag = " | OUT OF RANGE" if d.get("out_of_range") else ""
            lines.append(f"[{t}] REP {d['rep_number']} | ROM {d['rom']:.1f}° | form {d['form_score']:.0f}/100 | "
                         f"{d['duration_seconds']:.1f} s | {d['min_angle']:.1f}°–{d['max_angle']:.1f}°{flag}")
        elif row.type == "partial_rep":
            lines.append(f"[{t}] PARTIAL REP | {d['reason']} | ROM {d['rom']:.1f}° | "
                         f"{d['min_angle']:.1f}°–{d['max_angle']:.1f}° | {d['duration_seconds']:.1f} s")
        elif row.type == "form":
            lines.append(f"[{t}] FORM {d['severity']} | {d['message']}")
        elif row.type == "switch":
            lines.append(f"[{t}] SWITCH | {d['from_exercise']} -> {d['to_exercise']}")
        elif row.type == "reset":
            lines.append(f"[{t}] RESET | {d['exercise']} | count {d['rep_count_at_reset']}")
        elif row.type == "session_end":
            label = "SESSION INTERRUPTED" if d.get("status") == "interrupted" else "SESSION END"
            lines.append(f"[{t}] {label} | {d['total_reps']} reps | avg form {fmt_form(d['avg_form_score'])} | "
                         f"avg ROM {fmt_rom(d['avg_rom'])} | {fmt_seconds(d['duration_seconds'])}")
    lines.append(f"STATUS: {session.status}")
    return lines


def session_table_rows(store: SessionStore, patient_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Rows for a history table, newest first."""
    return [
        {
            "id": r.id,
            "date": date_minute(r.start_time),
            "patient_id": r.patient_id,
            "source": r.source,
            "exercises": ", ".join(r.exercises),
            "total_reps": r.total_reps if r.total_reps is not None else 0,
            "avg_form_score": fmt_form(r.avg_form_score),
            "status": r.status,
        }
        for r in store.list_sessions(patient_id)
    ]


# ------------------------------------------------------------------ legacy trend math bridge

def load_session_data_for_trends(store: SessionStore, patient_id: str) -> list:
    """Build the SessionData/ExerciseRecord objects src.session_tracker's trend math expects."""
    from src.session_tracker import ExerciseRecord, SessionData  # local import keeps ptlog free of matplotlib

    history = []
    for row in reversed(store.list_sessions(patient_id)):   # oldest first, as the tracker's history was
        session = store.load_session(row.id)
        start = datetime.fromisoformat(session.start_time)
        end = datetime.fromisoformat(session.end_time) if session.end_time else start
        records = []
        for es in session.sets:
            st = set_summary(es)
            records.append(ExerciseRecord(
                exercise_name=es.exercise_name,
                reps_completed=st["reps"],
                target_reps=st["target_reps"],
                avg_form_score=round(st["avg_form_score"], 1),
                min_rom=round(st["min_angle"], 1),
                max_rom=round(st["max_angle"], 1),
                rom_range=round(st["rom_range"], 1),
                avg_rep_duration=round(st["avg_duration"], 2),
                form_warnings=[f.message for f in es.form_events],
            ))
        overall = round(sum(r.avg_form_score for r in records) / len(records), 1) if records else 0.0
        history.append(SessionData(
            session_id=f"{session.patient_id}_{start.strftime('%Y%m%d_%H%M%S')}",
            patient_id=session.patient_id,
            date=start.strftime("%Y-%m-%d"),
            start_time=start.strftime("%H:%M:%S"),
            end_time=end.strftime("%H:%M:%S"),
            duration_minutes=(end - start).total_seconds() / 60,
            exercises=records,
            overall_form_score=overall,
            flags_for_review=legacy_flags(session),
            metadata={"canonical_session_id": session.id, "source": session.source, "status": session.status},
        ))
    return history


# ------------------------------------------------------------------ web-app adapters

from dataclasses import dataclass  # noqa: E402


@dataclass
class SessionRef:
    """A session handle with the path-like attributes the web pages used for legacy files."""
    id: int
    patient_id: str
    start_time: str
    source: str
    status: str
    exercises: List[str]
    total_reps: Optional[int]
    avg_form_score: Optional[float]

    @property
    def stem(self) -> str:
        return f"session_{self.id}"

    @property
    def name(self) -> str:
        return f"session_{self.id}"

    def __str__(self) -> str:
        return str(self.id)


def session_refs(store: SessionStore, patient_id: Optional[str] = None) -> List[SessionRef]:
    """Sessions newest first as SessionRef handles."""
    return [SessionRef(r.id, r.patient_id, r.start_time, r.source, r.status, r.exercises, r.total_reps, r.avg_form_score)
            for r in store.list_sessions(patient_id)]


def observation_dict(store: SessionStore, session_id: int) -> Dict[str, Any]:
    """The legacy observation-log dict for a session (feeds session_summary and the pages)."""
    from .exports.observation_json import to_observation_dict  # local import avoids a module cycle
    return to_observation_dict(store.load_session(session_id))
