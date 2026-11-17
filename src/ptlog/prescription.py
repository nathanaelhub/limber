"""Per-exercise details of a home program (feature 021 N1, FR-001 and FR-004).

A therapist may set, for each exercise in the current program, sets, reps, a hold, how often, and a short note to the
patient. Every value is optional: what is not set falls back to today's behaviour (the goal's target reps, else the
exercise's default). This module only checks the values and words them; the store keeps them on the assignment.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import AssignmentValidationError

SETS = (1, 10)
REPS = (1, 100)
HOLD = (0, 120)
DAYS = (1, 7)
NOTE_MAX = 200
FREQUENCIES = ("daily", "per_week")


def _whole(value: Any, low: int, high: int, what: str) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AssignmentValidationError(f"{what} must be a whole number from {low} to {high}.")
    try:
        number = float(value)
    except ValueError:
        raise AssignmentValidationError(f"{what} must be a whole number from {low} to {high}.") from None
    if not number.is_integer() or not (low <= number <= high):
        raise AssignmentValidationError(f"{what} must be a whole number from {low} to {high}.")
    return int(number)


def clean(detail: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The checked details, keeping only what is set. Raises AssignmentValidationError with a plain message."""
    detail = detail or {}
    if not isinstance(detail, dict):
        raise AssignmentValidationError("The exercise details could not be read.")
    out: Dict[str, Any] = {}
    for key, limits, what in (("sets", SETS, "Sets"), ("reps", REPS, "Reps"), ("hold_seconds", HOLD, "Hold")):
        value = _whole(detail.get(key), *limits, what + (" (seconds)" if key == "hold_seconds" else ""))
        if value is not None:
            out[key] = value
    frequency = detail.get("frequency") or None
    if frequency is not None:
        if frequency not in FREQUENCIES:
            raise AssignmentValidationError("How often must be every day or a number of days a week.")
        if frequency == "per_week":
            days = _whole(detail.get("days"), *DAYS, "Days a week")
            if days is None:
                raise AssignmentValidationError("Say how many days a week, from 1 to 7.")
            out["days"] = days
        out["frequency"] = frequency
    note = detail.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise AssignmentValidationError("The note must be text.")
        note = " ".join(note.split())
        if len(note) > NOTE_MAX:
            raise AssignmentValidationError(f"The note can be up to {NOTE_MAX} characters.")
        if note:
            out["note"] = note
    return out


def dose(detail: Optional[Dict[str, Any]]) -> str:
    """One plain sentence, such as "3 sets of 10 · 5-second hold · Every day". Empty when nothing is set."""
    detail = detail or {}
    parts = []
    sets, reps = detail.get("sets"), detail.get("reps")
    if sets and reps:
        parts.append(f"{sets} set{'s' if sets != 1 else ''} of {reps}")
    elif sets:
        parts.append(f"{sets} set{'s' if sets != 1 else ''}")
    elif reps:
        parts.append(f"{reps} rep{'s' if reps != 1 else ''}")
    if detail.get("hold_seconds"):
        parts.append(f"{detail['hold_seconds']}-second hold")
    if detail.get("frequency") == "daily":
        parts.append("Every day")
    elif detail.get("frequency") == "per_week":
        days = detail.get("days")
        parts.append(f"{days} day{'s' if days != 1 else ''} a week")
    return " · ".join(parts)


def target(detail: Optional[Dict[str, Any]], goal_reps: Optional[float], default: int) -> int:
    """The live session's target (owner's decision D1): the prescribed reps, else the goal's, else the default."""
    if detail and detail.get("reps"):
        return int(detail["reps"])
    if goal_reps:
        return int(goal_reps)
    return int(default)
