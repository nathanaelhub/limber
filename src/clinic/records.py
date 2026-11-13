"""The clinic Dashboard, Sessions and Observation logs (feature 019 slice 5a, FR-011), tested without a server.

The Dashboard is the therapist's home page (owner's decision, 12 November 2026): what needs them today first,
then their caseload's activity. Everything is read from the record, limited to the caseload; nothing is read from
files on disk, so it works on the hosted demo too. Exports and the rep CSV use the standard library only.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from src.ptlog.store import SessionStore

PERIODS = {7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days"}
EXPORTS = {"pta_log": ("txt", "text/plain", "PTA-Log text"),
           "observation_json": ("json", "application/json", "Observation JSON"),
           "csv_report": ("csv", "text/csv", "CSV report"),
           "text_log": ("log", "text/plain", "Session text log")}


def period(value) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 30
    return days if days in PERIODS else 30


def _mean(values: List[float]) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def activity(store: SessionStore, now: datetime, days: int) -> dict:
    """Sessions, reps, average form and range of motion over the period, and both by week (Monday first)."""
    since = (now - timedelta(days=days)).isoformat()
    rows = store.session_measures(since)
    weeks: Dict[date, dict] = {}
    for r in rows:
        day = date.fromisoformat(r["start_time"][:10])
        week = day - timedelta(days=day.weekday())
        w = weeks.setdefault(week, {"form": [], "rom": []})
        w["form"].append(r["avg_form_score"])
        w["rom"].append(r["avg_rom"])
    ordered = sorted(weeks)
    return {"sessions": len(rows), "reps": sum(r["total_reps"] or 0 for r in rows),
            "form": _mean([r["avg_form_score"] for r in rows]), "rom": _mean([r["avg_rom"] for r in rows]),
            "form_by_week": [(w.strftime("%-d %b"), _mean(weeks[w]["form"])) for w in ordered],
            "rom_by_week": [(w.strftime("%-d %b"), _mean(weeks[w]["rom"])) for w in ordered]}


def todays_visits(schedule_groups: dict, today: date) -> List[dict]:
    return [v for v in schedule_groups["upcoming"] if v["date"] == today.isoformat()]


def recent(store: SessionStore, limit: int = 8) -> List[dict]:
    out = []
    for r in store.list_sessions():
        if r.status == "running":
            continue
        out.append({"id": r.id, "when": datetime.fromisoformat(r.start_time[:19]).strftime("%a %-d %b, %H:%M"),
                    "patient_id": r.patient_id, "exercises": ", ".join(r.exercises) or "Session",
                    "reps": r.total_reps or 0, "form": r.avg_form_score, "origin": r.origin, "source": r.source,
                    "status": r.status})
        if len(out) >= limit:
            break
    return out


def session_rows(store: SessionStore, patient_id: Optional[str] = None) -> List[dict]:
    rows = []
    for r in store.list_sessions(patient_id):
        rows.append({"id": r.id, "when": datetime.fromisoformat(r.start_time[:19]).strftime("%a %-d %b %Y, %H:%M"),
                     "patient_id": r.patient_id, "exercises": ", ".join(r.exercises) or "Session",
                     "kind": "Video analysis" if r.source == "video" else "Live session",
                     "where": {"home": "at home", "browser": "in the clinic, browser pose"}.get(r.origin, "in the clinic"),
                     "reps": r.total_reps or 0, "form": r.avg_form_score, "status": r.status})
    return rows


def log_data(store: SessionStore, session_id: int) -> dict:
    """One session as its observation log, ready for the page: facts, per-rep rows, the timeline, warnings."""
    from src.ptlog.exports.observation_json import to_observation_dict
    session = store.load_session(session_id)
    data = to_observation_dict(session)
    reps = [e for e in data["events"] if e["type"] == "rep"]
    summary = data["summary"]
    from src.clinic.video import camera_warnings
    summary["warnings"] = list(summary.get("warnings") or []) + camera_warnings(session)
    target = data.get("target_reps") or 0
    return {"session": session, "data": data, "reps": reps, "summary": summary, "target": target,
            "completion": round(summary["total_reps"] / target * 100) if target else None,
            "timeline": [timeline_line(e) for e in data["events"]]}


def timeline_line(e: dict) -> tuple:
    """(time, label, detail) for one event, every measure with its unit."""
    t = datetime.fromisoformat(e["timestamp"][:19]).strftime("%H:%M:%S")
    kind = e["type"]
    if kind == "rep":
        return (t, "Rep complete", f"Rep {e['rep_number']} · {e['exercise']} · range of motion {e['rom']}° · "
                f"form {e['form_score']} of 100 · {e['duration_seconds']} s")
    if kind == "partial_rep":
        return (t, "Partial rep", f"{e['exercise']} · {e['reason']} · range of motion {e['rom']}°")
    if kind == "exercise_change":
        return (t, "Exercise switch", f"{e['from_exercise']} to {e['to_exercise']}")
    if kind == "reset":
        return (t, "Reset", f"During {e['exercise']} at rep {e['rep_count_at_reset']}")
    if kind == "session_start":
        return (t, "Session start", f"{e['exercise']} · target {e['target_reps']} reps")
    if kind == "session_end":
        return (t, "Session end", f"{e['total_reps']} reps · average form {e['avg_form_score']} of 100 · "
                f"average range of motion {e['avg_rom']}° · {e['duration_seconds']} s")
    return (t, kind.replace("_", " ").capitalize(), "")


def rep_csv(reps: List[dict]) -> str:
    """Every rep event as CSV, with the columns in the order they first appear (as the old pandas export)."""
    columns: List[str] = []
    for e in reps:
        columns += [k for k in e if k not in columns]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for e in reps:
        writer.writerow(e)
    return out.getvalue()


def export(store: SessionStore, session_id: int, fmt: str) -> tuple:
    """(content, file name, media type) for one of the four session exports."""
    from src.ptlog.exports import FORMATS
    if fmt not in EXPORTS:
        raise KeyError(fmt)
    session = store.load_session(session_id)
    content = FORMATS[fmt][1](store, session)
    if isinstance(content, list):
        content = "\n".join(content)
    ext, mime, _ = EXPORTS[fmt]
    stamp = datetime.fromisoformat(session.start_time[:19]).strftime("%Y%m%d_%H%M%S")
    return content, f"{session.patient_id}_{stamp}.{ext}", mime
