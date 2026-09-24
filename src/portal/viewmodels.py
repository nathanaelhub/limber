"""
What a signed-in patient sees (feature 007). Pure builders over the existing record.

Rules every function here keeps (spec FR-004):
- the patient ID always comes from the caller's server-side sign-in, never from a request;
- only that patient's own data is returned;
- labels, notes, reviews, attention flags, and thresholds are never read, let alone returned.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Dict, List, Optional, Sequence

from src.ptlog import adherence as adherence_mod
from src.ptlog import programs
from src.ptlog.models import AdherenceWeek, PatientNotFoundError
from src.ptlog.store import SessionStore

ALL_WEEKS = 10_000            # adherence.compute() defaults to the last four weeks; a streak needs them all
NO_PROGRAM = "Your therapist has not assigned a program yet."
SKIPPED_ONE = "One exercise in your program is no longer available and was skipped."
SKIPPED_MANY = "{n} exercises in your program are no longer available and were skipped."


def streak(weeks: Sequence[AdherenceWeek]) -> int:
    """Consecutive complete weeks, counted back from the latest, in which the sessions recorded met
    the plan. The week in progress adds one once it meets the plan and never breaks the streak."""
    complete = [w for w in weeks if not w.in_progress]
    count = 0
    for w in reversed(complete):
        if w.recorded < w.planned:
            break
        count += 1
    current = next((w for w in weeks if w.in_progress), None)
    if current is not None and current.planned and current.recorded >= current.planned:
        count += 1
    return count


def _require(store: SessionStore, patient_id: str) -> None:
    if store.get_patient(patient_id) is None:
        raise PatientNotFoundError(f"Patient '{patient_id}' not found")


def _adherence(store: SessionStore, patient_id: str, today: date):
    assignment = store.active_assignment(patient_id, today)
    if assignment is None:
        return None, None
    since = datetime.combine(date.fromisoformat(assignment.start_date), time.min)
    sessions = store.sessions_in_period(patient_id, since)
    return assignment, adherence_mod.compute(assignment, sessions, today, window_weeks=ALL_WEEKS)


def adherence_view(store: SessionStore, patient_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Sessions done this week against the plan, and the weekly streak; both None without a program."""
    _require(store, patient_id)
    now = now or datetime.now()
    assignment, adh = _adherence(store, patient_id, now.date())
    if assignment is None or not adh.weeks:
        return {"week": None if assignment is None else {"done": 0, "planned": int(assignment.sessions_per_week)},
                "streak_weeks": None if assignment is None else 0}
    current = next((w for w in adh.weeks if w.in_progress), None)
    week = {"done": current.recorded if current else 0, "planned": int(assignment.sessions_per_week)}
    return {"week": week, "streak_weeks": streak(adh.weeks)}


def _target_reps(store: SessionStore, patient_id: str, name: str, default: int) -> int:
    goal = store.get_goal(patient_id, name)
    return int(goal.target_reps) if goal is not None and goal.target_reps else int(default)


def program_exercises(store: SessionStore, patient_id: str, today: date) -> List[Dict[str, Any]]:
    """The active assignment's exercises that the configuration still defines, in order, with the
    target reps the patient should aim for (their goal's target, else the exercise default)."""
    assignment = store.active_assignment(patient_id, today)
    if assignment is None:
        return []
    catalog = programs.load_catalog()
    result = []
    for key in assignment.exercise_keys:
        entry = catalog.exercises.get(key)
        if entry is None:
            continue
        name = entry["display_name"]
        result.append({"key": key, "name": name,
                       "target_reps": _target_reps(store, patient_id, name, entry["target_reps"])})
    return result


def done_today_keys(store: SessionStore, patient_id: str, now: datetime) -> set:
    """Exercise keys with at least one counted rep in a session that started today."""
    start = datetime.combine(now.date(), time.min)
    sessions = [s for s in store.sessions_in_period(patient_id, start) if s.start_time[:10] == now.date().isoformat()]
    return adherence_mod._exercises_with_counted_reps(sessions)


