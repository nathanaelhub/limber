"""T021 — patient ID and label rules (FR-013, FR-014)."""

import pytest

from src.ptlog.models import PatientValidationError
from src.ptlog.privacy import LABEL_MAX, validate_label, validate_patient_id


class TestPatientId:
    @pytest.mark.parametrize("value", ["P-017", "abc123", "A" * 32, "p-017", "0"])
    def test_accepts_valid_ids(self, value):
        assert validate_patient_id(value) == value

    @pytest.mark.parametrize("value,rule", [
        ("", "1-32"),
        ("A" * 33, "1-32"),
        ("P 017", "letters, digits, or hyphens"),
        ("P_017", "letters, digits, or hyphens"),
        ("John Smith", "name"),
        ("01/02/1990", "date"),
        ("1990-01-02", "date"),
        ("123456", "six or more"),
        ("MRN1234567", "six or more"),
    ])
    def test_rejects_with_named_rule(self, value, rule):
        with pytest.raises(PatientValidationError) as exc:
            validate_patient_id(value)
        assert rule in str(exc.value)

    def test_strips_surrounding_whitespace(self):
        assert validate_patient_id("  P-017 ") == "P-017"


class TestLabel:
    def test_accepts_none_and_empty(self):
        assert validate_label(None) is None
        assert validate_label("") is None

    def test_accepts_max_length(self):
        assert validate_label("x" * LABEL_MAX) == "x" * LABEL_MAX

    def test_rejects_over_max_length(self):
        with pytest.raises(PatientValidationError) as exc:
            validate_label("x" * (LABEL_MAX + 1))
        assert str(LABEL_MAX) in str(exc.value)

    @pytest.mark.parametrize("value,rule", [
        ("Post-op knee for Jane Doe", "name"),
        ("DOB 1990-01-02", "date"),
        ("chart 00123456", "six or more"),
    ])
    def test_rejects_identifying_text(self, value, rule):
        with pytest.raises(PatientValidationError) as exc:
            validate_label(value)
        assert rule in str(exc.value)

    def test_accepts_clinical_label(self):
        assert validate_label("Post-op knee, week 3") == "Post-op knee, week 3"


class TestNotes:
    def test_accepts_empty_and_clinical_text(self):
        from src.ptlog.privacy import validate_notes
        assert validate_notes(None) is None
        assert validate_notes("") is None
        assert validate_notes("  post-op week 3, tolerated full set ") == "post-op week 3, tolerated full set"
        assert validate_notes("x" * 1000) == "x" * 1000

    @pytest.mark.parametrize("value,rule", [
        ("seen by Jane Doe", "name"), ("DOB 1990-01-02", "date"), ("MRN 123456", "six or more"),
    ])
    def test_rejects_identifying_text(self, value, rule):
        from src.ptlog.privacy import validate_notes
        with pytest.raises(PatientValidationError) as exc:
            validate_notes(value)
        assert rule in str(exc.value)
