# Data Model: Live Web Session Recording

**Feature**: 004-live-session-recording. **No schema change.** Sessions recorded from the page
are ordinary rows in the feature-001 tables (schema version stays 3).

## Runtime entities (not stored)

### LiveSession (src/live_session.py)

| Field | Meaning |
|-------|---------|
| store | `SessionStore` opened with `check_same_thread=False` |
| recorder | `SessionRecorder` bound to the store |
| session_id | id of the running session (set by `start`) |
| exercises | `analyze.load_config()` result |
| exercise_key / config | current exercise |
| tracker | `ExerciseTracker(config, fps)` |
| form_analyzer | `FormAnalyzer(base_exercise)` |
| frame_num | frames processed so far |
| last_assessment | latest `OverallFormAssessment` |
| last_metrics | latest dict from `tracker.update()` plus form status and messages |
| last_frame | latest annotated frame (for screenshots) |
| ended | True after `end()` |

State: `created → started (session running) → ended (session completed)`; an abandoned
`started` becomes `interrupted` through the store's recovery on next open.

### LiveVideoProcessor (interfaces/app.py)

Attributes set by the page before frames flow: `patient_id`, `exercise_key`, `target_reps`,
`camera_label`, `db_path`. Runtime: `live` (LiveSession or None), `pending_switch`,
`pending_reset`, `session_id`, `last_frame`, `error` (message when recording failed).

### Recorded session

Same as feature 001: `source = "webcam"`, `source_ref = <camera label>`,
`source_extras = {"camera_id": <label>, "imgsz": 320, "frame_skip": 1, "origin": "web", "pid": <process id>}`.

## Store behaviour changes (no schema change)

- `SessionStore(db_path, clock, check_same_thread=True)`: the flag is passed to `sqlite3.connect`.
- Recovery on open skips a running session whose `source_extras.pid` names a living process (research D11).
- `interrupt_session(session_id, reason)`: marks one running session interrupted (no-op otherwise).

## Validation rules

- `target_reps` 1–100 on the page (number input).
- Unknown exercise key → `ValueError` from `LiveSession`.
- `end()` after `end()` is a no-op returning the same session.
