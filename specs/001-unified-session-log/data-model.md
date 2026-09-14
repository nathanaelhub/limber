# Data Model: Unified PT Session Log

**Feature**: 001-unified-session-log | **Date**: 2026-09-14 | Schema version: 1

All tables live in one SQLite file. Timestamps are ISO 8601 local time with microseconds
(TEXT). Every numeric column lists its unit; the same unit and definition text is carried in
the `models.py` docstrings and shown in the UI (constitution V, FR-012).

## Entities

### patients

| Column | Type | Rules |
|--------|------|-------|
| id | TEXT PK | pseudonymous ID, `^[A-Za-z0-9-]{1,32}$`, unique case-insensitive (COLLATE NOCASE) |
| label | TEXT NULL | up to 60 chars, PHI heuristics rejected (D7) |
| notes | TEXT NULL | free text |
| created_at | TEXT | timestamp |
| is_builtin | INTEGER | 1 only for the `unassigned` row, which cannot be deleted (FR-015) |

The built-in patient's id is `unassigned`; the spec's "Unassigned" is its display label.

Definition: a person receiving therapy, known only by a pseudonymous ID.

### sessions

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | autoincrement |
| patient_id | TEXT FK → patients.id | ON DELETE CASCADE; reassignable (FR-016) |
| schema_version | INTEGER | version the row was written under |
| source | TEXT | `webcam` or `video` |
| source_ref | TEXT | camera index or video file name (never a patient identifier) |
| source_extras | TEXT NULL | JSON object; webcam sessions store `camera_id`, `imgsz`, `frame_skip` so the text-log export can rebuild its `SESSION START` line; NULL for video |
| status | TEXT | `running` → `completed` or `interrupted` (see State Transitions) |
| start_time | TEXT | timestamp |
| end_time | TEXT NULL | set on completion; on interruption set to last event timestamp |
| total_reps | INTEGER NULL | count, summary field |
| avg_form_score | REAL NULL | 0-100, mean of completed-rep form scores; NULL when no reps |
| avg_rom | REAL NULL | degrees, mean of completed-rep ROM; NULL when no reps |
| duration_seconds | REAL NULL | seconds, end_time − start_time |
| interrupted_reason | TEXT NULL | e.g. `recovered_on_open` |

Definition: one continuous exercise period for one patient from one source.

Summary invariant (FR-009): `total_reps`, `avg_form_score`, `avg_rom` MUST equal the values
recomputed from `reps` rows that are not flagged out of range.

### exercise_sets

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | |
| session_id | INTEGER FK → sessions.id | ON DELETE CASCADE |
| ordinal | INTEGER | 1-based order within the session |
| exercise_key | TEXT | config key, e.g. `knee_extension_right` |
| exercise_name | TEXT | display name, e.g. `Knee Extension (Right)` |
| side | TEXT | `left`, `right`, or `bilateral` (from `ExerciseConfig.side`) |
| target_reps | INTEGER | count |
| up_angle | REAL | degrees, engine threshold at set start (for PTA-Log `max=`) |
| down_angle | REAL | degrees, engine threshold at set start (for PTA-Log `min=`) |
| start_time | TEXT | timestamp |
| end_time | TEXT NULL | set on switch or session end |

Definition: a run of one exercise within a session. An empty set is still recorded so a
switch is visible (edge case).

### reps

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | |
| set_id | INTEGER FK → exercise_sets.id | ON DELETE CASCADE |
| rep_number | INTEGER | 1-based within the set |
| min_angle | REAL | degrees |
| max_angle | REAL | degrees |
| rom | REAL | degrees, max_angle − min_angle |
| duration_seconds | REAL | seconds |
| form_score | REAL | 0-100 |
| timestamp | TEXT | timestamp |
| frame_num | INTEGER | inference frame index |
| out_of_range | INTEGER | 1 when duration < 0, form_score ∉ [0,100], or rom ∉ [0,180]; excluded from averages (edge case) |

Definition: one counted repetition. Source: `RepMetrics` from `tracker.session.rep_metrics`.

### partial_reps

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | |
| set_id | INTEGER FK → exercise_sets.id | ON DELETE CASCADE |
| reason | TEXT | `insufficient_rom`, `reversed_early`, `interrupted` |
| min_angle | REAL | degrees |
| max_angle | REAL | degrees |
| rom | REAL | degrees |
| duration_seconds | REAL | seconds |
| timestamp | TEXT | timestamp |
| frame_num | INTEGER | |