def clips_badge(store: SessionStore, patient_id: str) -> Dict[str, Any]:
    rows = store.media_list(patient_id, "clip")
    return {"count": len(rows), "waiting": sum(1 for m in rows if m.deleted_at is None and m.reviewed_at is None)}


def checkin_badge(store: SessionStore, patient_id: str, now: datetime) -> Dict[str, Any]:
    """Whether Today should offer a check-in, and how many were made today."""
    from src.ptlog.entries import pain_series
    today = now.date().isoformat()
    made = [e for e in store.entries(patient_id, "checkin", newest_first=True, limit=20) if e.recorded_at[:10] == today]
    return {"prompt": True, "today": len(made)}


def entry_json(e) -> Dict[str, Any]:
    return {"id": e.id, "kind": e.kind, "recorded_at": e.recorded_at[:16], "phase": e.phase, "session_id": e.session_id,
            "score": e.score, "payload": e.payload, "warned": e.warned, "time_adjusted": e.time_adjusted,
            "note_removed": e.note_removed}


def entries_view(store: SessionStore, patient_id: str) -> Dict[str, Any]:
    from src.ptlog import entries as reg
    _require(store, patient_id)
    rows = store.entries(patient_id, newest_first=True, limit=200)
    return {"patient_id": patient_id, "entries": [entry_json(e) for e in rows],
            "definitions": {kind: reg.definitions(kind) for kind in reg.ENTRY_KINDS}}


def messages_badge(store: SessionStore, patient_id: str) -> Dict[str, Any]:
    """Whether the patient has a conversation with their therapist, and how much of it is unread."""
    from src.portal import messages
    enabled = messages.is_enabled(store, patient_id)
    return {"enabled": enabled, "unread": messages.unread_count(store, patient_id, viewer="patient") if enabled else 0}


def message_json(m) -> Dict[str, Any]:
    return {"id": m.id, "from": "you" if m.sender == "patient" else "therapist", "text": m.body,
            "sent_at": m.sent_at[:16], "removed": m.removed}


def messages_view(store: SessionStore, patient_id: str) -> Dict[str, Any]:
    """The patient's own conversation, oldest first; opening it marks the therapist's messages read."""
    from src.portal import messages
    _require(store, patient_id)
    enabled = messages.is_enabled(store, patient_id)
    thread = messages.thread(store, patient_id, viewer="patient") if enabled else []
    return {"patient_id": patient_id, "enabled": enabled, "notice": messages.NOT_FOR_EMERGENCIES,
            "messages": [message_json(m) for m in thread]}


def logs_badge(store: SessionStore, patient_id: str, now: datetime) -> Dict[str, Any]:
    """What the patient may log besides exercise: medication is offered only if the therapist set a
    list to choose from (feature 012 FR-006); sleep is always offered."""
    from src.ptlog import entries as reg
    today = now.date().isoformat()
    made = store.entries(patient_id, newest_first=True, limit=50)
    return {"medications": store.medication_list(patient_id), "sleep": True,
            "medication_today": sum(1 for e in made if e.kind == "medication" and e.recorded_at[:10] == today),
            "sleep_today": sum(1 for e in made if e.kind == "sleep" and e.recorded_at[:10] == today),
            "definitions": {kind: reg.definitions(kind) for kind in ("medication", "sleep")}}


