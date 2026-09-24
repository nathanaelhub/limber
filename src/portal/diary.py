"""Exercise the patient did without the camera (feature 012).

A logged session is stored as a session with source `diary`, which every count meaning "did they
practise" includes and every measurement rule skips (src/ptlog/origin.py). The rules live here; the
routes only validate the request shape and render.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.ptlog import programs
from src.ptlog.entries import RECORDED_AT_MAX_AGE
from src.ptlog.models import EntryValidationError, ExerciseSetInfo, PortalError, Session
from src.ptlog.store import SessionStore

from . import messages

REPS_MIN, REPS_MAX = 1, 200
SETS_MIN, SETS_MAX = 1, 20
EFFORT = [(1, "very easy"), (2, "easy"), (3, "moderate"), (4, "hard"), (5, "very hard")]
NOTE_MAX = 200
FIELDS = ("exercise", "reps", "sets", "effort", "note", "done_at")

NOTICE = ("What you log here counts towards your week and your streak. It is always marked "
          "self-reported, because how far you moved and how your form looked can only be measured "
          "by a camera session.")
OFF = "Your therapist has turned off logging exercise without the camera."
DISCHARGED = "Your programme has finished, so nothing more can be logged."
LABEL = "Self-reported"


def options(store: SessionStore, patient_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """What the patient may log: their program's exercises first, then the rest of the configuration."""
    today = (now or datetime.now()).date()
    catalog = programs.load_catalog()
    assignment = store.active_assignment(patient_id, today)
    mine = [k for k in (assignment.exercise_keys if assignment else []) if k in catalog.exercises]
    rest = [k for k in catalog.exercises if k not in mine]
    return {
        "enabled": store.diary_enabled(patient_id),
        "notice": NOTICE,
        "marked_as": LABEL,             # not "label": that is a patient field, and the no-leak guard
                                        # looks for the word anywhere in a response
        "exercises": [{"key": k, "name": catalog.exercises[k]["display_name"], "in_program": k in mine}
                      for k in mine + rest],
        "reps": {"minimum": REPS_MIN, "maximum": REPS_MAX},
        "sets": {"minimum": SETS_MIN, "maximum": SETS_MAX},
        "effort": EFFORT,
        "note_max": NOTE_MAX,
        "days_back": RECORDED_AT_MAX_AGE.days,
    }


def log(store: SessionStore, patient_id: str, data: Any, now: Optional[datetime] = None,
        confirm: bool = False) -> Session:
    """Store one logged session, or refuse it. Nothing is written until every field is accepted."""
    now = now or datetime.now()
    if store.get_discharge(patient_id) is not None:
        raise PortalError(DISCHARGED)
    if not store.diary_enabled(patient_id):
        raise PortalError(OFF)
    fields = _accept(data, now)
    note = fields["note"]
    reasons = messages.check_text(note) if note else []
    if reasons and not confirm:
        raise messages.NeedsConfirmation(reasons)
    exercise = programs.load_catalog().exercises[fields["exercise"]]
    info = ExerciseSetInfo(fields["exercise"], exercise["display_name"], exercise["side"],
                           int(exercise["target_reps"]), float(exercise["up_angle"]), float(exercise["down_angle"]))
    extras: Dict[str, Any] = {"origin": "diary"}
    if note:
        extras["note"] = note
        extras["note_warned"] = bool(reasons)
    # No separate access-history row: the session itself records who logged what and when, with its
    # origin, so a `diary_logged` event would only duplicate it and cost a third portal_audit rebuild.
    return store.add_diary_session(patient_id, info, fields["reps"], fields["sets"], fields["effort"],
                                   fields["done_at"], extras)


def note_of(session: Session) -> Dict[str, Any]:
    """The patient's own words on a logged session, if they wrote any, with the privacy marker."""
    extras = session.source_extras or {}
    return {"note": extras.get("note") or "", "warned": bool(extras.get("note_warned"))}


def summary(session: Session) -> str:
    """One line for a list: what they said they did, always labelled."""
    sets = session.sets[0] if session.sets else None
    if sets is None:
        return LABEL
    effort = dict(EFFORT).get(sets.effort or 0, "")
    reps = f"{sets.reported_sets or 1} × {sets.reported_reps or 0} reps"
    return f"{sets.exercise_name}, {reps}" + (f", felt {effort}" if effort else "")


# ----------------------------------------------------------------------------- validation


def _accept(data: Any, now: datetime) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise EntryValidationError("Say which exercise you did, and how many reps and sets")
    extra = set(data) - set(FIELDS)
    if extra:
        raise EntryValidationError(f"Unexpected field(s): {', '.join(sorted(extra))}")
    key = data.get("exercise")
    if not isinstance(key, str) or key not in programs.load_catalog().exercises:
        raise EntryValidationError("Choose an exercise from the list")
    note = data.get("note") or ""
    if not isinstance(note, str):
        raise EntryValidationError("A note must be text")
    note = note.strip()
    if len(note) > NOTE_MAX:
        raise EntryValidationError(f"A note can be up to {NOTE_MAX} characters")
    return {"exercise": key, "note": note,
            "reps": _whole("Reps", data.get("reps"), REPS_MIN, REPS_MAX),
            "sets": _whole("Sets", data.get("sets"), SETS_MIN, SETS_MAX),
            "effort": _whole("How hard it felt", data.get("effort"), 1, 5),
            "done_at": _done_at(data.get("done_at"), now)}


def _whole(label: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or value is None or value == "":
        raise EntryValidationError(f"{label} must be a whole number {low}-{high}")
    if isinstance(value, float) and not float(value).is_integer():
        raise EntryValidationError(f"{label} must be a whole number {low}-{high}")
    try:
        number = int(str(value).strip())
    except ValueError:
        raise EntryValidationError(f"{label} must be a whole number {low}-{high}") from None
    if not low <= number <= high:
        raise EntryValidationError(f"{label} must be between {low} and {high}")
    return number


def _done_at(value: Any, now: datetime) -> str:
    """When they did it: now by default, and up to seven days back so a phone that was offline can
    still say which day it was. A time in the future or further back is refused, not quietly moved."""
    if value is None or value == "":
        return now.isoformat()
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        raise EntryValidationError("Give the day and time you did it") from None
    if when > now:
        raise EntryValidationError("That is in the future")
    if now - when > RECORDED_AT_MAX_AGE:
        raise EntryValidationError(f"You can log something from the last {RECORDED_AT_MAX_AGE.days} days")
    return when.isoformat()
