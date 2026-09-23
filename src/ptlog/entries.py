"""
What a patient reports about themselves (feature 010 onward): the registry of entry kinds and their
fields, with a unit and a plain-language meaning for each (constitution V), validation, and small
helpers over stored entries. Storage lives in SessionStore; this module is pure.

Kinds arrive feature by feature: `checkin` (010); questionnaire, medication, sleep later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import EntryValidationError

NOTE_MAX = 500
RECORDED_AT_MAX_AGE = timedelta(days=7)
LEVELS = ["none", "mild", "moderate", "severe"]
AREAS = ["neck", "shoulder", "elbow", "wrist or hand", "back", "hip", "knee", "ankle or foot", "other"]


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    unit: str
    meaning: str
    kind: str                                  # int | choice | text
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    choices: List[str] = field(default_factory=list)
    required: bool = True


@dataclass(frozen=True)
class EntryKind:
    key: str
    label: str
    fields: List[Field]
    score_field: Optional[str]                 # the one number kept beside the payload for trends and flags


ENTRY_KINDS: Dict[str, EntryKind] = {
    "checkin": EntryKind("checkin", "Pain and symptom check-in", [
        Field("pain", "Pain now", "0-10", "How much pain you feel right now: 0 is none, 10 is the worst you can imagine.",
              "int", 0, 10),
        Field("area", "Where", "body area", "The part of the body the pain or stiffness is in.", "choice", choices=AREAS),
        Field("stiffness", "Stiffness", "level", "How stiff the joint feels: none, mild, moderate, or severe.",
              "choice", choices=LEVELS),
        Field("swelling", "Swelling", "level", "How swollen the area looks or feels: none, mild, moderate, or severe.",
              "choice", choices=LEVELS),
        Field("note", "Note", "text", "Anything else you want your therapist to know, in your own words.",
              "text", required=False),
    ], score_field="pain"),
}


def definitions(kind: str) -> Dict[str, Dict[str, str]]:
    k = ENTRY_KINDS[kind]
    return {f.key: {"label": f.label, "unit": f.unit, "meaning": f.meaning} for f in k.fields}


def validate(kind: str, data: Any) -> Tuple[Dict[str, Any], Optional[float]]:
    """(normalised payload, score) or EntryValidationError with a plain message."""
    if kind not in ENTRY_KINDS:
        raise EntryValidationError(f"Unknown entry kind '{kind}'")
    k = ENTRY_KINDS[kind]
    if not isinstance(data, dict):
        raise EntryValidationError("An entry is a set of named answers")
    known = {f.key for f in k.fields}
    extra = set(data) - known
    if extra:
        raise EntryValidationError(f"Unexpected field(s): {', '.join(sorted(extra))}")
    payload: Dict[str, Any] = {}
    for f in k.fields:
        value = data.get(f.key)
        if value is None or value == "":
            if f.required:
                raise EntryValidationError(f"{f.label} is required")
            payload[f.key] = "" if f.kind == "text" else None
            continue
        if f.kind == "int":
            if isinstance(value, bool) or isinstance(value, float) and not float(value).is_integer():
                raise EntryValidationError(f"{f.label} must be a whole number {f.minimum}-{f.maximum}")
            try:
                number = int(str(value).strip())
            except ValueError:
                raise EntryValidationError(f"{f.label} must be a whole number {f.minimum}-{f.maximum}") from None
            if not f.minimum <= number <= f.maximum:
                raise EntryValidationError(f"{f.label} must be between {f.minimum} and {f.maximum}")
            payload[f.key] = number
        elif f.kind == "choice":
            if not isinstance(value, str) or value not in f.choices:
                raise EntryValidationError(f"{f.label} must be one of: {', '.join(f.choices)}")
            payload[f.key] = value
        else:
            if not isinstance(value, str):
                raise EntryValidationError(f"{f.label} must be text")
            text = value.strip()
            if len(text) > NOTE_MAX:
                raise EntryValidationError(f"{f.label} can be up to {NOTE_MAX} characters")
            payload[f.key] = text
    score = float(payload[k.score_field]) if k.score_field and payload.get(k.score_field) is not None else None
    return payload, score


def accept_recorded_at(value: Any, now: datetime) -> Tuple[str, bool]:
    """The recorded time to store and whether it had to be replaced by the receive time (a phone
    clock in the future or an entry older than seven days)."""
    if value is None:
        return now.isoformat(), False
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return now.isoformat(), True
    if when > now or now - when > RECORDED_AT_MAX_AGE:
        return now.isoformat(), True
    return when.isoformat(), False


def pain_series(rows: Sequence[Any]) -> List[Tuple[str, float, int]]:
    """(recorded_at, pain, entry id) for check-ins with a score, oldest first."""
    scored = [(r.recorded_at, float(r.score), r.id) for r in rows if r.kind == "checkin" and r.score is not None]
    return sorted(scored, key=lambda t: (t[0], t[2]))