def today_view(store: SessionStore, patient_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    from src.portal import diary
    _require(store, patient_id)
    now = now or datetime.now()
    today = now.date()
    view: Dict[str, Any] = {"patient_id": patient_id, "date": today.isoformat(), "program": None, "exercises": [],
                            "week": None, "streak_weeks": None, "message": None,
                            "messages": messages_badge(store, patient_id),
                            "checkin": checkin_badge(store, patient_id, now),
                            "clips": clips_badge(store, patient_id),
                            "diary": diary.options(store, patient_id, now=now),
                            "logs": logs_badge(store, patient_id, now)}
    assignment = store.active_assignment(patient_id, today)
    if assignment is None:
        view["message"] = NO_PROGRAM
        return view
    done = done_today_keys(store, patient_id, now)
    exercises = program_exercises(store, patient_id, today)
    view["program"] = {"name": assignment.program_name, "sessions_per_week": int(assignment.sessions_per_week)}
    view["exercises"] = [{**e, "done_today": e["key"] in done} for e in exercises]
    skipped = len(assignment.exercise_keys) - len(exercises)
    if skipped:
        view["notes"] = [SKIPPED_ONE if skipped == 1 else SKIPPED_MANY.format(n=skipped)]
    view.update(adherence_view(store, patient_id, now))
    return view


# ----------------------------------------------------------------------------- progress (US3)

PROGRESS_NOTE = ("Sessions done at home and in the clinic are measured with different camera software, so they are "
                 "shown separately and their numbers should not be compared with each other.")
NEED_MORE = "More sessions are needed before a change can be shown."
NO_SESSIONS = "No sessions yet. Your progress will appear here after your first session."
_PATIENT_WORDING = {
    "avg_rom": ("Range of motion", "How far the joint moved on average in a session."),
    "avg_form": ("Form score", "How closely your movement matched good form, on average, out of 100."),
}


def _definitions() -> Dict[str, Dict[str, str]]:
    from src.ptlog.models import METRIC_DEFINITIONS
    result = {}
    for key, (label, plain) in _PATIENT_WORDING.items():
        unit = METRIC_DEFINITIONS[key]["unit"]
        result[key] = {"name": label, "unit": "out of 100" if unit == "score 0-100" else unit, "meaning": plain}
    return result


def progress_view(store: SessionStore, patient_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Per exercise: range of motion and form per session, the change from first to latest, and
    progress toward a range-of-motion goal, always within one capture origin (spec FR-013, FR-020).
    Never flags, reviews, notes, or thresholds."""
    from src.ptlog import review

    _require(store, patient_id)
    now = now or datetime.now()
    view: Dict[str, Any] = {"patient_id": patient_id, "definitions": _definitions(), "note": PROGRESS_NOTE,
                            "exercises": [], "message": None}
    for name in review.exercise_names(store, patient_id):
        trend = review.trend(store, patient_id, name, "all", now=now)
        series, change = {}, {}
        for origin, part in trend.by_origin.items():
            series[origin] = [{"date": m.start_time[:10], "avg_rom": m.avg_rom, "avg_form": m.avg_form,
                               "reps": m.reps_completed} for m in part.points]
            change[origin] = ({k: part.summary[k]["change"] for k in ("avg_rom", "avg_form")}
                              if part.enough_for_trend else None)
        goal = None
        if trend.goal is not None and trend.goal.target_rom:
            latest = next((m.avg_rom for m in reversed(trend.by_origin[trend.primary_origin].points)
                           if m.avg_rom is not None), None)
            if latest is not None:
                goal = {"target_rom": float(trend.goal.target_rom), "percent": trend.rom_progress_pct,
                        "recorded": trend.primary_origin,
                        "sentence": f"{latest:g}° of your {trend.goal.target_rom:g}° goal"}
        view["exercises"].append({
            "name": name, "series": series, "change": change, "goal": goal,
            "message": NEED_MORE if all(c is None for c in change.values()) else None})
    if not view["exercises"]:
        view["message"] = NO_SESSIONS
    from src.ptlog import entries as reg
    series = reg.pain_series(store.entries(patient_id, "checkin"))
    view["pain"] = {"series": [{"date": t[:10], "time": t[11:16], "pain": s} for t, s, _ in series],
                    "definition": reg.definitions("checkin")["pain"]}
    return view
