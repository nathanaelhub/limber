# Data Model: Multi-Patient PT Tracker

**Feature**: 003-pt-tracker | **Date**: 2026-09-19 | Schema version: 3 (adds to versions 1–2)

## New tables

### assignments

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | |
| patient_id | TEXT FK → patients.id | ON DELETE CASCADE ON UPDATE CASCADE |
| program_id | TEXT | config program id (e.g. `knee_rehab`) or `custom` |
| program_name | TEXT | display name at assignment time |
| exercise_keys | TEXT | JSON list of config keys, ordered; every key validated against the catalog at assignment time |
| sessions_per_week | INTEGER | 1–14 |
| start_date | TEXT | `YYYY-MM-DD` |
| end_date | TEXT NULL | `YYYY-MM-DD`; not before start when given by the user; may be before start after supersession |
| created_at | TEXT | timestamp |

Index on `(patient_id, start_date)`. Status is derived (see below), never stored.

### discharges

| Column | Type | Rules |
|--------|------|-------|
| patient_id | TEXT PK FK → patients.id | ON DELETE CASCADE ON UPDATE CASCADE; absent row = active |
| discharged_on | TEXT | `YYYY-MM-DD` |
| reason | TEXT NULL | validated with the notes rules |
| created_at | TEXT | |

### tracker_settings

| Column | Type | Rules |
|--------|------|-------|
| id | INTEGER PK | CHECK (id = 1) |
| adherence_threshold | INTEGER | 1–100, default 60 |

### schema_version

Gains row `3`.

## Derived (not stored)

### Program

`id`, `name`, `description`, `exercise_keys`, `exercise_names` (display names resolved from the
catalog; a key without a display name shows the key).

### Assignment status

```text
superseded  when end_date < start_date
scheduled   when start_date > today
completed   when end_date is set and end_date < today
active      otherwise
```

### AdherenceWeek

| Field | Unit | Definition |
|-------|------|------------|
| index | count | 1-based assignment week |
| start, end | date | inclusive bounds (7 days) |
| planned | count | sessions_per_week |
| recorded | count | sessions in the week with ≥ 1 counted rep |
| counted | count | min(recorded, planned) |
| exercises_performed / exercises_missing | keys | assigned keys with / without a counted rep that week |
| missed | bool | recorded == 0 and the week is complete |
| in_progress | bool | the week contains today |

### Adherence

`assignment`, `status`, `weeks` (up to 4 complete + current), `percentage` (whole percent or
None), `note` (`"no program"`, `"first week in progress"`, `"starts on <date>"`,
`"completed on <date>"`, `"superseded"`).

### RosterRow

| Field | Unit / values |
|-------|---------------|
| patient_id, label, is_builtin | |
| program_id, program_name, program_status | status or `none` |
| days_since_last | days or None ("no sessions yet") |
| sessions_7d, sessions_30d | count |
| adherence_pct | percent or None |
| adherence_note | text |
| pending_reviews | count |
| open_flags | count (rules other than practice gap, last 30 days) |
| practice_gap | bool |
| last_next_step | continue / progress / regress / hold / None |
| needs_attention | bool |

### QueueItem / QueueResult

`kind` ∈ pending_review | attention_flag | practice_gap | low_adherence; `patient_id`;
`target` (`session:<id>` | `flags:<patient_id>` | `adherence:<patient_id>`); `session_id`
(when applicable); `age_days`; `description`. `QueueResult.items` grouped by kind in that
order, `totals` per kind.

## Validation rules

- `sessions_per_week` 1–14; `end_date >= start_date` when given; exercise keys must exist in
  the catalog (unknown keys named); at least one exercise → `AssignmentValidationError` /
  `ProgramValidationError`.
- Built-in patient: assign and discharge refused (`BuiltinPatientError`).
- Discharge reason: `validate_notes`. Discharging an already discharged patient updates the
  record; reactivating an active patient is a no-op returning False.
- Adherence threshold 1–100.

## Migration 3

```sql
CREATE TABLE assignments (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE, program_id TEXT NOT NULL, program_name TEXT NOT NULL, exercise_keys TEXT NOT NULL, sessions_per_week INTEGER NOT NULL CHECK (sessions_per_week BETWEEN 1 AND 14), start_date TEXT NOT NULL, end_date TEXT, created_at TEXT NOT NULL);
CREATE INDEX idx_assignments_patient ON assignments(patient_id, start_date);
CREATE TABLE discharges (patient_id TEXT PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE, discharged_on TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL);
CREATE TABLE tracker_settings (id INTEGER PRIMARY KEY CHECK (id = 1), adherence_threshold INTEGER NOT NULL DEFAULT 60 CHECK (adherence_threshold BETWEEN 1 AND 100));
INSERT OR IGNORE INTO tracker_settings (id, adherence_threshold) VALUES (1, 60);
```

A test opens a database at version 2 and asserts version 3 applies with reviews and goals
intact.
