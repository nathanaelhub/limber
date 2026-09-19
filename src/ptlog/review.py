"""
Review over time: trends, comparison, reviews, flags, and the assembled review summary.

Everything here reads the canonical record through SessionStore and computes with the pure
functions in measures.py and flags.py. Nothing about recording changes (FR-024).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .measures import measure_series
from .models import PERIODS, Goal, SessionMeasure, Trend
from .store import SessionStore

MEASURES = ("reps_completed", "avg_form", "avg_rom", "avg_duration", "tempo_sd", "partial_share")
_TWO_DECIMALS = ("avg_duration", "tempo_sd")


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now()


def period_start(period: str, now: datetime) -> Optional[datetime]:
    """Start of the period ('14d', '30d', '90d', 'all'); None means no lower bound."""
    if period not in PERIODS:
        raise ValueError(f"Unknown period '{period}'; choose from {', '.join(PERIODS)}")
    days = PERIODS[period]
    return None if days is None else now - timedelta(days=days)


def exercise_names(store: SessionStore, patient_id: str) -> List[str]:
    return store.exercise_names(patient_id)


def _change(name: str, first, latest):
    if first is None or latest is None:
        return None
    if name == "reps_completed":
        return int(latest) - int(first)
    return round(float(latest) - float(first), 2 if name in _TWO_DECIMALS else 1)


def rom_progress(goal: Optional[Goal], points: List[SessionMeasure]) -> Optional[int]:
    """Latest average ROM as a percentage of the goal, capped at 100 (FR-006)."""
    if goal is None or not goal.target_rom:
        return None
    latest = next((p.avg_rom for p in reversed(points) if p.avg_rom is not None), None)
    if latest is None:
        return None
    return min(100, round(latest / goal.target_rom * 100))


def trend(store: SessionStore, patient_id: str, exercise: str, period: str = "all",
          now: Optional[datetime] = None) -> Trend:
    """Per-session measures for one exercise over the period, oldest first (FR-004 … FR-007)."""
    now = _now(now)
    sessions = store.sessions_in_period(patient_id, period_start(period, now))
    return _trend_from_sessions(store, patient_id, exercise, period, sessions)


def _trend_from_sessions(store: SessionStore, patient_id: str, exercise: str, period: str, sessions) -> Trend:
    points = measure_series(sessions, exercise)
    t = Trend(exercise=exercise, period=period, points=points)
    if len(points) >= 2:
        t.enough_for_trend = True
        for name in MEASURES:
            first, latest = getattr(points[0], name), getattr(points[-1], name)
            t.summary[name] = {"first": first, "latest": latest, "change": _change(name, first, latest)}
    t.goal = store.get_goal(patient_id, exercise)
    t.rom_progress_pct = rom_progress(t.goal, points)
    return t


# ------------------------------------------------------------------ session reviews (US2)

def session_review_view(store: SessionStore, session_id: int) -> Dict:
    """Everything the session review shows: session, measures, per-session summary, review."""
    from src.session_summary import generate_session_summary  # existing single-session analysis, unchanged
    from .exports.observation_json import to_observation_dict
    from .measures import measures_for_session

    session = store.load_session(session_id)
    return {
        "session": session,
        "measures": measures_for_session(session),
        "summary": generate_session_summary(to_observation_dict(session)),
        "review": store.get_review(session_id),
    }


def pending(store: SessionStore, patient_id: str):
    """Sessions of the patient without a review, newest first (FR-011)."""
    return store.pending_reviews(patient_id)


# ------------------------------------------------------------------ flags (US3)

def flags_for(store: SessionStore, patient_id: str, period: str = "all", now: Optional[datetime] = None):
    """Attention flags for a patient over a period, with evidence (FR-014 … FR-016)."""
    now = _now(now)
    sessions = store.sessions_in_period(patient_id, period_start(period, now))
    return _flags_from_sessions(store, patient_id, sessions, now)


def _exercise_order(sessions) -> List[str]:
    names: List[str] = []
    for s in sessions:
        for es in s.sets:
            if es.exercise_name not in names:
                names.append(es.exercise_name)
    return names


def _flags_from_sessions(store: SessionStore, patient_id: str, sessions, now: datetime):
    from . import flags as rules
    names = _exercise_order(sessions)
    series_by_exercise = {name: measure_series(sessions, name) for name in names}
    goals = {g.exercise_name: g for g in store.list_goals(patient_id)}
    starts = [(s.id, s.start_time) for s in sessions]
    return rules.evaluate(series_by_exercise, goals, starts, store.get_gap_days(patient_id), now)


# ------------------------------------------------------------------ comparison (US4)

BETTER = {"reps_completed": "higher", "avg_form": "higher", "avg_rom": "higher",
          "avg_duration": "informational", "tempo_sd": "lower", "partial_share": "lower"}
PCT_MEASURES = ("reps_completed", "avg_form", "avg_rom")


def compare(store: SessionStore, session_a: int, session_b: int, exercise: Optional[str] = None):
    """Side-by-side measures of two sessions of one exercise (FR-017, FR-018)."""
    from .measures import measures_for_session
    from .models import METRIC_DEFINITIONS, Comparison, ComparisonError, ComparisonRow

    ma = measures_for_session(store.load_session(session_a))
    mb = measures_for_session(store.load_session(session_b))
    common = [name for name in ma if name in mb]
    if exercise is None:
        if len(common) == 1:
            exercise = common[0]
        elif not common:
            raise ComparisonError(
                f"Comparisons are within one exercise; sessions {session_a} ({', '.join(ma) or 'none'}) and "
                f"{session_b} ({', '.join(mb) or 'none'}) share no exercise.")
        else:
            raise ComparisonError(
                f"Sessions {session_a} and {session_b} share several exercises ({', '.join(common)}); name one to compare.")
    elif exercise not in common:
        raise ComparisonError(
            f"Comparisons are within one exercise; '{exercise}' is not recorded in both sessions "
            f"(shared: {', '.join(common) or 'none'}).")
    a, b = ma[exercise], mb[exercise]
    rows = []
    for name in MEASURES:
        va, vb = getattr(a, name), getattr(b, name)
        change = _change(name, va, vb)
        pct = None
        if name in PCT_MEASURES and va is not None and vb is not None and va != 0:
            pct = round((vb - va) / va * 100, 1)
        rows.append(ComparisonRow(name, METRIC_DEFINITIONS[name]["unit"], va, vb, change, pct, BETTER[name]))
    return Comparison(exercise=exercise, a=a, b=b, rows=rows)


# ------------------------------------------------------------------ review summary (US6)

def review_summary(store: SessionStore, patient_id: str, period: str = "all", now: Optional[datetime] = None):
    """Everything the review exports need for a patient and period (FR-020, FR-021)."""
    from .measures import measures_for_session
    from .models import PatientNotFoundError, ReviewSummary

    if store.get_patient(patient_id) is None:
        raise PatientNotFoundError(f"Patient '{patient_id}' not found")
    now = _now(now)
    since = period_start(period, now)
    sessions = store.sessions_in_period(patient_id, since)
    names = _exercise_order(sessions)
    trends = {name: _trend_from_sessions(store, patient_id, name, period, sessions) for name in names}
    goals = []
    for g in store.list_goals(patient_id):
        points = trends[g.exercise_name].points if g.exercise_name in trends else measure_series(sessions, g.exercise_name)
        latest = points[-1] if points else None
        goals.append({
            "goal": g,
            "latest_rom": latest.avg_rom if latest else None,
            "progress_pct": rom_progress(g, points),
            "latest_reps": latest.reps_completed if latest else None,
            "latest_target": latest.target_reps if latest else None,
        })
    session_entries = [{"session": s, "measures": measures_for_session(s), "review": store.get_review(s.id)}
                       for s in reversed(sessions)]
    return ReviewSummary(
        patient_id=patient_id, period=period, period_start=since.isoformat() if since else None,
        generated_at=now.isoformat(), gap_days=store.get_gap_days(patient_id), trends=trends,
        flags=_flags_from_sessions(store, patient_id, sessions, now), goals=goals, sessions=session_entries,
    )
