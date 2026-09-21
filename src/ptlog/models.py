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


# --------------------------------------------------------------------------------------
# Review over time (feature 002)
# --------------------------------------------------------------------------------------

NEXT_STEPS = ("continue", "progress", "regress", "hold")
PERIODS: Dict[str, Optional[int]] = {"14d": 14, "30d": 30, "90d": 90, "all": None}
REVIEW_EXPORT_FORMATS = ("review_report", "review_csv")
GAP_DAYS_DEFAULT = 7

METRIC_DEFINITIONS.update({
    "reps_completed": {
        "unit": "count",
        "definition": "Counted repetitions of the exercise in the session, excluding any flagged as out of range.",
    },
    "avg_form": {
        "unit": "score 0-100",
        "definition": "Mean form score of the counted repetitions of the exercise in the session.",
    },
    "avg_duration": {
        "unit": "seconds",
        "definition": "Mean time per counted repetition of the exercise in the session.",
    },
    "tempo_sd": {
        "unit": "seconds",
        "definition": "Tempo consistency: the spread (population standard deviation) of repetition durations; lower is steadier.",
    },
    "partial_share": {
        "unit": "percent",
        "definition": "Partial repetitions as a share of all attempts (partial plus counted) for the exercise in the session.",
    },
})


class GoalValidationError(PTLogError):
    """A goal target is out of range or no target was given."""


class ComparisonError(PTLogError):
    """Two sessions cannot be compared (no common exercise, or several without a choice)."""


class ReviewValidationError(PTLogError):
    """A review's next step or notes are invalid."""


@dataclass
class Review:
    """The PT's review of one session (one per session; edits replace it)."""
    session_id: int
    reviewed_at: str
    notes: Optional[str]
    next_step: str            # continue | progress | regress | hold


@dataclass
class Goal:
    """A target per patient and exercise."""
    patient_id: str
    exercise_name: str
    target_rom: Optional[float]     # degrees, 1-180
    target_reps: Optional[int]      # count, >= 1
    set_at: str


@dataclass
class ReviewSettings:
    patient_id: str
    gap_days: int = GAP_DAYS_DEFAULT   # days, 1-90


@dataclass
class SessionMeasure:
    """Per-session, per-exercise figures derived from recorded reps (never stored)."""
    session_id: int
    patient_id: str
    start_time: str
    status: str
    interrupted: bool
    exercise_name: str
    reps_completed: int              # count
    target_reps: int                 # count
    avg_rom: Optional[float]         # degrees
    avg_form: Optional[float]        # score 0-100
    avg_duration: Optional[float]    # seconds
    tempo_sd: Optional[float]        # seconds
    partial_count: int               # count
    partial_share: Optional[float]   # percent
    safety_stops: List[tuple] = field(default_factory=list)   # (timestamp, message)


@dataclass
class Flag:
    rule: str
    exercise: Optional[str]
    session_ids: List[int]
    values: Dict[str, Any]
    message: str


@dataclass
class NotEvaluated:
    rule: str
    exercise: Optional[str]
    needed: int
    have: int


@dataclass
class FlagResult:
    flags: List[Flag] = field(default_factory=list)
    not_evaluated: List[NotEvaluated] = field(default_factory=list)


@dataclass
class Trend:
    exercise: str
    period: str
    points: List[SessionMeasure] = field(default_factory=list)
    summary: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)   # measure -> first/latest/change
    goal: Optional[Goal] = None
    rom_progress_pct: Optional[int] = None
    enough_for_trend: bool = False


@dataclass
class ComparisonRow:
    name: str
    unit: str
    a: Optional[float]
    b: Optional[float]
    change: Optional[float]
    pct_change: Optional[float]
    better: str                      # higher | lower | informational


@dataclass
class Comparison:
    exercise: str
    a: SessionMeasure
    b: SessionMeasure
    rows: List[ComparisonRow] = field(default_factory=list)


@dataclass
class ReviewSummary:
    patient_id: str
    period: str
    period_start: Optional[str]
    generated_at: str
    gap_days: int
    trends: Dict[str, Trend] = field(default_factory=dict)
    thresholds: Any = None        # the patient's effective attention thresholds (thresholds.Thresholds)
    exercise_thresholds: Dict[str, Any] = field(default_factory=dict)   # exercises with their own overrides
    flags: FlagResult = field(default_factory=FlagResult)
    goals: List[Dict[str, Any]] = field(default_factory=list)      # {"goal": Goal, "latest_rom", "progress_pct", "latest_reps"}
    sessions: List[Dict[str, Any]] = field(default_factory=list)   # newest first: {"session", "measures", "review"}


# --------------------------------------------------------------------------------------
# Multi-patient tracker (feature 003)
# --------------------------------------------------------------------------------------

