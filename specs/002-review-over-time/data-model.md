# Data Model: Review Over Time

**Feature**: 002-review-over-time | **Date**: 2026-09-16 | Schema version: 2 (migration adds
the tables below to the feature-001 schema; nothing existing changes)

## New tables

### reviews

| Column | Type | Rules |
|--------|------|-------|
| session_id | INTEGER PK FK → sessions.id | ON DELETE CASCADE; one review per session (FR-010) |
| reviewed_at | TEXT | timestamp; replaced on every edit |
| notes | TEXT NULL | free text; rejected on name/date/6-digit patterns (FR-009); empty allowed |
| next_step | TEXT | `continue`, `progress`, `regress`, `hold` |

Follows the session on reassignment (keyed by session), dies with the patient (session
cascade) — FR-013.

### goals

| Column | Type | Rules |
|--------|------|-------|
| patient_id | TEXT FK → patients.id | ON DELETE CASCADE ON UPDATE CASCADE |
| exercise_name | TEXT | recorded exercise name (sides separate) |
| target_rom | REAL NULL | degrees, 1–180 |
| target_reps | INTEGER NULL | count, ≥ 1 |
| set_at | TEXT | timestamp of last set |

PRIMARY KEY (patient_id, exercise_name). CHECK: at least one target present.

### review_settings

| Column | Type | Rules |
|--------|------|-------|
| patient_id | TEXT PK FK → patients.id | ON DELETE CASCADE ON UPDATE CASCADE |
| gap_days | INTEGER | 1–90, default 7 (FR-016) |

Absent row means defaults.

### review_exports

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | |
| patient_id | TEXT FK → patients.id | ON DELETE CASCADE |
| format | TEXT | `review_report`, `review_csv` |
| period | TEXT | `14d`, `30d`, `90d`, `all` |
| path | TEXT | absolute path; unlinked on patient delete (FR-022) |
| created_at | TEXT | |

### schema_version

Gains row `2`.

## Derived (not stored)

### SessionMeasure (per session, per exercise)

| Field | Unit | Definition |
|-------|------|------------|
| reps_completed | count | counted reps not flagged out of range, across all sets of the exercise |
| target_reps | count | target of the last set of the exercise in the session |
| avg_rom | degrees | mean ROM of counted reps; None when no reps |
| avg_form | score 0-100 | mean form score of counted reps; None when no reps |
| avg_duration | seconds | mean rep duration; None when no reps |
| tempo_sd | seconds | population standard deviation of rep durations; None when no reps |
| partial_count | count | partial reps of the exercise |
| partial_share | percent | partial / (partial + reps) × 100; None when both are 0 |
| safety_stops | list | (timestamp, message) of form events with severity `stop` |
| interrupted | bool | session status == interrupted |

Plus identity: `session_id`, `patient_id`, `start_time`, `exercise_name`.

### Trend

`exercise`, `period`, `points: [SessionMeasure]` oldest first, `summary` per measure
(first, latest, change) when ≥ 2 points, `goal` and `rom_progress_pct` (0–100) when a goal
exists, `enough_for_trend: bool`.

### Flag

`rule` (form_declining | rom_regression | rom_plateau | target_reps_not_reached |
rising_partial_reps | safety_stop | practice_gap), `exercise` (None for practice_gap),
`session_ids`, `values` (dict of the numbers used), `message` (one sentence with the
evidence). `FlagResult` = `flags` + `not_evaluated: [(rule, exercise, needed, have)]` (FR-015).

### Comparison

`exercise`, `a`, `b` (SessionMeasure), `rows`: per measure `{name, unit, a, b, change,
pct_change, better}` where `better` ∈ higher | lower | informational (FR-018).

### ReviewSummary

`patient_id`, `period`, `generated_at`, `trends: {exercise: Trend}`, `flags: FlagResult`,
`goals: [Goal + progress]`, `sessions: [{measures, review}]` newest first, `gap_days`.

## Validation rules

- `next_step` restricted to the four values; `notes` via `privacy.validate_notes`.
- `target_rom` 1–180, `target_reps` ≥ 1, at least one set; otherwise `PTLogError` subclass
  `GoalValidationError`.
- `gap_days` 1–90.
- Compare refuses sessions without a common exercise (`ComparisonError`).

## State transitions

```text
Session review:  pending ──set_review()──> reviewed ──set_review()──> reviewed (reviewed_at updated)
Goal:            none ──set_goal()──> set ──set_goal()──> updated ──clear_goal()──> none
```

## Migration 2

```sql
CREATE TABLE reviews (session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE, reviewed_at TEXT NOT NULL, notes TEXT, next_step TEXT NOT NULL CHECK (next_step IN ('continue','progress','regress','hold')));
CREATE TABLE goals (patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE, exercise_name TEXT NOT NULL, target_rom REAL CHECK (target_rom IS NULL OR (target_rom >= 1 AND target_rom <= 180)), target_reps INTEGER CHECK (target_reps IS NULL OR target_reps >= 1), set_at TEXT NOT NULL, PRIMARY KEY (patient_id, exercise_name), CHECK (target_rom IS NOT NULL OR target_reps IS NOT NULL));
CREATE TABLE review_settings (patient_id TEXT PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE, gap_days INTEGER NOT NULL DEFAULT 7 CHECK (gap_days BETWEEN 1 AND 90));
CREATE TABLE review_exports (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE, format TEXT NOT NULL CHECK (format IN ('review_report','review_csv')), period TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL);
```

A test opens a database created with migration 1 only and asserts version 2 applies with the
feature-001 data intact.
