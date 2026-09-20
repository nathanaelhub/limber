"""
Patient ID and label rules (FR-013, FR-014; research D7).

Patients are pseudonymous. An ID is 1-32 letters, digits, or hyphens. Neither the ID nor
the label may contain text that looks like a full name (two or more consecutive
capitalized words), a numeric date, or a run of six or more digits (a medical record
number). Notes are free text and are not scanned.
"""

from __future__ import annotations

import re
from typing import Optional

from .models import PatientValidationError

ID_RE = re.compile(r"^[A-Za-z0-9-]{1,32}$")
NAME_RE = re.compile(r"[A-Z][a-z]+(?: [A-Z][a-z]+)+")
DATE_RE = re.compile(r"\d{1,4}[/-]\d{1,2}[/-]\d{1,4}")
DIGITS_RE = re.compile(r"\d{6,}")
LABEL_MAX = 60

_PHI_RULES = (
    (NAME_RE, "must not contain a name (two or more consecutive capitalized words)"),
    (DATE_RE, "must not contain a date"),
    (DIGITS_RE, "must not contain six or more consecutive digits (record numbers)"),
)


def _check_phi(value: str, what: str) -> None:
    for pattern, rule in _PHI_RULES:
        if pattern.search(value):
            raise PatientValidationError(
                f"{what} {rule}; identifying information must not be stored")


def validate_patient_id(value: Optional[str]) -> str:
    """Return the normalized ID or raise PatientValidationError naming the violated rule."""
    value = (value or "").strip()
    _check_phi(value, "Patient ID")
    if not ID_RE.match(value):
        raise PatientValidationError(
            "Patient ID must be 1-32 characters using only letters, digits, or hyphens")
    return value


def validate_label(value: Optional[str]) -> Optional[str]:
    """Return the normalized label (None when empty) or raise PatientValidationError."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > LABEL_MAX:
        raise PatientValidationError(f"Label must be at most {LABEL_MAX} characters")
    _check_phi(value, "Label")
    return value


def validate_notes(value: Optional[str], what: str = "Notes") -> Optional[str]:
    """Return normalized free text (None when empty) or raise on identifying text.

    Same three patterns as labels; no length cap, since chart notes can be long. `what` names
    the field in the error (notes, discharge reason, ...).
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    _check_phi(value, what)
    return value
