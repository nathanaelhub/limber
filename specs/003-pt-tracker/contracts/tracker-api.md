# Contract: programs, adherence, tracker modules and store API

**Feature**: 003-pt-tracker

## programs.py

```python
def load_catalog(config_path: Path | None = None) -> Catalog   # cached per path; Catalog(exercises: dict, programs: dict[str, Program])
def list_programs(config_path=None) -> list[Program]
def get_program(program_id, config_path=None) -> Program | None
def exercise_name(key, config_path=None) -> str                 # display name or the key itself
def validate_exercise_keys(keys: list[str], config_path=None) -> list[str]   # raises ProgramValidationError naming unknown keys; rejects empty
def custom_program(keys) -> Program                            # id "custom", name "Custom"
```

## adherence.py (pure)

```python
def assignment_status(a: Assignment, today: date) -> str       # superseded | scheduled | completed | active
def week_bounds(a: Assignment, index: int) -> tuple[date, date]
def week_index(a: Assignment, on: date) -> int
def compute(a: Assignment | None, sessions: list[Session], today: date, window_weeks: int = 4) -> Adherence
```

## tracker.py

```python
def snapshot(store, patient: Patient, now: datetime) -> PatientSnapshot   # one load per patient (research D6)
def roster(store, now=None, sort="attention", program: str | None = None, needs_attention=False) -> list[RosterRow]
def attention_key(row: RosterRow) -> tuple
def queue(store, now=None) -> QueueResult
def adherence_for(store, patient_id, today=None) -> Adherence
```

## store.py additions

```python
# migration 3 applied on open(); SCHEMA_VERSION = 3
def assign_program(self, patient_id, program_id, program_name, exercise_keys, sessions_per_week=3,
                   start_date: date | str | None = None, end_date=None) -> Assignment   # supersedes; validates; builtin refused
def active_assignment(self, patient_id, on: date | None = None) -> Assignment | None   # start <= on and (end is null or end >= on)
def assignment_history(self, patient_id) -> list[Assignment]        # newest start first
def discharge(self, patient_id, on: date | None = None, reason=None) -> Discharge   # validate_notes(reason); builtin refused
def reactivate(self, patient_id) -> bool
def get_discharge(self, patient_id) -> Discharge | None
def active_patients(self) -> list[Patient]                         # not discharged, unassigned first
def discharged_patients(self) -> list[tuple[Patient, Discharge]]
def get_adherence_threshold(self) -> int
def set_adherence_threshold(self, value) -> int                    # 1-100
def latest_review(self, patient_id) -> Review | None               # by session start time
```

## exports

```python
def to_roster_csv(rows: list[RosterRow], generated_at: datetime) -> str
def write_roster_export(store, out_dir=None, now=None) -> Path      # roster_<YYYYMMDD_HHMMSS>.csv
```

## Errors

`ProgramValidationError`, `AssignmentValidationError` (both `PTLogError`); `BuiltinPatientError`
reused for assign/discharge of the built-in patient.
