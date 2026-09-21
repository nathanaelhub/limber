"""Feature 005 T002 — the threshold registry, validation, and resolution (pure functions)."""

import pytest

from src.ptlog.models import PTLogError, ThresholdValidationError
from src.ptlog.thresholds import THRESHOLDS, Thresholds, resolve, validate

EXPECTED = [  # key, unit, default, minimum, maximum
    ("practice_gap", "days", 7, 1, 90),
    ("form_drop", "points", 10, 1, 50),
    ("rom_regression", "degrees", 10, 1, 60),
    ("rom_plateau", "degrees", 3, 1, 30),
    ("target_reps_sessions", "sessions", 3, 2, 10),
    ("partial_share", "percent", 25, 1, 100),
    ("partial_rise", "percentage points", 10, 1, 100),
    ("adherence", "percent", 60, 1, 100),
]


def test_registry_matches_the_specification():
    got = [(d.key, d.unit, d.default, d.minimum, d.maximum) for d in THRESHOLDS.values()]
    assert got == EXPECTED
    for d in THRESHOLDS.values():
        assert d.name and len(d.meaning) > 20, d.key


@pytest.mark.parametrize("key,unit,default,lo,hi", EXPECTED)
def test_validate_bounds(key, unit, default, lo, hi):
    assert validate(key, lo) == lo and validate(key, hi) == hi and validate(key, str(default)) == default
    for bad in (lo - 1, hi + 1):
        with pytest.raises(ThresholdValidationError) as err:
            validate(key, bad)
        assert f"{lo}-{hi}" in str(err.value) and unit in str(err.value)


@pytest.mark.parametrize("bad", [5.5, "5.5", "abc", None, True, ""])
def test_validate_rejects_non_whole_numbers(bad):
    with pytest.raises(ThresholdValidationError):
        validate("form_drop", bad)


def test_validate_unknown_key_lists_the_known_ones():
    with pytest.raises(ThresholdValidationError) as err:
        validate("speed", 3)
    assert "rom_regression" in str(err.value)
    assert issubclass(ThresholdValidationError, PTLogError)


def test_resolution_precedence_and_origins():
    t = resolve({"rom_regression": 5, "from_the_future": 1}, {"rom_regression": 8, "form_drop": 12})
    assert (t.value("rom_regression"), t.origin("rom_regression")) == (5, "patient")
    assert (t.value("form_drop"), t.origin("form_drop")) == (12, "installation")
    assert (t.value("adherence"), t.origin("adherence")) == (60, "default")
    assert t.overridden() == ["form_drop", "rom_regression"]
    assert list(t.values) == list(THRESHOLDS)
    assert t.rom_regression == 5 and t.practice_gap == 7


def test_defaults():
    d = Thresholds.defaults()
    assert d.overridden() == [] and all(d.value(k) == THRESHOLDS[k].default for k in THRESHOLDS)
    assert resolve(None, None).values == d.values
    with pytest.raises(AttributeError):
        d.nonexistent


# ----------------------------------------------------------------------------- feature 006: exercise layer

def test_exercise_level_keys():
    from src.ptlog.thresholds import EXERCISE_KEYS, validate_exercise_key
    assert EXERCISE_KEYS == ["form_drop", "rom_regression", "rom_plateau", "target_reps_sessions",
                             "partial_share", "partial_rise"]
    assert validate_exercise_key("rom_regression", "5") == 5
    for key in ("practice_gap", "adherence"):
        with pytest.raises(ThresholdValidationError) as err:
            validate_exercise_key(key, 5)
        assert "whole patient" in str(err.value)
    with pytest.raises(ThresholdValidationError):
        validate_exercise_key("speed", 5)
    with pytest.raises(ThresholdValidationError):
        validate_exercise_key("rom_regression", 0)


def test_exercise_layer_wins_and_is_named():
    t = resolve({"rom_regression": 8, "form_drop": 12}, {"rom_plateau": 4}, exercise={"rom_regression": 5, "adherence": 1})
    assert (t.rom_regression, t.origin("rom_regression")) == (5, "exercise")
    assert (t.form_drop, t.origin("form_drop")) == (12, "patient")
    assert (t.rom_plateau, t.origin("rom_plateau")) == (4, "installation")
    assert (t.adherence, t.origin("adherence")) == (60, "default")          # not an exercise-level key: ignored
    assert resolve({"rom_regression": 8}, None).origin("rom_regression") == "patient"
