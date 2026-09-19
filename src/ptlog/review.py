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
