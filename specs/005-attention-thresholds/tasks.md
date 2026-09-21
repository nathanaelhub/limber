---
description: "Task list for feature 005: configurable attention thresholds"
---

# Tasks: Configurable Attention Thresholds

**Input**: Design documents from `/specs/005-attention-thresholds/`

**Tests**: REQUIRED (constitution IV): each test task fails before its implementation task.
Suite: `.venv/bin/python -m pytest tests`.

## Phase 1: Setup

- [X] T001 Create branch `005-attention-thresholds`, confirm the suite is green, commit the design documents under specs/005-attention-thresholds/

## Phase 2: Foundational

- [X] T002 [P] Write failing tests in tests/test_ptlog_thresholds.py: registry has the eight keys in order with the units, defaults, and ranges of data-model.md; `validate` accepts bounds, rejects out-of-range, non-integers, booleans, and unknown keys with a message containing the range and unit; `resolve` precedence patient → installation → default with origins; unknown stored keys ignored; `Thresholds.defaults()`, `value`, `origin`, `overridden`
- [X] T003 Implement src/ptlog/thresholds.py and `ThresholdValidationError` in src/ptlog/models.py
- [X] T004 [P] Write failing tests in tests/test_ptlog_thresholds_store.py: a fresh store is at schema v4 with both tables; a v3 file with a `review_settings` row (gap 14) and `tracker_settings` 70 migrates to a patient `practice_gap` 14 and installation `adherence` 70 (adherence 60 copies nothing); patient set/reset/reset-all and installation set/reset/restore; validation before write; unknown patient raises; delete cascades and ID change follows; `get/set_gap_days` and `get/set_adherence_threshold` read and write the new tables; `effective_thresholds` and `effective_thresholds_all`
- [X] T005 Implement schema v4 and the threshold methods in src/ptlog/store.py (before module-level helpers); update version-list assertions in earlier tests to read `MIGRATIONS`

## Phase 3: User Story 1 - Tune a patient's flag thresholds (P1) 🎯 MVP

- [X] T006 [P] [US1] Write the no-override regression test in tests/test_ptlog_flags.py: for the existing rule fixtures, `evaluate(..., Thresholds.defaults(), now)` and `evaluate(..., 7, now)` return the same rules, sessions, and values (apart from the added `threshold` value)
- [X] T007 [P] [US1] Write failing rule tests in tests/test_ptlog_flags.py: each rule fires or stays silent on either side of a custom threshold (form_drop 8, rom_regression 5, rom_plateau 6, target_reps_sessions 2 and 4 including NotEvaluated minimums, partial_share 15 / partial_rise 5, practice_gap 3); every threshold-driven flag has `values["threshold"]` and its evidence contains `threshold <n> <unit>`
- [X] T008 [US1] Change src/ptlog/flags.py: rules take `thresholds: Thresholds = Thresholds.defaults()`; `evaluate` accepts a `Thresholds` or an int gap; evidence states the threshold; docstrings name the defaults
- [X] T009 [P] [US1] Write failing tests in tests/test_ptlog_review.py: `flags_for` and `session_review_view`/`review_summary` use the patient's effective thresholds (6° drop: silent at default, flagged at 5, silent after reset; installation value applies without an override)
- [X] T010 [US1] Resolve and pass thresholds in src/ptlog/review.py
- [X] T011 [P] [US1] Write failing CLI tests in tests/test_cli_ptlog.py for `review thresholds`: list lines with value, unit, origin, default, meaning; `--set k=v ...` atomic validation with exit 1 and range message; `--reset`, `--reset-all`; unknown patient exit code as other review commands; `review flags` reflects the change
- [X] T012 [US1] Add `threshold_lines` / `threshold_rows` to src/ptlog/views.py and the `review thresholds` command to interfaces/cli.py
- [X] T013 [P] [US1] Write a failing page test in tests/test_app_pages.py: Review → Goals & settings shows the thresholds table and form; saving `rom_regression` 5 stores an override; "Reset all to defaults" clears it
- [X] T014 [US1] Implement the thresholds editor in `_review_goals_settings` in interfaces/app.py (replaces the gap-days control)
- [X] T015 [US1] Run the suite; checkpoint commit

## Phase 4: User Story 2 - Per-patient adherence threshold (P2)

- [X] T016 [P] [US2] Write failing tests in tests/test_ptlog_tracker.py: two patients at 55% adherence, installation 60, one override 50 → only the other is marked for adherence in roster and queue; reset restores; roster uses `effective_thresholds_all` (one load); per-patient gap threshold still honoured; performance test still inside its budget
- [X] T017 [US2] Use effective thresholds in src/ptlog/tracker.py (`snapshot`, `roster`, `adherence_for`, `queue`)
- [X] T018 [P] [US2] Write failing tests: `tracker adherence P-017` prints `Attention threshold: 50% (patient)` in tests/test_cli_ptlog.py; the adherence section in tests/test_app_pages.py shows the same
- [X] T019 [US2] Implement in src/ptlog/views.py, interfaces/cli.py, interfaces/app.py; checkpoint commit

## Phase 5: User Story 3 - Installation defaults (P3)

- [X] T020 [P] [US3] Write failing CLI tests for `review thresholds --installation` (list, `--set`, `--reset`, `--restore-defaults`, patient overrides untouched, origin `installation` in a patient listing) and a page test for the Tracker installation editor
- [X] T021 [US3] Implement in interfaces/cli.py and interfaces/app.py (replaces the single adherence control; `tracker settings --adherence-threshold` keeps working); checkpoint commit

## Phase 6: User Story 4 - Thresholds in exports (P4)

- [X] T022 [P] [US4] Write failing tests in tests/test_ptlog_review_exports.py: `ReviewSummary.thresholds`; the report has a thresholds section listing eight values with units and marks overrides with origin, or states built-in defaults were used; the CSV carries threshold rows; existing golden expectations updated only for the added section
- [X] T023 [US4] Implement in src/ptlog/review.py, src/ptlog/exports/review_report.py, src/ptlog/exports/review_csv.py; checkpoint commit

## Phase 7: Polish

- [ ] T024 [P] Update docs/UPDATES.md (Update 7), README.md, docs/PROJECT_OVERVIEW.md
- [ ] T025 Run quickstart steps 1-6 under bash against a temp copy of the database; record results in checklists/requirements.md; final commit and merge

## Dependencies

Phase 2 blocks all stories. US2, US3, US4 each depend only on Phase 2 and US1's `views` helpers. MVP = T001-T015.
