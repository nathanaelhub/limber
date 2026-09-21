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


def today_view(store: SessionStore, patient_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    _require(store, patient_id)
    now = now or datetime.now()
    today = now.date()
    view: Dict[str, Any] = {"patient_id": patient_id, "date": today.isoformat(), "program": None, "exercises": [],
                            "week": None, "streak_weeks": None, "message": None}
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
        result[key] = {"label": label, "unit": "out of 100" if unit == "score 0-100" else unit, "meaning": plain}
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
    return view
