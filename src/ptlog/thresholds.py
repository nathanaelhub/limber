"""
Attention thresholds (feature 005): the one place that defines each threshold's name, unit,
plain-language meaning, built-in default, and allowed range, and that resolves the value in
use for a patient (patient override, else installation value, else built-in default).
Pure functions; storage lives in SessionStore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

from .models import ThresholdValidationError

ORIGINS = ("patient", "installation", "default")


@dataclass(frozen=True)
class ThresholdDef:
    key: str
    name: str
    unit: str
    default: int
    minimum: int
    maximum: int
    meaning: str


_DEFS = [
    ThresholdDef("practice_gap", "Practice gap", "days", 7, 1, 90,
                 "Flag when more than this many days pass between sessions or since the last session."),
    ThresholdDef("form_drop", "Form drop", "points", 10, 1, 50,
                 "Flag when the latest average form score is at least this far below the best of the other "
                 "three recent sessions."),
    ThresholdDef("rom_regression", "ROM regression", "degrees", 10, 1, 60,
                 "Flag when the latest average range of motion is at least this far below the best of the "
                 "previous three sessions."),
    ThresholdDef("rom_plateau", "ROM plateau", "degrees", 3, 1, 30,
                 "Flag when range of motion changed by less than this across four sessions while below the goal."),
    ThresholdDef("target_reps_sessions", "Sessions below target", "sessions", 3, 2, 10,
                 "Flag when this many consecutive sessions ended below the target rep count."),
    ThresholdDef("partial_share", "Partial-rep share", "percent", 25, 1, 100,
                 "The partial-rep flag needs the latest session's share of partial reps to be at least this."),
    ThresholdDef("partial_rise", "Partial-rep rise", "percentage points", 10, 1, 100,
                 "The partial-rep flag also needs the latest share to be at least this far above the mean of "
                 "the previous three sessions."),
    ThresholdDef("adherence", "Adherence", "percent", 60, 1, 100,
                 "Mark the patient for attention when adherence to the assigned program is below this."),
]
THRESHOLDS: Dict[str, ThresholdDef] = {d.key: d for d in _DEFS}


def validate(key: str, value) -> int:
    """Return the value as a whole number inside the key's range, or raise ThresholdValidationError."""
    if key not in THRESHOLDS:
        raise ThresholdValidationError(f"Unknown threshold '{key}'; choose from {', '.join(THRESHOLDS)}")
    d = THRESHOLDS[key]
    allowed = f"{d.name} must be a whole number in the range {d.minimum}-{d.maximum} {d.unit}"
    if isinstance(value, bool) or value is None:
        raise ThresholdValidationError(allowed)
    if isinstance(value, float):
        if not value.is_integer():
            raise ThresholdValidationError(allowed)
        value = int(value)
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ThresholdValidationError(allowed) from None
    if not d.minimum <= number <= d.maximum:
        raise ThresholdValidationError(allowed)
    return number


@dataclass(frozen=True)
class Thresholds:
    """The complete set in use for one patient: a value and an origin for every key."""
    values: Dict[str, int] = field(default_factory=dict)
    origins: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> "Thresholds":
        return _DEFAULTS

    def value(self, key: str) -> int:
        return self.values[key]

    def origin(self, key: str) -> str:
        return self.origins[key]

    def overridden(self) -> List[str]:
        return [k for k in self.values if self.origins[k] != "default"]

    def __getattr__(self, key: str) -> int:
        values = object.__getattribute__(self, "values")
        if key in values:
            return values[key]
        raise AttributeError(key)


def resolve(patient: Optional[Mapping[str, int]] = None,
            installation: Optional[Mapping[str, int]] = None) -> Thresholds:
    """Patient override, else installation value, else built-in default. Unknown stored keys are ignored."""
    patient, installation = patient or {}, installation or {}
    values, origins = {}, {}
    for key, d in THRESHOLDS.items():
        if key in patient:
            values[key], origins[key] = int(patient[key]), "patient"
        elif key in installation:
            values[key], origins[key] = int(installation[key]), "installation"
        else:
            values[key], origins[key] = d.default, "default"
    return Thresholds(values, origins)


_DEFAULTS = resolve()
