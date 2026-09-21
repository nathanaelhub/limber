# Tasks: Threshold Refinements

Tests are REQUIRED and precede their implementation. Suite: `.venv/bin/python -m pytest tests`.

## Phase 1-2: Setup and foundation

- [X] T001 Branch `006-threshold-refinements`; commit design documents under specs/006-threshold-refinements/
- [X] T002 [P] Failing tests in tests/test_ptlog_thresholds.py: `EXERCISE_KEYS` (six), `validate_exercise_key` rejects `practice_gap`/`adherence` with "whole patient" and unknown keys; `resolve(patient, installation, exercise=)` layering and origin "exercise"; two-argument calls unchanged
- [X] T003 Implement in src/ptlog/thresholds.py
- [X] T004 [P] Failing tests in tests/test_ptlog_thresholds_store.py: schema v5 tables; v4 file upgrades keeping values with empty history; exercise set/get/reset/reset-all; patient reset-all removes exercise overrides; `effective_thresholds(patient, exercise)`; `effective_thresholds_by_exercise(_all)`; cascade on delete and ID change
- [X] T005 Implement schema v5 and exercise methods in src/ptlog/store.py

## Phase 3: US1 per-exercise thresholds (P1) 🎯

- [X] T006 [P] [US1] Failing tests in tests/test_ptlog_flags.py: `evaluate(..., per_exercise={...})` applies an exercise's set to that exercise only; without it results equal feature 005 (FR-009)
- [X] T007 [US1] Implement `per_exercise` in src/ptlog/flags.py
- [X] T008 [P] [US1] Failing tests in tests/test_ptlog_review.py and tests/test_ptlog_tracker.py: 6° drop in two exercises, override on one → only it is flagged in `flags_for`, `review_summary`, roster open-flag count; roster still bulk-loads once
- [X] T009 [US1] Implement in src/ptlog/review.py and src/ptlog/tracker.py
- [X] T010 [P] [US1] Failing CLI tests in tests/test_cli_ptlog.py for `--exercise` (list six lines, set, reset, reset-all, rejected keys, rejected with `--installation`) and a page test for the "Applies to" selector in tests/test_app_pages.py
- [X] T011 [US1] Implement in src/ptlog/views.py, interfaces/cli.py, interfaces/app.py; suite; checkpoint commit

## Phase 4: US2 change history (P2)

- [X] T012 [P] [US2] Failing tests in tests/test_ptlog_thresholds_store.py: set/change/reset produce three rows with old/new; unchanged save adds none; bulk set logs only changed keys; reset-all and restore-defaults log one row per removed key; legacy `set_gap_days`/`set_adherence_threshold` log; patient history includes installation rows; cascade on delete
- [X] T013 [US2] Implement `_log_change`, `threshold_history()` and `ThresholdChange` in src/ptlog/store.py and src/ptlog/models.py
- [X] T014 [P] [US2] Failing tests: `history_lines` in tests/test_ptlog_views.py; CLI `--history` in tests/test_cli_ptlog.py; history expanders in tests/test_app_pages.py
- [X] T015 [US2] Implement in src/ptlog/views.py, interfaces/cli.py, interfaces/app.py; suite; checkpoint commit

## Phase 5: US3 exports (P3)

- [X] T016 [P] [US3] Failing tests in tests/test_ptlog_review_exports.py: report lists exercise override lines; CSV cell per row's exercise marks `(exercise)`
- [X] T017 [US3] Implement in src/ptlog/review.py and src/ptlog/exports/; checkpoint commit

## Phase 6: Polish

- [X] T018 Update docs/UPDATES.md (Update 8), README.md; run quickstart 1-5 on a temp database; record results in checklists/requirements.md; final commit and merge
