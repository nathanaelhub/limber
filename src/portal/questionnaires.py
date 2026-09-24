"""What a patient may answer, and accepting an answer set (feature 013).

The scoring lives in `src/ptlog/questionnaires.py` and the definitions in `src/ptlog/instruments.py`;
this module joins them to one patient's assignments and turns an answer set into the payload the record
stores. The routes only carry it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from src.ptlog import instruments as registry
from src.ptlog import questionnaires as rules
from src.ptlog.models import EntryValidationError, PortalError
from src.ptlog.store import SessionStore

NOT_ASSIGNED = "That questionnaire is not assigned to you."


def _installed(directory=None):
    return registry.load(directory)


def assigned(store: SessionStore, patient_id: str, today: Optional[date] = None,
             directory=None) -> List[Dict[str, Any]]:
    """Every live assignment of this patient, with its instrument and when it is next due.

    An assignment whose definition is no longer installed is left out of the patient's view: they cannot
    answer what cannot be shown. The therapist still sees the answers already given."""
    today = today or date.today()
    installed = _installed(directory).by_key
    result = []
    for assignment in store.assignments(patient_id):
        instrument = installed.get(assignment.instrument_key)
        if instrument is None:
            continue
        last = store.last_questionnaire_at(patient_id, assignment.instrument_key)
        last_day = date.fromisoformat(last[:10]) if last else None
        due = rules.next_due(assignment.interval, date.fromisoformat(assignment.start_date), last_day)
        result.append({
            "instrument": instrument.key,
            "name": instrument.name,
            "meaning": instrument.meaning,
            "unit": instrument.unit,
            "direction": instrument.direction,
            "notice": instrument.notice,
            "how_often": rules.interval_words(assignment.interval),
            "due_on": due.isoformat() if due else None,
            "is_due": rules.is_due(due, today),
            "last_answered": last,
            "item_count": len(instrument.items),
            "minimum_answered": instrument.minimum_answered,
            "items": [{"key": i.key, "text": i.text,
                       "choices": [{"text": c.text, "value": c.value} for c in i.choices]}
                      for i in instrument.items],
        })
    return result


def view(store: SessionStore, patient_id: str, now: Optional[datetime] = None, directory=None) -> Dict[str, Any]:
    """What the questionnaire page shows: what is due first, then anything assigned but not yet due."""
    now = now or datetime.now()
    mine = assigned(store, patient_id, now.date(), directory)
    return {"patient_id": patient_id,
            "due": [q for q in mine if q["is_due"]],
            "assigned": [q for q in mine if not q["is_due"]]}


def badge(store: SessionStore, patient_id: str, now: Optional[datetime] = None, directory=None) -> Dict[str, Any]:
    """What Today needs: how many are due, and when the next one is."""
    mine = assigned(store, patient_id, (now or datetime.now()).date(), directory)
    dates = sorted(q["due_on"] for q in mine if q["due_on"])
    return {"due": sum(1 for q in mine if q["is_due"]), "assigned": len(mine),
            "next_due_on": dates[0] if dates else None,
            "names": [q["name"] for q in mine if q["is_due"]]}


def accept(store: SessionStore, patient_id: str, data: Any, now: Optional[datetime] = None,
           directory=None) -> tuple:
    """Validate and score one answer set: (payload for the record, the total as the entry's score)."""
    now = now or datetime.now()
    if not isinstance(data, dict):
        raise EntryValidationError("Send the questionnaire and its answers")
    extra = set(data) - {"instrument", "answers"}
    if extra:
        raise EntryValidationError(f"Unexpected field(s): {', '.join(sorted(extra))}")
    key = data.get("instrument")
    if not isinstance(key, str) or not key:
        raise EntryValidationError("Say which questionnaire this is")
    if store.instrument_assignment(patient_id, key) is None:
        raise EntryValidationError(NOT_ASSIGNED)
    instrument = _installed(directory).by_key.get(key)
    if instrument is None:
        raise EntryValidationError(NOT_ASSIGNED)
    answers = data.get("answers")
    snapshot = rules.snapshot(instrument, answers)          # refuses a bad answer set before anything is stored
    score = rules.rescore(snapshot)
    payload = {
        "instrument": instrument.key,
        "version": instrument.version,
        "name": instrument.name,
        "answers": {k: v for k, v in answers.items() if v is not None},
        "total": score.total,
        "subscales": score.subscales,
        "answered": score.answered,
        "missing": score.missing,
        "snapshot": snapshot,
    }
    return payload, float(score.total)
