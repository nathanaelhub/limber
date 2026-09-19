# Research: Review Over Time

**Feature**: 002-review-over-time | **Date**: 2026-09-16

No NEEDS CLARIFICATION markers remain. Decisions below resolve the design choices.

## D1. Measures are derived, never stored

- **Decision**: `measures.py` computes `SessionMeasure` per session and exercise from a loaded
  `Session` on every request; nothing is cached or persisted.
- **Rationale**: constitution II (one canonical record). A 200-session patient needs 200
  `load_session` calls, measured at well under a second in feature 001's read tests; caching
  would add a second source of truth for no measurable gain.
- **Alternatives considered**: a `session_measures` table refreshed on session end (stale
  after imports and reassignments); SQL aggregates (cannot express tempo consistency and
  partial share cleanly, and duplicates rounding rules).

## D2. Tempo consistency is the population standard deviation of rep durations

- **Decision**: `statistics.pstdev(durations)` over counted reps, rounded to 2 decimals;
  None with fewer than one rep. Matches the engine's own `tempo_consistency` (which used
  `np.std`, population form).
- **Rationale**: the same definition the on-screen session summary already shows.
- **Alternatives considered**: sample standard deviation (differs from the engine's number
  the PT has seen); coefficient of variation (harder to explain).

## D3. Rule thresholds live as named constants with the spec text as docstring

- **Decision**: `flags.py` defines `FORM_DECLINE_WINDOW = 4`, `FORM_DROP_POINTS = 10`,
  `ROM_REGRESSION_DEGREES = 10`, `ROM_PLATEAU_DEGREES = 3`, `TARGET_REPS_SESSIONS = 3`,
  `PARTIAL_SHARE_MIN = 25`, `PARTIAL_SHARE_RISE = 10`; each rule function's docstring quotes
  FR-014. Only `gap_days` is per patient (FR-016).
- **Rationale**: spec assumption "fixed thresholds"; constants make a later settings feature
  trivial and keep tests readable.
- **Alternatives considered**: a settings table now (spec defers it).

## D4. Flags are computed per exercise; the practice gap is per patient

- **Decision**: rules 1–6 run on each exercise's ordered `SessionMeasure` series inside the
  period; the practice-gap rule runs once over all sessions of the patient in the period and
  from the latest session to "now" (an injected clock for tests).
- **Rationale**: a gap in practice is not exercise-specific; the others are.

## D5. Reviews key on the session

- **Decision**: `reviews.session_id` is the primary key with `ON DELETE CASCADE`; one row per
  session, replaced on edit (`INSERT OR REPLACE`), `reviewed_at` set to the clock at write.
- **Rationale**: FR-010 (one review), FR-013 (follows reassignment, dies with the patient
  through the session cascade) with no extra bookkeeping.
- **Alternatives considered**: a review history table (spec says no history).

## D6. Review exports get their own table

- **Decision**: `review_exports(patient_id, format, period, path, created_at)` with cascade
  on patient; `delete_patient` unlinks these paths as it does session exports.
- **Rationale**: review exports are per patient and period, not per session, so the existing
  `exports(session_id)` table cannot hold them, and its CHECK constraint stays untouched.

## D7. Per-session summary reused unchanged

- **Decision**: the session review view calls `session_summary.generate_session_summary(
  to_observation_dict(session))` and shows `key_flags` and `summary_text`.
- **Rationale**: spec assumption; the module already consumes the legacy dict shape that
  feature 001's export produces.

## D8. Legacy trend code retired

- **Decision**: delete `src/session_tracker.py`, its tests, `views.load_session_data_for_trends`,
  and the CLI `progress` command; `measures`/`flags`/`review` replace them. `plot_progress`
  (matplotlib PNG) is not carried over; the web page draws charts and the CLI prints tables.
- **Rationale**: feature 001 research D13 kept the trend math only until this feature; two
  trend implementations would violate constitution V.
- **Alternatives considered**: keeping `SessionTracker.calculate_progress` as a thin wrapper
  (duplicate definitions of "trend").

## D9. Period handling

- **Decision**: periods are `14d`, `30d`, `90d`, `all`; a session is in the period when its
  start time is at or after `now - days`. `now` is injectable; the CLI and web use the real
  clock.

## D10. Comparison exercise resolution

- **Decision**: `compare(a, b, exercise=None)`: if both sessions share exactly one exercise
  name it is used; if they share several the caller must name one; if they share none the
  comparison is refused (FR-017). Percentage change is reported for ROM, form, and reps only;
  when the base value is 0 or missing the percentage is "not available".

## D11. Review page layout

- **Decision**: one `page_review` with a horizontal section radio (key `review_tab`): Trends,
  Flags, Compare, Session review, Goals & settings, Export. Only the chosen section renders,
  which keeps each run cheap and lets page tests pick a section through session state
  (`st.tabs` renders every tab on every run and cannot be selected programmatically).
- **Rationale**: replaces two pages with one place to do the whole review (FR-023).

## D12. Notes validation

- **Decision**: `privacy.validate_notes` applies the three PHI patterns with no length cap
  and trims whitespace; empty notes are allowed (a review may be just a next step).
