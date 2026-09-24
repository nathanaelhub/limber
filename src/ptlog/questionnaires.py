"""Scoring a questionnaire, and when the next one is due (feature 013).

Scoring is arithmetic the definition file describes, nothing more: `sum` or `mean` of the item values,
each reversed item turned round inside its own range, subscales scored over their own items, and one
rule for missing items. Nothing here interprets a score clinically, and no attention rule is derived
from one; the sentence saying what a score means comes from the definition.

Every score is stored with a **snapshot** — the item values, ranges, reversals, subscale membership,
and rules that produced it — so a stored total can be reproduced years later even if the definition has
since been edited or deleted. A therapist is told that the installed definition differs; a stored number
is never quietly recomputed.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .instruments import Instrument
from .models import EntryValidationError

INTERVALS: List[Tuple[str, str]] = [
    ("once", "once only"),
    ("weekly", "every week"),
    ("fortnightly", "every two weeks"),
    ("monthly", "every month"),
]
INTERVAL_KEYS = tuple(k for k, _ in INTERVALS)
OVERDUE_DAYS = 7                                   # past due by more than this reaches the work queue


@dataclass(frozen=True)
class Score:
    total: float
    subscales: Dict[str, Optional[float]] = field(default_factory=dict)
    answered: int = 0
    missing: int = 0
    minimum: float = 0.0
    maximum: float = 0.0


# ----------------------------------------------------------------------------- scoring


def score(instrument: Instrument, answers: Any) -> Score:
    """Score an answer set, or refuse it with a message the patient can act on."""
    return rescore(snapshot(instrument, answers))


def snapshot(instrument: Instrument, answers: Any) -> Dict[str, Any]:
    """Everything needed to reproduce this score without the definition file."""
    checked = _check(instrument, answers)
    return {
        "instrument": instrument.key,
        "version": instrument.version,
        "name": instrument.name,
        "unit": instrument.unit,
        "meaning": instrument.meaning,
        "direction": instrument.direction,
        "notice": instrument.notice,
        "scoring": instrument.scoring,
        "minimum_answered": instrument.minimum_answered,
        "replace_with_mean": instrument.replace_with_mean,
        "items": [{"key": i.key, "text": i.text, "value": checked.get(i.key),
                   "minimum": i.minimum, "maximum": i.maximum, "reversed": i.reversed,
                   "answer": _answer_text(i, checked.get(i.key))}
                  for i in instrument.items],
        "subscales": [{"key": s.key, "name": s.name, "items": list(s.item_keys),
                       "minimum": s.minimum, "maximum": s.maximum} for s in instrument.subscales],
    }


def rescore(snap: Dict[str, Any]) -> Score:
    """The score of a stored questionnaire, from its snapshot alone."""
    items = snap["items"]
    scored = {i["key"]: _value(i) for i in items if i.get("value") is not None}
    answered = len(scored)
    missing = len(items) - answered
    if answered < int(snap["minimum_answered"]):
        raise EntryValidationError(f"At least {snap['minimum_answered']} of the {len(items)} questions "
                                   "need an answer before this can be scored")
    mean_of_answered = sum(scored.values()) / answered
    replace = bool(snap["replace_with_mean"])
    method = snap["scoring"]

    used = list(scored.values())
    if replace:
        used += [mean_of_answered] * missing
    total = sum(used) if method == "sum" else (sum(used) / len(used))

    subscales: Dict[str, Optional[float]] = {}
    for sub in snap.get("subscales", []):
        own = [scored[k] for k in sub["items"] if k in scored]
        if not own:
            subscales[sub["key"]] = None
            continue
        own_mean = sum(own) / len(own)
        values = own + ([own_mean] * (len(sub["items"]) - len(own)) if replace else [])
        subscales[sub["key"]] = _round(sum(values) if method == "sum" else sum(values) / len(values))

    minimum = sum(i["minimum"] for i in items) if method == "sum" else min(i["minimum"] for i in items)
    maximum = sum(i["maximum"] for i in items) if method == "sum" else max(i["maximum"] for i in items)
    return Score(total=_round(total), subscales=subscales, answered=answered, missing=missing,
                 minimum=_round(minimum), maximum=_round(maximum))


def differs_from_installed(snap: Dict[str, Any], instrument: Optional[Instrument]) -> bool:
    """True when the definition now installed is not the one this questionnaire was answered under."""
    if instrument is None:
        return True
    return instrument.key != snap["instrument"] or int(instrument.version) != int(snap["version"])


def answer_rows(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per item for the therapist: the question, what was answered, and the value scored."""
    return [{"Question": i["text"], "Answer": i.get("answer") or "(not answered)",
             "Value": _value(i) if i.get("value") is not None else None,
             "Reversed": "yes" if i["reversed"] else ""} for i in snap["items"]]


def _check(instrument: Instrument, answers: Any) -> Dict[str, int]:
    if not isinstance(answers, dict) or not answers:
        raise EntryValidationError("Answer the questions before sending")
    checked: Dict[str, int] = {}
    for key, value in answers.items():
        item = instrument.item(str(key))
        if item is None:
            raise EntryValidationError(f"'{key}' is not a question in {instrument.name}")
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise EntryValidationError(f"The answer to '{item.text}' must be one of its choices")
        if value not in item.values():
            raise EntryValidationError(f"The answer to '{item.text}' must be one of its choices")
        checked[item.key] = int(value)
    if len(checked) < instrument.minimum_answered:
        raise EntryValidationError(f"At least {instrument.minimum_answered} of the {len(instrument.items)} "
                                   "questions need an answer")
    return checked


def _value(item: Dict[str, Any]) -> int:
    """The value as scored: reversed items are turned round inside their own range."""
    value = int(item["value"])
    if item.get("reversed"):
        return int(item["minimum"]) + int(item["maximum"]) - value
    return value


def _answer_text(item, value) -> str:
    if value is None:
        return ""
    return next((c.text for c in item.choices if c.value == value), str(value))


def _round(number: float) -> float:
    rounded = round(float(number), 1)
    return int(rounded) if float(rounded).is_integer() else rounded


# ----------------------------------------------------------------------------- when it is due


def next_due(interval: str, start: date, last_answered: Optional[date]) -> Optional[date]:
    """The date this questionnaire is next due, or None when nothing more is expected."""
    if interval not in INTERVAL_KEYS:
        raise EntryValidationError(f"How often must be one of: {', '.join(INTERVAL_KEYS)}")
    if last_answered is None:
        return start
    if interval == "once":
        return None
    if interval == "weekly":
        return _plus_days(last_answered, 7)
    if interval == "fortnightly":
        return _plus_days(last_answered, 14)
    return _plus_month(last_answered)


def is_due(due: Optional[date], today: date) -> bool:
    return due is not None and due <= today


def is_overdue(due: Optional[date], today: date, grace_days: int = OVERDUE_DAYS) -> bool:
    return due is not None and (today - due).days > grace_days


def interval_words(interval: str) -> str:
    return dict(INTERVALS).get(interval, interval)


def _plus_days(day: date, days: int) -> date:
    from datetime import timedelta
    return day + timedelta(days=days)


def _plus_month(day: date) -> date:
    """The same day next month, clamped to the end of a shorter month (31 January → 28 February)."""
    year = day.year + (1 if day.month == 12 else 0)
    month = 1 if day.month == 12 else day.month + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
