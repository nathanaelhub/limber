# Research: Multi-Patient PT Tracker

**Feature**: 003-pt-tracker | **Date**: 2026-09-19. No NEEDS CLARIFICATION markers remain.

## D1. One catalog loader for exercises and programs

- **Decision**: `programs.py` owns `load_catalog(config_path=None)` returning exercises
  (key → display name, side, thresholds, target reps) and programs (id → name, description,
  exercise keys) from `config.yaml`, cached per path. `importer.exercise_catalog()` delegates
  to it. Custom assignments use program id `custom` and name `Custom`.
- **Rationale**: constitution V; the importer already parsed the same file.
- **Alternatives considered**: a `programs` table seeded from the config (a second source of
  truth that drifts when the config changes).

## D2. Assignment weeks, not calendar weeks

- **Decision**: week *k* of an assignment covers dates `start + 7(k−1)` through
  `start + 7k − 1` inclusive; a session belongs to the week containing the date part of its
  start time. A week is complete when its last day is before today; the current week is the
  one containing today. The window is the last four complete weeks not after the end date,
  plus the current week when the assignment is active.
- **Rationale**: spec assumption; independent of the weekday a program starts, and the
  start-day and last-day edge cases follow directly.

## D3. Percentage over complete weeks, capped per week

- **Decision**: `percentage = round(100 × Σ min(recorded, planned) / Σ planned)` over the
  complete weeks in the window; None when there is no complete week, no active or completed
  assignment, or the assignment is superseded.
- **Rationale**: FR-010; capping per week keeps one heavy week from hiding a missed one.

## D4. What counts as a recorded session

- **Decision**: a session counts once toward a week when it has at least one counted rep
  (any exercise, `out_of_range == 0`); an assigned exercise is performed in a week when any
  set with that `exercise_key` in that week has a counted rep. Sessions attributed to the
  patient at computation time count (a reassigned session moves with its patient).
- **Rationale**: spec assumptions; recorded sets already carry the config key.

## D5. Supersession

- **Decision**: `assign_program()` sets `end_date = new start − 1 day` on any existing
  assignment for the patient whose end date is null or on/after the new start; an assignment
  whose end date is before its start is reported as `superseded`. Status otherwise is
  `scheduled` (start after today), `active`, or `completed` (end before today).
- **Rationale**: FR-007/FR-008 and the back-dated edge case.

## D6. One load per patient

- **Decision**: `tracker._snapshot(store, patient, now)` calls `list_sessions(pid)` (cheap
  rows) for last-session and 7/30-day counts, then `sessions_in_period(pid, since)` once with
  `since = min(now − 30 days, adherence window start)` and reuses the loaded sessions for the
  30-day flags (filtered in memory) and adherence. `pending_reviews` and a new
  `latest_review` query are per patient.
- **Rationale**: SC-002; 50 × 20 sessions = 1000 full loads of small sessions, well under
  3 s in feature 002's measurements; avoiding a second load per patient halves it.
- **Alternatives considered**: precomputed roster columns stored in a table (stale after
  reviews and imports); SQL-only counts (cannot evaluate the flag rules).

## D7. Attention sort and "needs attention"

- **Decision**: sort key `(−open_flags, −pending_reviews, adherence_rank, −days_since_last)`
  where `adherence_rank` is the percentage when present and a value above 100 when absent
  (patients without a program sort after those with one); `needs_attention` is true when
  open flags > 0, pending > 0, adherence below the threshold, or a practice-gap flag fired.
  `open_flags` counts flags from every rule except practice gap; the gap is a separate
  boolean so the queue lists it under its own kind.

## D8. Queue kinds and ordering

- **Decision**: kinds `pending_review` (per session, oldest start first), `attention_flag`
  (per flag, oldest triggering session first), `practice_gap` (per patient, longest gap
  first), `low_adherence` (per patient, lowest first). Items carry `patient_id`, `target`
  (`session:<id>`, `flags:<patient>`, `adherence:<patient>`), `age_days`, and a sentence.
  No state is stored (FR-015).

## D9. Adherence threshold is installation-wide

- **Decision**: `tracker_settings` is a single-row table (`id = 1`,
  `adherence_threshold` 1–100, default 60). Discharge and reactivate live in a `discharges`
  table keyed by patient (absent = active).

## D10. Roster export is not tracked per patient

- **Decision**: `roster_<YYYYMMDD_HHMMSS>.csv` under `exports/`, not recorded in any
  bookkeeping table, because it belongs to the caseload rather than to one patient and
  contains only IDs and non-identifying labels.

## D11. Web layout

- **Decision**: `page_tracker` with a section radio (Roster, Queue, Adherence, Discharged,
  Export), same pattern as the Review page; the Patients page gains an "Program" form
  (program select or custom multiselect, per week, start, end) with the assignment history,
  and a discharge/reactivate control per patient.

## D12. Dates

- **Decision**: assignment and discharge dates are ISO `YYYY-MM-DD` strings; "today" is an
  injectable `date` (CLI/web use the real date). Session membership in a week uses the date
  part of the ISO start time.
