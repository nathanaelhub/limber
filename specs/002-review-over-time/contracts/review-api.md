# Contract: review modules and store API

**Feature**: 002-review-over-time

## measures.py (pure)

```python
def measures_for_session(session: Session) -> dict[str, SessionMeasure]   # keyed by exercise name
def measure_series(sessions: list[Session], exercise: str) -> list[SessionMeasure]  # oldest first, only sessions holding the exercise
```

Rules: reps = counted reps with `out_of_range == 0` across all sets of that exercise; target =
last set's target; averages rounded to 1 decimal; durations and tempo_sd to 2 decimals;
partial_share to 1 decimal; None where the spec says "not available".

## flags.py (pure)

```python
def evaluate(series_by_exercise: dict[str, list[SessionMeasure]], goals: dict[str, Goal],
             session_starts: list[str], gap_days: int, now: datetime) -> FlagResult   # session_starts: ISO start times of every session in the period
# rule functions, each -> Flag | None | NotEvaluated:
def form_declining(series) ; def rom_regression(series) ; def rom_plateau(series, goal)
def target_reps_not_reached(series) ; def rising_partial_reps(series)
def safety_stops(series) -> list[Flag] ; def practice_gap(session_starts: list[str], gap_days, now) -> list[Flag]
```

Thresholds (FR-014): windows 4/4/4/3/4; form drop 10 points; ROM regression 10°; plateau
< 3° change; partial share ≥ 25% and ≥ 10 points above the previous three's mean.
Every `Flag.message` names the sessions (by id and date) and the numbers used.

## review.py

```python
PERIODS = {"14d": 14, "30d": 30, "90d": 90, "all": None}
def period_start(period: str, now: datetime) -> datetime | None
def trend(store, patient_id, exercise, period="all", now=None) -> Trend
def flags_for(store, patient_id, period="all", now=None) -> FlagResult
def compare(store, session_a: int, session_b: int, exercise: str | None = None) -> Comparison   # raises ComparisonError
def pending(store, patient_id) -> list[SessionSummaryRow]                                     # newest first
def session_review_view(store, session_id) -> dict   # {"session", "measures", "summary": generate_session_summary(...), "review"}
def review_summary(store, patient_id, period="all", now=None) -> ReviewSummary
```

## store.py additions

```python
# migration 2 applied on open(); SCHEMA_VERSION = 2
def set_review(self, session_id, next_step, notes=None) -> Review        # validates; INSERT OR REPLACE; reviewed_at = now
def get_review(self, session_id) -> Review | None
def pending_reviews(self, patient_id) -> list[SessionSummaryRow]
def set_goal(self, patient_id, exercise_name, target_rom=None, target_reps=None) -> Goal   # None keeps the existing value
def get_goal(self, patient_id, exercise_name) -> Goal | None
def list_goals(self, patient_id) -> list[Goal]
def clear_goal(self, patient_id, exercise_name) -> bool
def get_gap_days(self, patient_id) -> int                                # default 7
def set_gap_days(self, patient_id, days) -> int
def sessions_in_period(self, patient_id, since: datetime | None) -> list[Session]   # full graphs, oldest first
def exercise_names(self, patient_id) -> list[str]                        # distinct, first-seen order
def record_review_export(self, patient_id, fmt, period, path) -> int
# delete_patient also unlinks review_exports paths and counts them in DeleteReport.export_files
```

## privacy.py addition

```python
def validate_notes(value: str | None) -> str | None   # same three patterns as labels; no length cap; "" -> None
```

## exports

```python
def to_review_report(summary: ReviewSummary) -> str
def to_review_csv(summary: ReviewSummary) -> str
def write_review_export(store, patient_id, period, fmt, out_dir=None, now=None) -> Path
# file name: {patient_id}_review_{period}_{YYYYMMDD_HHMMSS}.{txt|csv}
```

## Errors

`GoalValidationError`, `ComparisonError`, `ReviewValidationError` (all `PTLogError`).