ASSIGNMENT_STATUSES = ("scheduled", "active", "completed", "superseded")
QUEUE_KINDS = ("pending_review", "attention_flag", "practice_gap", "low_adherence")
ADHERENCE_THRESHOLD_DEFAULT = 60

METRIC_DEFINITIONS.update({
    "adherence_pct": {
        "unit": "percent",
        "definition": "Recorded sessions (capped at the plan each week) divided by planned sessions over the last four complete assignment weeks.",
    },
    "sessions_per_week": {
        "unit": "count",
        "definition": "Number of sessions the assigned program plans for each seven-day assignment week.",
    },
})


# --------------------------------------------------------------------------------------
# Patient portal (feature 007)
# --------------------------------------------------------------------------------------

class PortalError(PTLogError):
    """A patient-portal rule was broken (who may get a code, sign-in, frames, live sessions)."""


@dataclass
class AccessStatus:
    """A patient's home access. state: none | active | expired | revoked. The code itself is never stored."""
    patient_id: str
    state: str
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    last_used_at: Optional[str] = None


@dataclass
class PortalSignIn:
    """One open sign-in of a patient on one device."""
    patient_id: str
    created_at: str
    last_seen_at: str
    expires_at: str


@dataclass
class AuditEntry:
    """One line of the portal's access history. `client` is a keyed hash, never an address."""
    id: int
    at: str
    patient_id: Optional[str]
    event: str
    client: Optional[str] = None
    detail: Optional[str] = None


@dataclass
class ThresholdChange:
    """One change of a stored attention threshold. None = no stored value (the inherited value applies)."""
    id: int
    changed_at: str                      # ISO 8601
    scope: str                           # patient | exercise | installation
    patient_id: Optional[str]
    exercise_name: Optional[str]
    key: str
    old_value: Optional[int]
    new_value: Optional[int]


class ThresholdValidationError(PTLogError):
    """An attention threshold key is unknown or its value is outside the allowed range."""


class ProgramValidationError(PTLogError):
    """An exercise key is unknown or a program has no exercises."""


class AssignmentValidationError(PTLogError):
    """Sessions per week or dates of an assignment are out of range."""


@dataclass
class Program:
    """A named, ordered list of exercise keys (pre-built from the configuration, or custom)."""
    id: str
    name: str
    description: str
    exercise_keys: List[str]
    exercise_names: List[str] = field(default_factory=list)


@dataclass
class Assignment:
    """A program assigned to a patient with a plan and dates; status is derived, not stored."""
    id: int
    patient_id: str
    program_id: str
    program_name: str
    exercise_keys: List[str]
    sessions_per_week: int          # count, 1-14
    start_date: str                 # YYYY-MM-DD
    end_date: Optional[str]         # YYYY-MM-DD or None
    created_at: str


@dataclass
class Discharge:
    patient_id: str
    discharged_on: str              # YYYY-MM-DD
    reason: Optional[str]
    created_at: str


@dataclass
class AdherenceWeek:
    index: int                      # 1-based assignment week
    start: str                      # YYYY-MM-DD inclusive
    end: str                        # YYYY-MM-DD inclusive
    planned: int                    # count
    recorded: int                   # count of sessions with at least one counted rep
    counted: int                    # min(recorded, planned)
    exercises_performed: List[str] = field(default_factory=list)
    exercises_missing: List[str] = field(default_factory=list)
    missed: bool = False
    in_progress: bool = False


@dataclass
class Adherence:
    assignment: Optional[Assignment]
    status: str                     # none | scheduled | active | completed | superseded
    weeks: List[AdherenceWeek] = field(default_factory=list)
    percentage: Optional[int] = None    # percent over complete weeks
    note: str = ""


@dataclass
class RosterRow:
    patient_id: str
    label: Optional[str]
    is_builtin: bool
    program_id: Optional[str]
    program_name: str               # display name or "none"
    program_status: str             # none | scheduled | active | completed | superseded
    days_since_last: Optional[int]  # days; None when no sessions
    sessions_7d: int
    sessions_30d: int
    adherence_pct: Optional[int]
    adherence_note: str
    pending_reviews: int
    open_flags: int                 # flags from every rule except practice gap, last 30 days
    practice_gap: bool
    last_next_step: Optional[str]
    needs_attention: bool


@dataclass
class QueueItem:
    kind: str                       # pending_review | attention_flag | practice_gap | low_adherence
    patient_id: str
    target: str                     # session:<id> | flags:<patient> | adherence:<patient>
    session_id: Optional[int]
    age_days: int
    description: str


@dataclass
class QueueResult:
    items: Dict[str, List[QueueItem]] = field(default_factory=dict)   # kind -> items, QUEUE_KINDS order
    totals: Dict[str, int] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return sum(self.totals.values())


@dataclass
class TrackerSettings:
    adherence_threshold: int = ADHERENCE_THRESHOLD_DEFAULT
