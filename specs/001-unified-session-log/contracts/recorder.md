# Contract: SessionStore and SessionRecorder

**Feature**: 001-unified-session-log | Python module: `src/ptlog`

## SessionStore (`src/ptlog/store.py`) — the single writer

```python
class SessionStore:
    def __init__(self, db_path: Path, clock: Callable[[], datetime] = datetime.now): ...
    def open(self) -> "SessionStore"          # applies migrations, recovers running sessions
    def close(self) -> None
    # patients
    def add_patient(self, patient_id: str, label: str | None = None, notes: str | None = None) -> Patient
    def update_patient(self, patient_id: str, label: str | None, notes: str | None) -> Patient
    def list_patients(self) -> list[Patient]          # includes 'unassigned' first
    def get_patient(self, patient_id: str) -> Patient | None
    def delete_patient(self, patient_id: str) -> DeleteReport   # cascades; removes export files
    # sessions (write)
    def start_session(self, patient_id: str, source: str, source_ref: str) -> int
    def open_set(self, session_id: int, exercise: ExerciseSetInfo) -> int
    def close_set(self, set_id: int) -> None
    def add_rep(self, set_id: int, rep: RepEvent) -> int
    def add_partial_rep(self, set_id: int, partial: PartialRepEvent) -> int
    def add_form_event(self, set_id: int, event: FormEvent) -> int
    def add_control_event(self, session_id: int, event: ControlEvent) -> int
    def add_frame_samples(self, set_id: int, samples: list[FrameSample]) -> None   # one txn
    def end_session(self, session_id: int) -> Session            # computes + stores summary
    def reassign_session(self, session_id: int, patient_id: str) -> None
    # sessions (read)
    def list_sessions(self, patient_id: str | None = None) -> list[SessionSummaryRow]  # newest first
    def load_session(self, session_id: int) -> Session           # full object graph
    def event_log(self, session_id: int) -> list[LogRow]         # ordered union view
    # exports / imports bookkeeping
    def record_export(self, session_id: int, fmt: str, path: Path) -> None
    def ledger_lookup(self, sha256: str) -> LedgerRow | None
    def ledger_add(self, row: LedgerRow) -> None
```

Guarantees:

- Every `add_*` and `start_session`/`end_session` call commits before returning
  (`synchronous=FULL`), except `add_frame_samples`, which commits once per call.
- `open()` sets any `running` session to `interrupted`, fills `end_time` from the last event,
  and stores a summary computed from events (FR-011).
- `add_patient` raises `PatientValidationError` with a human-readable reason on any FR-013 or
  FR-014 violation, and `DuplicatePatientError` on a case-insensitive ID collision.
- `delete_patient('unassigned')` raises `BuiltinPatientError`.
- `delete_patient` returns counts of sessions, events, and export files removed.
- Reads never block on the writer (WAL). All methods are safe to call from the Streamlit
  process while a CLI session is recording.

## SessionRecorder (`src/ptlog/recorder.py`) — the only engine adapter

```python
class SessionRecorder:
    def __init__(self, store: SessionStore, clock: Callable[[], datetime] = datetime.now,
                 sample_every: int = 15, form_throttle_frames: int = 60,
                 form_throttle_seconds: float = 2.0): ...
    def start(self, patient_id: str | None, source: str, source_ref: str,
              exercise_config: ExerciseConfig,
              extras: dict | None = None) -> int                  # returns session_id; extras → sessions.source_extras
    def observe(self, tracker: ExerciseTracker, metrics: dict, angle: float | None,
                frame_num: int, assessment: OverallFormAssessment | None) -> None
    def switch(self, new_exercise_config: ExerciseConfig, tracker: ExerciseTracker) -> None
    def reset(self, tracker: ExerciseTracker) -> None
    def end(self, session: ExerciseSession) -> Session
    @property
    def session_id(self) -> int | None
```

What `observe()` reads, and nothing else (constitution I):

| Input | Engine source | Used for |
|-------|---------------|----------|
| `metrics["rep_count"]`, `metrics["current_angle"]` | return of `ExerciseTracker.update()` | frame samples, rep delta |
| `tracker.current_state` | public attribute | frame sample `state` |
| `tracker.session.rep_metrics` | `ExerciseSession` (public output) | new `RepMetrics` since last call |
| `tracker.session.partial_rep_metrics` | `ExerciseSession` | new `PartialRepMetrics` since last call |
| `assessment.status`, `assessment.feedback_messages[0]` | `OverallFormAssessment` | form events |
| `exercise_config.name/side/target_reps/up_angle/down_angle` | `ExerciseConfig` | set metadata |

Behaviour:

- A `RepMetrics` appended to `tracker.session.rep_metrics` since the previous `observe()`
  becomes one `reps` row, with `frame_num` of the observing frame.
- A new `PartialRepMetrics` becomes one `partial_reps` row.
- Form events are stored only when `assessment.status.value in {"warning","poor","stop"}`,
  at most once per `form_throttle_frames` frames, and never with an identical message within
  `form_throttle_seconds` for the same set (FR-007).
- Every `sample_every`-th frame with `angle is not None` buffers a `FrameSample`; the buffer
  flushes on any event and at least once per second.
- `switch()` closes the current set, writes a `switch` control event, opens a new set, and
  resets the delta counters; partial reps recorded by the engine at switch time (reason
  `interrupted`) are captured on the next `observe()` or by `switch()` itself.
- `reset()` writes a `reset` control event with `tracker.rep_count` and resets delta counters.
- `end()` flushes samples, closes the open set, and calls `store.end_session()`; the returned
  `Session` summary MUST equal `ExerciseSession.total_reps/avg_form_score/avg_rom` to one
  decimal for a normal session (parity check in tests).
- If the store raises (disk full, read-only), the recorder logs the failure once via the
  standard `logging` module, sets `degraded=True`, and swallows further store errors so the
  on-screen session continues (edge case). `end()` re-raises the first error so the CLI can
  warn the user.

## Call-site contract in `analyze.py`

The webcam and video loops each become:

```python
recorder = SessionRecorder(store)
recorder.start(patient_id, "webcam", str(camera_id), exercise_config)   # or ("video", filename)
...
metrics = tracker.update(angle)
recorder.observe(tracker, metrics, angle, frame_num, last_assessment)
...
# 'n' key: recorder.switch(exercise_config, tracker)
# 'r' key: recorder.reset(tracker)
...
session = tracker.finalize_session()
recorder.end(session)
```

No other line in the loops changes. The engine classes are not edited.

## Export functions (`src/ptlog/exports/*.py`) — pure functions

```python
def to_pta_log_text(session: Session, samples: list[FrameSample], ordinal: int) -> str
def to_observation_dict(session: Session) -> dict      # exact legacy shape; feeds session_summary
def to_observation_json(session: Session) -> str        # json.dumps(dict, indent=2)
def to_csv_report(session: Session) -> str
def to_text_log(session: Session) -> list[str]          # one string per 50-line legacy file
def write_export(store, session_id: int, fmt: str, out_dir: Path) -> Path   # names + records
```

Each function depends only on its arguments and the format specification in `exports.md`.
