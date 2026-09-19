# Tasks: Review Over Time

**Input**: Design documents from `/specs/002-review-over-time/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (review-api.md, cli.md, exports.md), quickstart.md

**Tests**: REQUIRED (constitution IV). Each story's tests are written first and MUST fail before the
implementation; the full suite (`.venv/bin/python -m pytest tests`) MUST be green at every checkpoint.
Tests use `tmp_path` databases and the fixed clock; no camera, network, or model weights. Engine tests are
never edited.

**Organization**: Tasks are grouped by user story so each story is an independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US6 from spec.md
- Exact file paths are included in every task

## Path Conventions

Single project: `src/ptlog/` package, flat `tests/`, interfaces in `interfaces/`. Branch `002-review-over-time`
is created from `main` before T001.

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Add to `tests/conftest.py` a `fixed_store` fixture (SessionStore on `tmp_db` with `tests.fixtures.golden.sequence.FixedClock`, yielding `(store, clock)`) and a `make_session` fixture factory: `make_session(store, clock, patient_id, exercise: ExerciseSetInfo | str, start: datetime, reps: list[tuple[form, rom, duration]], partials: int = 0, target_reps: int = 10, safety_stop: str | None = None, interrupted: bool = False, extra_sets: list[...] = ())` that sets the clock to `start`, starts a session (source video, ref clip.mp4), opens the set(s), adds reps with timestamps stepping 5 s from `start` (min_angle 10, max_angle 10 + rom), adds `partials` reversed_early partial reps, adds a `stop` form event when `safety_stop` is given, and either ends the session or, when `interrupted`, leaves it running and calls `store._interrupt_running("recovered_on_open")`; returns the session id
- [X] T002 [P] Create `src/ptlog/measures.py`, `src/ptlog/flags.py`, `src/ptlog/review.py`, `src/ptlog/exports/review_report.py`, `src/ptlog/exports/review_csv.py` with module docstrings only (contents arrive in their stories)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: schema migration 2, models, notes validation, and the per-session measures every story reads

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 [P] Write the foundation section of `tests/test_ptlog_review.py` (must FAIL first): a database created by applying only `MIGRATIONS[:1]` (open a raw sqlite3 connection, `executescript(MIGRATIONS[0][1])`, insert `schema_version` 1, a patient and a session) opens through `SessionStore.open()` at version 2 with tables `reviews`, `goals`, `review_settings`, `review_exports` and `schema_version` rows `[1, 2]`, and the session is still readable; `models.NEXT_STEPS == ("continue", "progress", "regress", "hold")`; `models.PERIODS == {"14d": 14, "30d": 30, "90d": 90, "all": None}`; dataclasses `Review`, `Goal`, `ReviewSettings`, `SessionMeasure`, `Flag`, `FlagResult`, `Trend`, `Comparison`, `ReviewSummary` exist with the fields in data-model.md; `METRIC_DEFINITIONS` has `avg_duration` ("seconds"), `tempo_sd` ("seconds"), `partial_share` ("percent"); exceptions `GoalValidationError`, `ComparisonError`, `ReviewValidationError` subclass `PTLogError`
- [X] T004 [P] Write the store-primitives section of `tests/test_ptlog_review.py` (must FAIL first): `set_goal("P-017", "Knee Extension", target_rom=120, target_reps=10)` stores and returns a `Goal` with `set_at`; `set_goal(..., target_reps=12)` keeps `target_rom` 120 (None keeps existing); `get_goal` returns None when unset; `list_goals` ordered by exercise name; `clear_goal` returns True then False; `GoalValidationError` for "target_rom 1–180" (0 and 181), "target_reps ≥ 1" (0), and "at least one target" (both None on a new goal); `get_gap_days` defaults to 7; `set_gap_days(5)` persists; 0 and 91 raise `PTLogError`; `sessions_in_period(patient, since)` returns full `Session` objects oldest first and filters by `start_time >= since`, `since=None` returns all; `exercise_names(patient)` distinct in first-seen order; `record_review_export` inserts a row and `delete_patient` unlinks the file and counts it in `DeleteReport.export_files`; goals, settings, and review_exports rows vanish on patient delete
- [X] T005 [P] Extend `tests/test_ptlog_privacy.py` (must FAIL first): `validate_notes(None)` and `("")` → None; `("  post-op week 3, tolerated full set ")` → stripped text; 1000-character notes accepted (no length cap); `"seen by Jane Doe"` → `PatientValidationError` naming "name"; `"DOB 1990-01-02"` → "date"; `"MRN 123456"` → "six or more"
- [X] T006 [P] Write `tests/test_ptlog_measures.py` (must FAIL first) using `make_session`: `measures_for_session` on a session with two Knee Extension sets (target 10 then 12) and one Squat set: keyed by exercise name; Knee `reps_completed` counts non-flagged reps across both sets and `target_reps == 12` (last set); `avg_rom`/`avg_form` rounded to 1 decimal; `avg_duration` and `tempo_sd == round(statistics.pstdev(durations), 2)`; `partial_share == round(partials / (partials + reps) * 100, 1)`; a rep with `form_score=101` is excluded from every average and from `reps_completed`; a set with zero reps gives `avg_rom/avg_form/avg_duration/tempo_sd None` and `partial_share None` when partials are also 0; `safety_stops` lists `(timestamp, message)` for severity `stop` only; `interrupted` True for an interrupted session; `measure_series(sessions, "Knee Extension")` returns oldest first and skips sessions without that exercise
- [X] T007 Implement the additions to `src/ptlog/models.py` (depends on T003): `NEXT_STEPS`, `PERIODS`, `REVIEW_EXPORT_FORMATS = ("review_report", "review_csv")`, dataclasses `Review(session_id, reviewed_at, notes, next_step)`, `Goal(patient_id, exercise_name, target_rom, target_reps, set_at)`, `ReviewSettings(patient_id, gap_days=7)`, `SessionMeasure` (fields per data-model.md), `Flag(rule, exercise, session_ids, values, message)`, `NotEvaluated(rule, exercise, needed, have)`, `FlagResult(flags, not_evaluated)`, `Trend(exercise, period, points, summary, goal, rom_progress_pct, enough_for_trend)`, `ComparisonRow(name, unit, a, b, change, pct_change, better)`, `Comparison(exercise, a, b, rows)`, `ReviewSummary(patient_id, period, period_start, generated_at, gap_days, trends, flags, goals, sessions)`; the three metric definitions with units and definitions; the three exceptions
- [X] T008 Implement in `src/ptlog/store.py` (depends on T003, T004, T007): `SCHEMA_V2_SQL` exactly as data-model.md, `MIGRATIONS.append((2, SCHEMA_V2_SQL))`, `SCHEMA_VERSION = 2`; `set_goal`/`get_goal`/`list_goals`/`clear_goal` with `GoalValidationError` messages "target_rom must be 1–180 degrees", "target_reps must be at least 1", "a goal needs at least one target"; `get_gap_days`/`set_gap_days` (1–90); `sessions_in_period`; `exercise_names`; `record_review_export(patient_id, fmt, period, path)`; extend `delete_patient` to collect and unlink `review_exports.path` rows
- [X] T009 [P] Implement `validate_notes` in `src/ptlog/privacy.py` (depends on T005): strip, empty → None, apply `_check_phi(value, "Notes")`, no length cap
- [X] T010 [P] Implement `src/ptlog/measures.py` (depends on T006, T007): `measures_for_session(session) -> dict[str, SessionMeasure]` combining all sets per exercise name (reps with `out_of_range == 0`, target from the last set, `statistics.pstdev`, rounding per contract), `measure_series(sessions, exercise)`

**Checkpoint**: schema at v2, measures computable, notes validated — story work can begin

---

## Phase 3: User Story 1 - See a Patient's Trends Across Sessions (Priority: P1) 🎯 MVP

**Goal**: one patient, one exercise, one period → ordered per-session measures with first/latest/change and goal progress; replaces the old progress views.

**Independent Test**: seed four Knee Extension sessions on different days, run `review trends`, confirm four ordered points whose values match each session, and that `--period 14d` hides older ones.

### Tests for User Story 1 (write first, MUST FAIL)

- [X] T011 [P] [US1] Add the trend section to `tests/test_ptlog_review.py`: with sessions on days −40, −20, −10, −1 (relative to an injected `now`), `review.trend(store, "P-017", "Knee Extension", "all", now)` has four points oldest first with `session_id` and values equal to `measures_for_session`; `"14d"` keeps two, `"30d"` three, `"90d"` four; `summary["avg_rom"] == {"first", "latest", "change"}` with change = latest − first (1 decimal) and `enough_for_trend` True; a single session gives `enough_for_trend` False and `summary == {}`; an interrupted session appears with `interrupted` True; after `set_goal(target_rom=120, target_reps=10)`, `trend.goal` is set and `rom_progress_pct == min(100, round(latest_avg_rom / 120 * 100))`; a patient with sessions but none of the exercise returns an empty trend and `review.exercise_names` lists what exists; two sessions on the same day are two points ordered by start time; "Knee Extension" and "Knee Extension (Right)" are separate trends; `period_start("14d", now) == now - timedelta(days=14)` and `period_start("all", now) is None`
- [X] T012 [P] [US1] Write `tests/test_ptlog_views.py` additions: `views.trend_table_rows(trend)` gives one dict per point with keys `date, session_id, reps, avg_form, avg_rom, avg_duration, tempo_sd, partial_share, status` formatted with units (`"8/10"`, `"85.0/100"`, `"80.0°"`, `"2.40 s"`, `"0.15 s"`, `"0.0%"`, `"not available"`); `views.trend_summary_lines(trend)` includes `"avg ROM: 80.0° → 92.0° (+12.0°)"` and a `"Goal: ROM 120° (77% of goal) | reps 10"` line when a goal exists and `"A trend needs at least two sessions."` otherwise
- [X] T013 [P] [US1] Extend `tests/test_cli_ptlog.py`: `review trends P-017 --exercise "Knee Extension" --period all` prints the table header with units and one row per session, the change block, exit 0; `--json` parses with `points` and `summary`; an exercise the patient never did → exit 1 with the available exercise names; `progress` is no longer a command (exit 2 from argparse)
- [X] T014 [P] [US1] Update `tests/test_app_pages.py`: `PAGES` gains `"review"` and loses `"progress"` and `"pt_summary"`; a `test_review_page_trends_tab` seeds two sessions, sets `current_page = "review"`, runs, asserts no exception and that a dataframe with an `avg ROM (degrees)` column is rendered

### Implementation for User Story 1

- [X] T015 [US1] Implement in `src/ptlog/review.py` (depends on T011): `period_start`, `_now()`, `trend(store, patient_id, exercise, period="all", now=None) -> Trend` (loads `sessions_in_period`, `measure_series`, summary dict per measure name `reps_completed, avg_form, avg_rom, avg_duration, tempo_sd, partial_share` with first/latest/change when ≥ 2 points, goal via `store.get_goal`, `rom_progress_pct` capped at 100), `exercise_names(store, patient_id)`
- [X] T016 [US1] Add to `src/ptlog/views.py` (depends on T012, T015): `fmt_measure(name, value)` using `METRIC_DEFINITIONS` units, `trend_table_rows(trend)`, `trend_summary_lines(trend)`; delete `load_session_data_for_trends` and its import of `src.session_tracker`; delete `TestTrendLoader` from `tests/test_ptlog_views.py`
- [X] T017 [US1] `interfaces/cli.py` (depends on T013, T015, T016): add the `review` command group with `trends` per `contracts/cli.md` (table via `views.trend_table_rows`, summary lines, `--json`), remove the `progress` subparser, `cmd_progress`, and its dispatch; update the module docstring examples
- [X] T018 [US1] `interfaces/app.py` (depends on T014, T015, T016): add `page_review()` with a horizontal `st.radio("Section", ["Trends", "Flags", "Compare", "Session review", "Goals & settings", "Export"], key="review_tab")` so only the chosen section renders (testable through `st.session_state["review_tab"]`, cheaper than `st.tabs`, which renders every tab on each run) and implement the Trends section (exercise and period selectors, `st.dataframe` of `trend_table_rows` with unit-labelled columns, `st.line_chart` for avg ROM and avg form, summary lines, goal line when set; other sections show "coming in this feature" placeholders until their story); register `'review': '🩺 Review'` in the sidebar `pages` dict replacing `'progress'` and `'pt_summary'`; delete `page_progress_report()`; route `'review'` in `main()`
- [X] T019 [US1] Retire the legacy trend code: delete `src/session_tracker.py` and `tests/test_session_tracker.py`; remove `from src.session_tracker import SessionTracker` from `interfaces/app.py`; grep confirms no remaining `session_tracker` references outside `docs/` and `specs/`; run the full suite green

**Checkpoint**: MVP — trends replace the old progress views

---

## Phase 4: User Story 2 - Review a Session and Track What Is Pending (Priority: P2)

**Goal**: one review per session with notes and next step, pending list, per-session summary in the session view; replaces the PT Summary page.

**Independent Test**: two sessions pending; mark one; pending list shrinks to one; reopening shows notes, next step, review time.

### Tests for User Story 2 (write first, MUST FAIL)

- [X] T020 [P] [US2] Add the review section to `tests/test_ptlog_review.py`: `set_review(sid, "progress", "post-op week 3")` returns `Review` with `reviewed_at` from the clock; `get_review` round-trips; a second `set_review` replaces notes/next_step and updates `reviewed_at` with still one row; `next_step="stop"` → `ReviewValidationError`; notes `"seen by Jane Doe"` → `ReviewValidationError` naming "name" and nothing stored; unknown session → `SessionNotFoundError`; `pending_reviews("P-017")` newest first excludes reviewed sessions; a review survives `reassign_session` to another patient and is gone after `delete_patient`; `review.session_review_view(store, sid)` returns `session`, `measures` (dict per exercise), `summary` with keys `key_flags`, `summary_text`, `metrics` from `generate_session_summary`, and `review` (None when pending)
- [X] T021 [P] [US2] Extend `tests/test_cli_ptlog.py`: `review pending P-017` lists both seeded sessions newest first; `review mark <id> --next-step progress --notes "post-op week 3"` prints `Reviewed session <id> (next step: progress)`; `--notes "seen by Jane Doe"` → exit 1 naming the rule; `--next-step stop` → argparse error; `review session <id>` prints `REVIEW: reviewed` with the notes and the per-session summary flags header, and `REVIEW: pending` for the other; `review pending` afterwards lists only the other
- [X] T022 [P] [US2] Extend `tests/test_app_pages.py`: `test_review_page_session_tab` selects the Session review section via `at.session_state["review_tab"] = "Session review"`, asserts no exception, that a `selectbox` for next step exists with the four options, and that the per-session summary text is rendered

### Implementation for User Story 2

- [X] T023 [US2] Implement in `src/ptlog/store.py` (depends on T020): `set_review` (validate `next_step in NEXT_STEPS` else `ReviewValidationError`, `validate_notes` → `ReviewValidationError` on failure, session existence, `INSERT OR REPLACE`, `reviewed_at = self._now()`), `get_review`, `pending_reviews` (sessions without a review row, newest first, as `SessionSummaryRow`)
- [X] T024 [US2] Implement in `src/ptlog/review.py` (depends on T020, T023): `session_review_view(store, session_id)` (load session, `measures_for_session`, `generate_session_summary(to_observation_dict(session))`, `get_review`), `pending(store, patient_id)`; add `views.review_lines(view)` rendering `REVIEW: pending` or `REVIEW: reviewed <time> | next step: <x> | notes: <notes>` plus one line per summary flag with severity and message
- [X] T025 [US2] `interfaces/cli.py` (depends on T021, T024): add `review session`, `review mark`, `review pending` per `contracts/cli.md` with `--next-step` `choices=NEXT_STEPS`
- [X] T026 [US2] `interfaces/app.py` (depends on T022, T024): implement the Session review tab (session selector for the sidebar patient, header lines, measures table, per-session summary flags and text, review status, a form with next-step selectbox and notes text area calling `store.set_review`, validation errors via `st.error`), the section radio already keeps the active section in `st.session_state["review_tab"]`; delete `page_pt_summary()` and the `generate_session_summary` import at the top of the file (it is now reached through `review.session_review_view`)

**Checkpoint**: reviews recorded and tracked; PT Summary page replaced

---

## Phase 5: User Story 3 - Flags That Need Attention, With Evidence (Priority: P3)

**Goal**: seven explicit rules with evidence, "not evaluated yet" reporting, per-patient gap threshold.

**Independent Test**: one seeded history per rule fires exactly that rule; a clean history fires none.

### Tests for User Story 3 (write first, MUST FAIL)

- [X] T027 [P] [US3] Write `tests/test_ptlog_flags.py` with `SessionMeasure` fixtures built directly (no store): `form_declining` fires for form 90, 86, 81, 75 (each lower) and for 90, 88, 89, 78 (latest ≥ 10 below the best of the other three), not for 90, 86, 88, 85, and returns `NotEvaluated(needed=4, have=3)` for three sessions; `rom_regression` fires for 85, 84, 86, 70 (latest ≥ 10° below the best of the previous three), not for 85, 84, 86, 80; `rom_plateau` fires for 80, 81, 79, 80 with goal 110 (|latest − earliest| < 3 and below goal), not without a goal, not when latest ≥ goal, and not when regression fires; `target_reps_not_reached` fires for 8/10, 7/10, 9/10, not when one of the last three reached target, `NotEvaluated(needed=3, have=2)`; `rising_partial_reps` fires for shares 10, 10, 10, 30 (latest ≥ 25 and ≥ 10 above the previous mean), not for 10, 10, 10, 20, treats None shares as 0; `safety_stops` yields one flag per session with stops naming the message and time; `practice_gap` fires for consecutive sessions 9 days apart with `gap_days=7` and for a last session 9 days before `now`, not for 5-day gaps; every `Flag.message` contains each session id and value used; `evaluate(...)` aggregates per exercise and lists `not_evaluated` entries
- [X] T028 [P] [US3] Add the flags section to `tests/test_ptlog_review.py`: `review.flags_for(store, "P-017", "all", now)` on a seeded history that triggers `form_declining` for Knee Extension and `practice_gap` returns exactly those two flags; `set_gap_days(30)` makes the gap flag disappear; a clean history returns no flags and lists rules not evaluated with counts; performance (SC-004): a patient with 200 sessions of one exercise built with `make_session` — `review.trend`, `review.flags_for`, and `review.pending` each complete in under 2 s
- [X] T029 [P] [US3] Extend `tests/test_cli_ptlog.py`: `review flags P-017` prints one paragraph per flag with session ids and values and a `Not evaluated yet:` block, or `Nothing needs attention.`; `review settings P-017` prints `Gap threshold: 7 days`; `--gap-days 5` updates; `--gap-days 0` → exit 1
- [X] T030 [P] [US3] Extend `tests/test_app_pages.py`: the Flags tab renders without exception and shows either flag text or "Nothing needs attention"; the Goals & settings tab shows a gap-days number input

### Implementation for User Story 3

- [X] T031 [US3] Implement `src/ptlog/flags.py` (depends on T027): named constants `FORM_WINDOW = 4, FORM_DROP_POINTS = 10, ROM_WINDOW = 4, ROM_REGRESSION_DEGREES = 10, ROM_PLATEAU_DEGREES = 3, TARGET_REPS_SESSIONS = 3, PARTIAL_WINDOW = 4, PARTIAL_SHARE_MIN = 25, PARTIAL_SHARE_RISE = 10`; rule functions per `contracts/review-api.md`, each docstring quoting its FR-014 sentence; `evaluate(series_by_exercise, goals, session_starts, gap_days, now) -> FlagResult`
- [X] T032 [US3] Implement in `src/ptlog/review.py` (depends on T028, T031): `flags_for(store, patient_id, period="all", now=None)` (sessions in period → `measure_series` per exercise name → `evaluate` with `list_goals` and `get_gap_days`); add `views.flag_lines(result)`
- [X] T033 [US3] `interfaces/cli.py` (depends on T029, T032): add `review flags` and `review settings`
- [X] T034 [US3] `interfaces/app.py` (depends on T030, T032): implement the Flags tab (period selector, `st.warning` per flag with evidence, `st.info` for not-evaluated rules, `st.success` when nothing needs attention) and the gap-days number input (1–90) in the Goals & settings tab

**Checkpoint**: flags with evidence available in CLI and web

---

## Phase 6: User Story 4 - Compare Two Sessions Side by Side (Priority: P4)

**Goal**: per-measure comparison with change, % change, and improvement direction.

**Independent Test**: compare two seeded sessions with known values and check every row.

### Tests for User Story 4 (write first, MUST FAIL)

- [X] T035 [P] [US4] Add the comparison section to `tests/test_ptlog_review.py`: session A (avg ROM 80, form 85, 8/10, 2.40 s, partial 0%) vs B (92, 88, 10/10, 2.10 s, 10%): rows for `reps_completed, avg_form, avg_rom, avg_duration, tempo_sd, partial_share` with `change` (+2, +3.0, +12.0, −0.30, …, +10.0), `pct_change` for reps/form/rom only (25.0, 3.5, 15.0) and None elsewhere, `better` higher/higher/higher/informational/lower/lower; different exercises → `ComparisonError` mentioning "within one exercise"; two shared exercises without `exercise=` → `ComparisonError` listing them; a zero-rep session gives `a`/`b` None for rep-based measures and `change` None; `pct_change` None when the base is 0
- [X] T036 [P] [US4] Extend `tests/test_cli_ptlog.py`: `review compare <a> <b>` prints a table with a `better when` column; different exercises → exit 1; `--json` parses `rows`
- [X] T037 [P] [US4] Extend `tests/test_app_pages.py`: the Compare tab renders with two session selectboxes and a comparison dataframe without exception

### Implementation for User Story 4

- [X] T038 [US4] Implement `compare(store, session_a, session_b, exercise=None) -> Comparison` in `src/ptlog/review.py` (depends on T035) with `BETTER = {"reps_completed": "higher", "avg_form": "higher", "avg_rom": "higher", "avg_duration": "informational", "tempo_sd": "lower", "partial_share": "lower"}`; add `views.comparison_rows(comparison)` with unit-formatted cells
- [X] T039 [US4] `interfaces/cli.py` (depends on T036, T038): add `review compare`
- [X] T040 [US4] `interfaces/app.py` (depends on T037, T038): implement the Compare tab

**Checkpoint**: comparisons available

---

## Phase 7: User Story 5 - Goals per Patient and Exercise (Priority: P5)

**Goal**: set, update, clear goals; trend and plateau rule use them.

**Independent Test**: set → shown on trend; update reps only → ROM unchanged; clear → gone.

### Tests for User Story 5 (write first, MUST FAIL)

- [ ] T041 [P] [US5] Extend `tests/test_cli_ptlog.py`: `review goal set P-017 --exercise "Knee Extension" --rom 120 --reps 10` prints `Goal for Knee Extension: ROM 120° | reps 10`; `--reps 12` alone keeps ROM 120 in `review goals P-017`; `--rom 200` → exit 1 with the range; `review goal clear` prints `Cleared goal for Knee Extension`; `review trends` after setting shows the goal line and progress percentage
- [ ] T042 [P] [US5] Extend `tests/test_app_pages.py`: the Goals & settings tab renders the goal form (exercise selectbox, ROM and reps number inputs, set and clear buttons) without exception

### Implementation for User Story 5

- [ ] T043 [US5] `interfaces/cli.py` (depends on T041): add `review goals`, `review goal set`, `review goal clear` (store CRUD from T008)
- [ ] T044 [US5] `interfaces/app.py` (depends on T042): implement the goal form in the Goals & settings tab with `st.error` on `GoalValidationError`

**Checkpoint**: goals manageable from CLI and web

---

## Phase 8: User Story 6 - Export a Review Summary (Priority: P6)

**Goal**: text report and CSV of trends, flags, goals, and reviews for a patient and period; removed with the patient.

**Independent Test**: build a patient with two exercises, a goal, a flag, and one review; export both; verify sections and rows.

### Tests for User Story 6 (write first, MUST FAIL)

- [ ] T045 [P] [US6] Write `tests/test_ptlog_review_exports.py`: `review.review_summary(store, "P-017", "all", now)` has `trends` per exercise, `flags`, `goals` with progress, `sessions` newest first each with `measures` and `review`; `to_review_report(summary)` equals an expected string built in the test from the seeded values (header lines `PT REVIEW SUMMARY`, `Patient: P-017`, `Period: all time`, `Generated: <fixed clock>`, `TRENDS` table with the column header from `contracts/exports.md`, `FLAGS` lines, `GOALS`, `SESSIONS` with `reviewed …` and `pending review`); `to_review_csv(summary)` starts with the exact header row, uses `\r\n`, has one row per session per exercise newest first, empty cells for missing values, `interrupted` true/false, `review_status` reviewed/pending; `write_review_export(store, "P-017", "all", "review_report", tmp_path, now)` writes `P-017_review_all_<YYYYMMDD_HHMMSS>.txt`, records a `review_exports` row, and `delete_patient` removes the file; two exports with the same clock are identical
- [ ] T046 [P] [US6] Extend `tests/test_cli_ptlog.py`: `review export P-017 --format all --out DIR` prints two paths; `--format csv` one; unknown patient → exit 1
- [ ] T047 [P] [US6] Extend `tests/test_app_pages.py`: the Export tab renders two download buttons labelled `Review report (text)` and `Review data (CSV)`

### Implementation for User Story 6

- [ ] T048 [US6] Implement `review_summary(store, patient_id, period="all", now=None) -> ReviewSummary` in `src/ptlog/review.py` (depends on T045)
- [ ] T049 [P] [US6] Implement `to_review_report` in `src/ptlog/exports/review_report.py` per `contracts/exports.md` (depends on T045)
- [ ] T050 [P] [US6] Implement `to_review_csv` in `src/ptlog/exports/review_csv.py` per `contracts/exports.md` (depends on T045)
- [ ] T051 [US6] Add `write_review_export(store, patient_id, period, fmt, out_dir=None, now=None) -> Path` and `REVIEW_FORMATS` to `src/ptlog/exports/__init__.py` (depends on T048–T050)
- [ ] T052 [US6] `interfaces/cli.py` (depends on T046, T051): add `review export`
- [ ] T053 [US6] `interfaces/app.py` (depends on T047, T051): implement the Export tab with period selector and two `st.download_button`s

**Checkpoint**: review summaries exportable; all six stories complete

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T054 [P] Add "Update 4 — Review Over Time" to `docs/UPDATES.md` (measures, trends, flags with rules and thresholds, reviews, goals, gap threshold, comparison, exports, retired progress/PT Summary views and session tracker, review CLI group)
- [ ] T055 [P] Update `README.md`: review commands in Quick Start, Project Structure (add `measures.py`, `flags.py`, `review.py`, review exports; remove `session_tracker.py`), feature bullet
- [ ] T056 [P] Update `docs/PROJECT_OVERVIEW.md`: architecture tree and Key Files (remove `session_tracker.py`, add the review modules)
- [ ] T057 Run `specs/002-review-over-time/quickstart.md` steps 1–8 against a scratch database (step 9 via `tests/test_app_pages.py`) and record outcomes under `## Notes` in `specs/002-review-over-time/checklists/requirements.md`
- [ ] T058 Final gate: full suite green; `git diff --stat main -- analyze.py src/form_assessment.py src/utils.py config.yaml tests/test_analysis.py tests/test_form_assessment.py requirements.txt` empty; `grep -rn session_tracker --include='*.py' .` (outside `.venv`) empty; `grep -rnE '^(import|from) (socket|urllib|http|requests)' src/ptlog/` empty; performance test in `tests/test_ptlog_review.py` (200 sessions: trend, flags, pending each < 2 s) passing; then run `/speckit-analyze`

