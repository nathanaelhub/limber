"""T004 — models carry the data-model fields, units, and validation rules."""

import dataclasses

import pytest

from src.ptlog import models
from src.ptlog.models import (
    METRIC_DEFINITIONS,
    ControlEvent,
    DeleteReport,
    ExerciseSet,
    ExerciseSetInfo,
    FormEvent,
    FrameSample,
    LedgerRow,
    LogRow,
    PartialRepEvent,
    Patient,
    RepEvent,
    Session,
    SessionSummaryRow,
)


def _fields(cls):
    return {f.name for f in dataclasses.fields(cls)}


class TestDataclassFields:
    def test_patient_fields(self):
        assert {"id", "label", "notes", "created_at", "is_builtin"} <= _fields(Patient)

    def test_session_fields(self):
        expected = {
            "id", "patient_id", "schema_version", "source", "source_ref", "source_extras",
            "status", "start_time", "end_time", "total_reps", "avg_form_score", "avg_rom",
            "duration_seconds", "interrupted_reason", "sets", "control_events",
        }
        assert expected <= _fields(Session)

    def test_exercise_set_fields(self):
        expected = {
            "id", "session_id", "ordinal", "exercise_key", "exercise_name", "side",
            "target_reps", "up_angle", "down_angle", "start_time", "end_time",
            "reps", "partial_reps", "form_events", "samples",
        }
        assert expected <= _fields(ExerciseSet)
        assert {"exercise_key", "exercise_name", "side", "target_reps", "up_angle", "down_angle"} <= _fields(ExerciseSetInfo)

    def test_event_fields(self):
        assert {"rep_number", "min_angle", "max_angle", "rom", "duration_seconds", "form_score",
                "timestamp", "frame_num", "out_of_range"} <= _fields(RepEvent)
        assert {"reason", "min_angle", "max_angle", "rom", "duration_seconds", "timestamp",
                "frame_num"} <= _fields(PartialRepEvent)
        assert {"severity", "status", "message", "body_part", "timestamp", "frame_num"} <= _fields(FormEvent)
        assert {"kind", "from_exercise", "to_exercise", "rep_count_at_reset", "timestamp",
                "frame_num"} <= _fields(ControlEvent)
        assert {"frame_num", "timestamp", "angle", "state", "rep_count"} <= _fields(FrameSample)

    def test_read_model_fields(self):
        assert {"id", "patient_id", "start_time", "source", "status", "exercises", "total_reps",
                "avg_form_score"} <= _fields(SessionSummaryRow)
        assert {"type", "timestamp", "frame_num", "set_ordinal", "data"} <= _fields(LogRow)
        assert {"patient_id", "sessions", "events", "export_files"} <= _fields(DeleteReport)
        assert {"file_sha256", "source_path", "session_id", "outcome", "imported_at"} <= _fields(LedgerRow)


class TestEnums:
    def test_restricted_values(self):
        assert models.SESSION_STATUSES == ("running", "completed", "interrupted")
        assert models.SIDES == ("left", "right", "bilateral")
        assert models.PARTIAL_REASONS == ("insufficient_rom", "reversed_early", "interrupted")
        assert models.SEVERITIES == ("suggestion", "warning", "stop")
        assert models.CONTROL_KINDS == ("switch", "reset")


class TestMetricDefinitions:
    NUMERIC_FIELDS = [
        "min_angle", "max_angle", "rom", "duration_seconds", "form_score",
        "avg_form_score", "avg_rom", "total_reps", "angle", "target_reps",
    ]

    @pytest.mark.parametrize("field", NUMERIC_FIELDS)
    def test_every_numeric_field_has_unit_and_definition(self, field):
        entry = METRIC_DEFINITIONS[field]
        assert entry["unit"].strip()
        assert len(entry["definition"].strip()) > 10


class TestOutOfRange:
    def _rep(self, **kw):
        base = dict(rep_number=1, min_angle=10.0, max_angle=88.0, rom=78.0,
                    duration_seconds=3.0, form_score=95.0, timestamp="2026-03-23T09:15:08", frame_num=240)
        base.update(kw)
        return RepEvent(**base)

    def test_normal_rep_in_range(self):
        assert self._rep().out_of_range == 0

    def test_negative_duration_flagged(self):
        assert self._rep(duration_seconds=-0.5).out_of_range == 1

    def test_form_score_above_100_flagged(self):
        assert self._rep(form_score=101.0).out_of_range == 1

    def test_form_score_below_0_flagged(self):
        assert self._rep(form_score=-1.0).out_of_range == 1

    def test_rom_above_180_flagged(self):
        assert self._rep(rom=190.0).out_of_range == 1

    def test_rom_boundaries_in_range(self):
        assert self._rep(rom=0.0).out_of_range == 0
        assert self._rep(rom=180.0).out_of_range == 0


class TestExceptions:
    def test_exception_hierarchy(self):
        for name in ("PatientValidationError", "DuplicatePatientError", "BuiltinPatientError",
                     "PatientNotFoundError", "SessionNotFoundError"):
            exc = getattr(models, name)
            assert issubclass(exc, models.PTLogError)
            assert issubclass(exc, Exception)