Definition: an attempted repetition that did not count. Source: `PartialRepMetrics`.

### form_events

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | |
| set_id | INTEGER FK → exercise_sets.id | ON DELETE CASCADE |
| severity | TEXT | `suggestion`, `warning`, `stop` (mapping below) |
| status | TEXT | engine `FormStatus` value: `warning`, `poor`, `stop` |
| message | TEXT | first feedback message text |
| body_part | TEXT NULL | from `FormFeedback.body_part` |
| timestamp | TEXT | |
| frame_num | INTEGER | |

Severity mapping (spec assumption): `FeedbackPriority.INFO/SUGGESTION` → `suggestion`;
`WARNING` and status `poor` → `warning`; `CRITICAL` or status `stop` → `stop`.
Throttle (FR-007): an identical `message` for the same set is not stored again within 2 s;
the recorder also keeps the legacy 60-frame throttle so the plain-text log export matches.

### control_events

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | |
| session_id | INTEGER FK → sessions.id | ON DELETE CASCADE |
| kind | TEXT | `switch` or `reset` |
| from_exercise | TEXT NULL | switch only |
| to_exercise | TEXT NULL | switch only |
| rep_count_at_reset | INTEGER NULL | reset only |
| timestamp | TEXT | |
| frame_num | INTEGER | |

### frame_samples

| Column | Type | Rules |
|--------|------|-------|
| set_id | INTEGER FK → exercise_sets.id | ON DELETE CASCADE |
| frame_num | INTEGER | every 15th inference frame with a detected angle |
| timestamp | TEXT | |
| angle | REAL | degrees, the raw detected angle passed to `update()` (what the legacy PTA-Log line recorded) |
| state | TEXT | `up`, `down`, `idle`, `neutral` |
| rep_count | INTEGER | |

Not an event under FR-010; flushed in a batch at most once per second. Exists for the PTA-Log
export (D2) and future angle traces. Index on `(set_id, frame_num)`.

### exports

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | |
| session_id | INTEGER FK → sessions.id | ON DELETE CASCADE |
| format | TEXT | `pta_log`, `observation_json`, `csv_report`, `text_log` |
| path | TEXT | absolute path written; deleted with the patient (FR-017) |
| created_at | TEXT | |

### import_ledger

| Column | Type | Rules |
|--------|------|-------|
| file_sha256 | TEXT PK | hash of the legacy file |
| source_path | TEXT | path at import time |
| session_id | INTEGER FK → sessions.id NULL | NULL when skipped as duplicate or malformed |
| outcome | TEXT | `imported`, `duplicate`, `malformed` |
| imported_at | TEXT | |

### schema_version

| Column | Type |
|--------|------|
| version | INTEGER PK |
| applied_at | TEXT |

## Relationships

```text
patients 1 ─── * sessions 1 ─── * exercise_sets 1 ─── * reps
                    │                    ├──────────── * partial_reps
                    │                    ├──────────── * form_events
                    │                    └──────────── * frame_samples
                    ├──────────── * control_events
                    └──────────── * exports
import_ledger * ─── 0..1 sessions
```

All child rows cascade on delete (`PRAGMA foreign_keys=ON`), which implements FR-017 in one
statement plus file removal for `exports.path`.

## State Transitions

```text
Session:   (start) ──> running ──end()──> completed
                           └──open() finds running──> interrupted
Set:       open ──switch()/end()──> closed (end_time set)
Patient:   exists ──delete()+confirm──> removed (cascade)   [unassigned: never]
```

## Read model: the event log view

`SessionStore.event_log(session_id)` returns the union of reps, partial reps, form events,
and control events ordered by `(timestamp, frame_num)`, each row tagged with `type` and the
set ordinal, plus synthetic `session_start` and `session_end` rows, so the UI and the
observation-JSON export share one ordering.

## Validation rules (from FRs)

- Patient ID/label: D7 regexes; duplicate ID (case-insensitive) rejected (FR-013/014).
- `unassigned` patient is created by migration 1 and cannot be deleted (FR-015).
- Rep and partial-rep values outside physical ranges are stored with `out_of_range=1` and
  excluded from summary averages (edge case).
- A session with zero non-flagged reps has NULL averages, displayed as "not available".
- Only one `running` session may exist; `start()` marks any existing running session
  `interrupted` first (edge case).
