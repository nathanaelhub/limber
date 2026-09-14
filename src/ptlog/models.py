"""
Data model for the canonical PT session log.

Every numeric field documents its unit and a plain-language definition (constitution V,
FR-012). The same text is exposed through METRIC_DEFINITIONS so interfaces can label
metrics without restating them. Timestamps are ISO 8601 local-time strings, exactly as
the retired loggers wrote them, so exports can reproduce legacy files byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------------------
# Restricted vocabularies (data-model.md)
# --------------------------------------------------------------------------------------

SESSION_STATUSES = ("running", "completed", "interrupted")
SOURCES = ("webcam", "video")
SIDES = ("left", "right", "bilateral")
PARTIAL_REASONS = ("insufficient_rom", "reversed_early", "interrupted")
SEVERITIES = ("suggestion", "warning", "stop")
CONTROL_KINDS = ("switch", "reset")
EXPORT_FORMATS = ("pta_log", "observation_json", "csv_report", "text_log")
LEDGER_OUTCOMES = ("imported", "duplicate", "malformed")

UNASSIGNED_ID = "unassigned"
UNASSIGNED_LABEL = "Unassigned"

# --------------------------------------------------------------------------------------
# Units and definitions shown to clinicians
# --------------------------------------------------------------------------------------

METRIC_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "angle": {
        "unit": "degrees",
        "definition": "The joint angle measured by the pose model at that moment, after smoothing.",
    },
    "min_angle": {
        "unit": "degrees",
        "definition": "The smallest joint angle reached during the repetition.",
    },
    "max_angle": {
        "unit": "degrees",
        "definition": "The largest joint angle reached during the repetition.",
    },
    "rom": {
        "unit": "degrees",
        "definition": "Range of motion: the largest angle minus the smallest angle in the repetition.",
    },
    "duration_seconds": {
        "unit": "seconds",
        "definition": "Time from the start of the repetition to its completion.",
    },
    "form_score": {
        "unit": "score 0-100",
        "definition": "Quality of the repetition: 40% range achieved, 30% smoothness, 30% symmetry of the up and down phases.",
    },
    "avg_form_score": {
        "unit": "score 0-100",
        "definition": "Mean form score across the completed repetitions in the session.",
    },
    "avg_rom": {
        "unit": "degrees",
        "definition": "Mean range of motion across the completed repetitions in the session.",
    },
    "total_reps": {
        "unit": "count",
        "definition": "Number of repetitions that reached both movement thresholds and were counted.",
    },
    "target_reps": {
        "unit": "count",
        "definition": "Number of repetitions prescribed for the exercise set.",
    },
    "rep_number": {
        "unit": "count",
        "definition": "Position of the repetition within its exercise set, starting at 1.",
    },
    "rep_count": {
        "unit": "count",
        "definition": "Running number of repetitions counted so far in the set.",
    },
    "frame_num": {
        "unit": "frame index",
        "definition": "Index of the camera or video frame at which the event was observed.",
    },
    "up_angle": {
        "unit": "degrees",
        "definition": "Joint angle the exercise treats as the extended or raised position.",
    },
    "down_angle": {
        "unit": "degrees",
        "definition": "Joint angle the exercise treats as the flexed or lowered position.",
    },
    "session_duration_seconds": {
        "unit": "seconds",
        "definition": "Time from the first to the last moment of the session.",
    },
}


# --------------------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------------------

class PTLogError(Exception):
    """Base class for canonical-record errors."""


class PatientValidationError(PTLogError):
    """A patient ID or label violates the pseudonymity or format rules."""


class DuplicatePatientError(PTLogError):
    """The patient ID is already registered (case-insensitive)."""


class BuiltinPatientError(PTLogError):
    """The built-in 'unassigned' patient cannot be deleted."""


class PatientNotFoundError(PTLogError):
    """No patient with that ID exists."""


class SessionNotFoundError(PTLogError):
    """No session with that ID exists."""


# --------------------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------------------

@dataclass
class Patient:
    """A person receiving therapy, known only by a pseudonymous ID."""
    id: str
    label: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = ""
    is_builtin: bool = False
    session_count: int = 0
    last_session_at: Optional[str] = None


@dataclass
class ExerciseSetInfo:
    """What the recorder knows about an exercise when a set opens."""
    exercise_key: str          # config key, e.g. "knee_extension_right"
    exercise_name: str         # display name, e.g. "Knee Extension (Right)"
    side: str                  # left | right | bilateral
    target_reps: int           # count
    up_angle: float            # degrees, engine threshold at set start
    down_angle: float          # degrees, engine threshold at set start


@dataclass
class RepEvent:
    """One counted repetition. Source: RepMetrics from the engine."""
    rep_number: int            # count, 1-based within the set
    min_angle: float           # degrees
    max_angle: float           # degrees
    rom: float                 # degrees, max_angle - min_angle
    duration_seconds: float    # seconds
    form_score: float          # score 0-100
    timestamp: str             # ISO 8601
    frame_num: int = 0         # frame index
    out_of_range: int = 0      # 1 when a value is physically impossible; excluded from averages
    id: Optional[int] = None
    set_id: Optional[int] = None

    def __post_init__(self) -> None:
        self.out_of_range = int(
            self.duration_seconds < 0
            or not (0 <= self.form_score <= 100)
            or not (0 <= self.rom <= 180)
        )


@dataclass
class PartialRepEvent:
    """An attempted repetition that did not count. Source: PartialRepMetrics."""
    reason: str                # insufficient_rom | reversed_early | interrupted
    min_angle: float           # degrees
    max_angle: float           # degrees
    rom: float                 # degrees
    duration_seconds: float    # seconds
    timestamp: str             # ISO 8601
    frame_num: int = 0
    id: Optional[int] = None
    set_id: Optional[int] = None


@dataclass
class FormEvent:
    """A feedback message from the form analyzer."""
    severity: str              # suggestion | warning | stop
    status: str                # engine FormStatus value: warning | poor | stop
    message: str
    timestamp: str             # ISO 8601
    frame_num: int = 0
    body_part: Optional[str] = None
    id: Optional[int] = None
    set_id: Optional[int] = None


@dataclass
class ControlEvent:
    """An exercise switch or a counter reset."""
    kind: str                  # switch | reset
    timestamp: str             # ISO 8601
    frame_num: int = 0
    from_exercise: Optional[str] = None
    to_exercise: Optional[str] = None
    rep_count_at_reset: Optional[int] = None
    id: Optional[int] = None
    session_id: Optional[int] = None


@dataclass
class FrameSample:
    """A downsampled angle observation (every 15th inference frame with a detected angle)."""
    frame_num: int             # frame index
    timestamp: str             # ISO 8601
    angle: float               # degrees
    state: str                 # up | down | idle | neutral
    rep_count: int             # count
    set_id: Optional[int] = None


@dataclass
class ExerciseSet:
    """A run of one exercise within a session."""
    id: int
    session_id: int
    ordinal: int
    exercise_key: str
    exercise_name: str
    side: str
    target_reps: int
    up_angle: float
    down_angle: float
    start_time: str
    end_time: Optional[str] = None
    reps: List[RepEvent] = field(default_factory=list)
    partial_reps: List[PartialRepEvent] = field(default_factory=list)
    form_events: List[FormEvent] = field(default_factory=list)
    samples: List[FrameSample] = field(default_factory=list)


@dataclass
class Session:
    """One continuous exercise period for one patient from one source."""
    id: int
    patient_id: str
    schema_version: int
    source: str                          # webcam | video
    source_ref: str                      # camera index or video file name
    status: str                          # running | completed | interrupted
    start_time: str
    end_time: Optional[str] = None
    source_extras: Optional[Dict[str, Any]] = None   # webcam: camera_id, imgsz, frame_skip
    total_reps: Optional[int] = None     # count
    avg_form_score: Optional[float] = None  # score 0-100, NULL when no counted reps
    avg_rom: Optional[float] = None      # degrees, NULL when no counted reps
    duration_seconds: Optional[float] = None  # seconds
    interrupted_reason: Optional[str] = None
    sets: List[ExerciseSet] = field(default_factory=list)
    control_events: List[ControlEvent] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Read models and reports
# --------------------------------------------------------------------------------------

@dataclass
class SessionSummaryRow:
    """One line in a patient's history list."""
    id: int
    patient_id: str
    start_time: str
    end_time: Optional[str]
    source: str
    status: str
    exercises: List[str]
    total_reps: Optional[int]
    avg_form_score: Optional[float]


@dataclass
class LogRow:
    """One row of the chronological event log view."""
    type: str                  # session_start | rep | partial_rep | form | switch | reset | session_end
    timestamp: str
    frame_num: int
    set_ordinal: Optional[int]
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeleteReport:
    patient_id: str
    sessions: int = 0
    events: int = 0
    export_files: int = 0


@dataclass
class LedgerRow:
    file_sha256: str
    source_path: str
    session_id: Optional[int]
    outcome: str               # imported | duplicate | malformed
    imported_at: str = ""
    reason: Optional[str] = None
