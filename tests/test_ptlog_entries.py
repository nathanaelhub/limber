"""Feature 010 T002 — the registry of what a patient can report, and validation of a check-in."""

from datetime import datetime, timedelta

import pytest

from src.ptlog import entries
from src.ptlog.models import EntryValidationError

NOW = datetime(2026, 9, 23, 9, 0, 0)
GOOD = {"pain": 4, "area": "knee", "stiffness": "mild", "swelling": "none", "note": "Sore after stairs"}


def test_registry_has_units_and_meanings():
    kind = entries.ENTRY_KINDS["checkin"]
    assert [f.key for f in kind.fields] == ["pain", "area", "stiffness", "swelling", "note"]
    for f in kind.fields:
        assert f.label and f.unit and len(f.meaning) > 15, f.key
    assert kind.fields[0].minimum == 0 and kind.fields[0].maximum == 10
    assert "knee" in kind.fields[1].choices and "other" in kind.fields[1].choices
    assert kind.fields[2].choices == ["none", "mild", "moderate", "severe"]
    assert entries.definitions("checkin")["pain"]["unit"] == "0-10"


def test_validate_accepts_a_good_checkin_and_normalises_it():
    payload, score = entries.validate("checkin", {**GOOD, "pain": "4", "note": "  Sore after stairs  "})
    assert payload == GOOD and score == 4.0
    payload, score = entries.validate("checkin", {"pain": 0, "area": "back", "stiffness": "none", "swelling": "none"})
    assert payload["note"] == "" and score == 0.0


@pytest.mark.parametrize("bad", [
    {**GOOD, "pain": 11}, {**GOOD, "pain": -1}, {**GOOD, "pain": 3.5}, {**GOOD, "pain": "bad"}, {**GOOD, "pain": True},
    {**GOOD, "area": "spleen"}, {**GOOD, "stiffness": "lots"}, {**GOOD, "swelling": None},
    {**GOOD, "note": "x" * 501}, {**GOOD, "extra": 1}, {"pain": 4}, "not a dict", None,
])
def test_validate_rejects(bad):
    with pytest.raises(EntryValidationError):
        entries.validate("checkin", bad)


def test_unknown_kind():
    with pytest.raises(EntryValidationError):
        entries.validate("horoscope", GOOD)


def test_recorded_time_window():
    assert entries.accept_recorded_at((NOW - timedelta(days=2)).isoformat(), NOW) == ((NOW - timedelta(days=2)).isoformat(), False)
    assert entries.accept_recorded_at((NOW + timedelta(minutes=10)).isoformat(), NOW) == (NOW.isoformat(), True)
    assert entries.accept_recorded_at((NOW - timedelta(days=8)).isoformat(), NOW) == (NOW.isoformat(), True)
    assert entries.accept_recorded_at("garbage", NOW) == (NOW.isoformat(), True)
    assert entries.accept_recorded_at(None, NOW) == (NOW.isoformat(), False)


def test_pain_series_uses_the_score_in_time_order():
    from src.ptlog.models import Entry
    rows = [Entry(id=2, patient_id="P", kind="checkin", recorded_at="2026-09-22T09:00:00", received_at="", phase="standalone",
                  session_id=None, score=6.0, payload={}, client_id="b"),
            Entry(id=1, patient_id="P", kind="checkin", recorded_at="2026-09-21T09:00:00", received_at="", phase="standalone",
                  session_id=None, score=3.0, payload={}, client_id="a")]
    assert entries.pain_series(rows) == [("2026-09-21T09:00:00", 3.0, 1), ("2026-09-22T09:00:00", 6.0, 2)]