---

## Dependencies & Execution Order

- **Setup → Foundational → US1 → US2 → US3 → US4 → US5 → US6 → Polish** is the intended order.
- US2–US6 each depend on Foundational and on US1's `review.py`/`views.py`/CLI group/`page_review` scaffolding (same files), so they run sequentially in practice even though their logic is independent.
- US5's store CRUD is already in Foundational (T008) because US1's trend and US3's plateau rule read goals; US5 adds the interfaces and validation coverage.
- US6 depends on US2 (reviews in the summary) and US3 (flags in the summary).
- T019 (retire `session_tracker`) must follow T017/T018, which remove its last consumers.

### Parallel Opportunities

- Phase 2: T003, T004, T005, T006 together; then T007; then T008, T009, T010 together
- Each story: its test tasks together; implementation tasks touching `review.py`, `cli.py`, and `app.py` sequentially
- Phase 9: T054, T055, T056 together

---

## Implementation Strategy

1. Setup + Foundational (10 tasks) → schema v2 and measures
2. US1 (9 tasks) → **MVP checkpoint**: trends replace progress views; commit
3. US2 → US3 → US4 → US5 → US6, suite green at each checkpoint
4. Polish → docs, quickstart run, final gate, `/speckit-analyze`

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- Thresholds and windows are quoted in tasks from FR-014; do not loosen them at implementation time
- Never edit the engine files or their tests (constitution I)
- Commit only when the suite is green and only when asked
