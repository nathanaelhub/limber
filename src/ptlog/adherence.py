"""
Adherence to an assigned program (FR-009 … FR-012). Pure functions over loaded sessions.

Weeks are seven-day periods from the assignment start date (research D2). A session counts
toward a week when it has at least one counted rep; an assigned exercise is performed in a
week when a set with that key has a counted rep (D4). The percentage covers complete weeks
only, capped per week (D3).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional, Tuple

from .models import Adherence, AdherenceWeek, Assignment, Session


def _d(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def assignment_status(a: Assignment, today: date) -> str:
    start = _d(a.start_date)
    end = _d(a.end_date) if a.end_date else None
    if end is not None and end < start:
        return "superseded"
    if start > today:
        return "scheduled"
    if end is not None and end < today:
        return "completed"
    return "active"


def week_bounds(a: Assignment, index: int) -> Tuple[date, date]:
    start = _d(a.start_date) + timedelta(days=7 * (index - 1))
    return start, start + timedelta(days=6)


def week_index(a: Assignment, on: date) -> int:
    return (on - _d(a.start_date)).days // 7 + 1


def _session_counts(session: Session) -> bool:
    return any(not r.out_of_range for es in session.sets for r in es.reps)


def _exercises_with_counted_reps(sessions: List[Session]) -> set:
    return {es.exercise_key for s in sessions for es in s.sets if any(not r.out_of_range for r in es.reps)}


def _build_week(a: Assignment, index: int, sessions: List[Session], complete: bool) -> AdherenceWeek:
    ws, we = week_bounds(a, index)
    in_week = [s for s in sessions if ws <= _d(s.start_time) <= we]
    counting = [s for s in in_week if _session_counts(s)]
    performed_keys = _exercises_with_counted_reps(counting)
    performed = [k for k in a.exercise_keys if k in performed_keys]
    missing = [k for k in a.exercise_keys if k not in performed_keys]
    recorded = len(counting)
    return AdherenceWeek(
        index=index, start=ws.isoformat(), end=we.isoformat(), planned=int(a.sessions_per_week),
        recorded=recorded, counted=min(recorded, int(a.sessions_per_week)),
        exercises_performed=performed, exercises_missing=missing,
        missed=complete and recorded == 0, in_progress=not complete,
    )


def compute(a: Optional[Assignment], sessions: List[Session], today: date, window_weeks: int = 4) -> Adherence:
    """Weeks in the window with counts and coverage, and the percentage over complete weeks."""
    if a is None:
        return Adherence(None, "none", [], None, "no program")
    status = assignment_status(a, today)
    if status == "superseded":
        return Adherence(a, status, [], None, "superseded")
    if status == "scheduled":
        return Adherence(a, status, [], None, f"starts on {a.start_date}")
    end = _d(a.end_date) if a.end_date else None
    last_day = min(today, end) if end else today
    current = week_index(a, last_day)
    if status == "active":
        current_complete = week_bounds(a, current)[1] < today
        complete_upto = current if current_complete else current - 1
        include_current = not current_complete
    else:
        complete_upto, include_current = current, False
    first = max(1, complete_upto - window_weeks + 1)
    weeks = [_build_week(a, i, sessions, complete=True) for i in range(first, complete_upto + 1)]
    if include_current:
        weeks.append(_build_week(a, current, sessions, complete=False))
    complete_weeks = [w for w in weeks if not w.in_progress]
    if not complete_weeks:
        return Adherence(a, status, weeks, None, "first week in progress")
    planned = sum(w.planned for w in complete_weeks)
    counted = sum(w.counted for w in complete_weeks)
    pct = round(100 * counted / planned) if planned else 0
    note = "" if status == "active" else f"completed on {a.end_date}"
    return Adherence(a, status, weeks, pct, note)
