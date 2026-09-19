# Tasks: Multi-Patient PT Tracker

**Input**: Design documents from `/specs/003-pt-tracker/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (tracker-api.md, cli.md, exports.md), quickstart.md

**Tests**: REQUIRED (constitution IV). Tests are written first and MUST fail before implementation; the full suite
(`.venv/bin/python -m pytest tests`) MUST be green at every checkpoint. Tests use `tmp_path` databases, the
fixed clock, and the `make_session` fixture; no camera, network, or model weights. Engine tests are never edited.

**Organization**: Tasks are grouped by user story so each story is an independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US6 from spec.md
- Exact file paths are included in every task

## Path Conventions

Single project: `src/ptlog/` package, flat `tests/`, interfaces in `interfaces/`. Branch `003-pt-tracker` is
created from `main` before T001.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Create `tests/fixtures/config_small.yaml` with two exercises (`knee_extension` display "Knee Extension" side left, `partial_squat` display "Partial Squat" side bilateral, each with up/down angles and target_reps) and one program (`mini_knee`, name "Mini Knee", exercises `[knee_extension, partial_squat]`), and add a `today` helper to `tests/conftest.py`: `D0_DATE = date(2026, 3, 23)` plus a `caseload` fixture factory `caseload(store, clock, spec)` that registers patients and records sessions from a compact description (`{"P-017": [(days_ago, exercise, [(form, rom, dur), ...]), ...]}`) using `make_session`
- [ ] T002 [P] Create `src/ptlog/programs.py`, `src/ptlog/adherence.py`, `src/ptlog/tracker.py`, `src/ptlog/exports/roster_csv.py` with module docstrings only

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: migration 3, models, the program catalog, store primitives, and the adherence computation every story reads

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 [P] Write the foundation section of `tests/test_ptlog_tracker.py` (must FAIL first): a database at version 2 (apply `MIGRATIONS[:2]`, insert a patient, a session, a review, and a goal) opens at version 3 with tables `assignments`, `discharges`, `tracker_settings`, `schema_version` rows `[1, 2, 3]`, the review and goal still readable, and `tracker_settings` holding one row with `adherence_threshold` 60; `models.ASSIGNMENT_STATUSES == ("scheduled", "active", "completed", "superseded")`; `models.QUEUE_KINDS == ("pending_review", "attention_flag", "practice_gap", "low_adherence")`; dataclasses `Program`, `Assignment`, `Discharge`, `AdherenceWeek`, `Adherence`, `RosterRow`, `QueueItem`, `QueueResult`, `TrackerSettings` with the fields in data-model.md; `METRIC_DEFINITIONS["adherence_pct"]["unit"] == "percent"`; `ProgramValidationError` and `AssignmentValidationError` subclass `PTLogError`
- [ ] T004 [P] Write `tests/test_ptlog_programs.py` (must FAIL first): `load_catalog(config_small)` returns two exercises with display names and one program `mini_knee` with name, description (empty allowed), and ordered keys; `list_programs()` on the real `config.yaml` returns four programs including `knee_rehab` with five exercises in config order; `get_program("nope")` is None; `exercise_name("knee_extension_right")` is "Knee Extension (Right)" and an unknown key returns the key; `validate_exercise_keys(["knee_extension", "bogus", "also_bogus"])` raises `ProgramValidationError` naming both unknown keys; `validate_exercise_keys([])` raises "at least one"; `custom_program(["squat"])` has id `custom` and name `Custom`; `importer.exercise_catalog()` returns the same display-name map as the programs catalog (delegation)
- [ ] T005 [P] Write the store-primitives section of `tests/test_ptlog_tracker.py` (must FAIL first): `assign_program("P-017", "knee_rehab", "Knee Rehabilitation", keys, 3, date(2026,3,1))` stores JSON keys and returns an `Assignment` with `created_at`; a second assignment starting 2026-03-15 sets the first's `end_date` to `2026-03-14` and `assignment_history` lists both newest start first; `active_assignment("P-017", on=date(2026,3,20))` is the second and on 2026-03-10 the first; validation: `sessions_per_week` 0 and 15 → `AssignmentValidationError` "1–14", `end_date` before start → "end date", empty keys → "at least one", unknown key → `ProgramValidationError`; builtin patient → `BuiltinPatientError`; unknown patient → `PatientNotFoundError`; `discharge("P-017", date(2026,3,20), "goals met")` returns a `Discharge`, `active_patients()` excludes P-017 and `discharged_patients()` lists it with the reason; `discharge` with reason "seen by Jane Doe" → `ReviewValidationError`-compatible `PTLogError` naming "name"; `reactivate` returns True then False; builtin discharge refused; `get_adherence_threshold()` defaults 60, `set_adherence_threshold(30)` persists, 0 and 101 rejected; `latest_review` returns the review of the most recent session by start time or None; `delete_patient` removes assignments and discharge rows
- [ ] T006 [P] Write `tests/test_ptlog_adherence.py` (must FAIL first) with an `Assignment` starting 2026-03-01, 3 per week, keys `[knee_extension, partial_squat]`, and `make_session`-built sessions: `assignment_status` scheduled (today before start), active, completed (end 2026-03-20, today 2026-03-25), superseded (end before start); `week_bounds(a, 1) == (2026-03-01, 2026-03-07)` and `week_index(a, 2026-03-08) == 2`; `compute` with today 2026-03-22 and sessions counted 3, 1, 0 in weeks 1–3 and 2 in week 4 → weeks 1–3 complete with `recorded` 3/1/0, week 3 `missed`, week 4 `in_progress` with recorded 2, `percentage == 44`; 5 sessions in a week → `counted == 3` and percentage capped at 100; a week with only knee-extension sessions lists `partial_squat` in `exercises_missing`; a session with zero counted reps does not count; a session on 2026-03-01 at 00:00 is in week 1 and one at 2026-03-07 23:59 is in week 1; today 2026-03-03 → `percentage None`, note "first week in progress"; `compute(None, …)` → note "no program"; a completed assignment stops at its end date; a scheduled assignment → note "starts on 2026-03-01"; superseded → note "superseded"; a five-week-old assignment shows only the last four complete weeks; an assignment with no sessions at all after three complete weeks gives every week `missed` and `percentage == 0`
- [ ] T007 Implement the additions to `src/ptlog/models.py` (depends on T003): `ASSIGNMENT_STATUSES`, `QUEUE_KINDS`, `ADHERENCE_THRESHOLD_DEFAULT = 60`, dataclasses `Program(id, name, description, exercise_keys, exercise_names)`, `Assignment(id, patient_id, program_id, program_name, exercise_keys, sessions_per_week, start_date, end_date, created_at)`, `Discharge(patient_id, discharged_on, reason, created_at)`, `AdherenceWeek(index, start, end, planned, recorded, counted, exercises_performed, exercises_missing, missed, in_progress)`, `Adherence(assignment, status, weeks, percentage, note)`, `RosterRow` (fields per data-model.md), `QueueItem(kind, patient_id, target, session_id, age_days, description)`, `QueueResult(items, totals)`, `TrackerSettings(adherence_threshold)`; `METRIC_DEFINITIONS["adherence_pct"]` (percent) and `["sessions_per_week"]` (count); the two exceptions
- [ ] T008 Implement `src/ptlog/programs.py` (depends on T004, T007): `Catalog`, `load_catalog` (cached per path, default `REPO_ROOT / "config.yaml"`), `list_programs`, `get_program`, `exercise_name`, `validate_exercise_keys`, `custom_program`; make `importer.exercise_catalog()` delegate to it
- [ ] T009 Implement in `src/ptlog/store.py` (depends on T005, T007, T008): `SCHEMA_V3_SQL` exactly as data-model.md, `MIGRATIONS.append((3, …))`, `SCHEMA_VERSION = 3`; `assign_program` (builtin refused, keys validated through `programs.validate_exercise_keys`, per-week 1–14, end ≥ start, supersession per research D5), `active_assignment`, `assignment_history`, `discharge` (reason via `validate_notes`), `reactivate`, `get_discharge`, `active_patients` (unassigned first, then alphabetical, excluding discharged), `discharged_patients`, `get_adherence_threshold`, `set_adherence_threshold`, `latest_review`
- [ ] T010 Implement `src/ptlog/adherence.py` (depends on T006, T007): `assignment_status`, `week_bounds`, `week_index`, `compute(assignment, sessions, today, window_weeks=4)` per research D2–D4 (a session counts when any rep has `out_of_range == 0`; coverage by `exercise_key`; window = last four complete weeks not after the end date plus the current week when active)

**Checkpoint**: schema at v3, catalog readable, assignments and discharges storable, adherence computable

---

## Phase 3: User Story 1 - See the Caseload at a Glance (Priority: P1) 🎯 MVP

**Goal**: the roster with every column, the attention sort, and the filters, on the CLI and the Tracker page.

**Independent Test**: seed three patients (one with a pending review and a flag, one quiet, one discharged), run `tracker roster`, and check every column and the order.

### Tests for User Story 1 (write first, MUST FAIL)

- [ ] T011 [P] [US1] Add the roster section to `tests/test_ptlog_tracker.py`: with `now = D0`, patient A (sessions 2 and 5 days ago, one reviewed with next step `hold`, the other pending, form scores 90, 86, 81, 75 over four sessions so `form_declining` fires), patient B (one session 20 days ago, reviewed), patient C discharged, patient D (no sessions), and the built-in patient holding one session: `tracker.roster(store, now)` lists unassigned, A, B, D and not C; A's row has `sessions_7d == 2`, `sessions_30d == 4`, `pending_reviews == 1`, `open_flags == 1`, `last_next_step == "hold"`, `days_since_last == 2`, `program_name == "none"`, `adherence_pct is None`, `adherence_note == "no program"`; B's has `days_since_last == 20`, `practice_gap True`; D's has `days_since_last None` and zeros; the unassigned row has `is_builtin True`; attention order is A first, then B (gap), then D and unassigned; `sort="id"` orders by id with unassigned first; after `assign_program(A, …)` starting 21 days ago with 3/week and A's two sessions in the last complete week, `adherence_pct` equals `adherence.compute`'s percentage; `program="knee_rehab"` filter keeps only A; `needs_attention=True` keeps A and B; `snapshot()` loads `sessions_in_period` once per patient (assert via a counting subclass)
- [ ] T012 [P] [US1] Add to `tests/test_ptlog_views.py`: `views.roster_table_rows(rows)` formats `days_since_last` None as "no sessions yet", `adherence_pct` None as the note, `practice_gap` as "yes"/"no", `last_next_step` None as "none", and uses `metric_label("adherence_pct")` in the column map returned by `views.roster_columns()`
- [ ] T013 [P] [US1] Extend `tests/test_cli_ptlog.py` with a `seed_caseload(tmp_db)` helper (three patients with the histories of T011 written in-process) and tests: `tracker roster` prints the header and one row per active patient with A first; `--sort id` reorders; `--needs-attention` drops D; `--program knee_rehab` after an assignment keeps A; `--json` parses with the RosterRow fields; `tracker programs` lists the four config programs and `custom`
- [ ] T014 [P] [US1] Extend `tests/test_app_pages.py`: `PAGES` gains `"tracker"`; `_tracker_page(seeded_env, section)` mirrors `_review_page` with `st.session_state["tracker_tab"]`; `test_tracker_page_roster` asserts a dataframe with a "pending reviews (count)" column and no exception

### Implementation for User Story 1

- [ ] T015 [US1] Implement in `src/ptlog/tracker.py` (depends on T011): `PatientSnapshot` (patient, rows from `list_sessions`, loaded sessions, active assignment, adherence, flags result, pending count, latest review), `snapshot(store, patient, now)` per research D6, `roster(store, now=None, sort="attention", program=None, needs_attention=False)`, `attention_key(row)` per research D7 (`open_flags` excludes practice-gap flags; `practice_gap` is a bool), `_row_from_snapshot`
- [ ] T016 [US1] Add to `src/ptlog/views.py` (depends on T012, T015): `roster_columns()`, `roster_table_rows(rows)`, `fmt_days(value)`
- [ ] T017 [US1] `interfaces/cli.py` (depends on T013, T015, T016): add the `tracker` group with `roster` and `programs` per `contracts/cli.md`
- [ ] T018 [US1] `interfaces/app.py` (depends on T014, T015, T016): add `page_tracker()` with a section radio (key `tracker_tab`: Roster, Queue, Adherence, Discharged, Export), implement the Roster section (sort and filter controls, `st.dataframe` of `roster_table_rows`), placeholders for the other sections, register `'tracker': '📋 Tracker'` in the sidebar `pages` dict and route it in `main()`

**Checkpoint**: MVP — the caseload is visible with every column, sorted by attention

---

## Phase 4: User Story 2 - Assign a Program (Priority: P2)

**Goal**: assign pre-built or custom programs from the CLI and the Patients page, with supersession and history.

**Independent Test**: assign a pre-built program, then a custom one, and confirm the first is ended the day before the second starts and both appear in the history.

### Tests for User Story 2 (write first, MUST FAIL)

- [ ] T019 [P] [US2] Extend `tests/test_cli_ptlog.py`: `tracker assign P-017 --program knee_rehab --per-week 3 --start 2026-03-01` prints `Assigned Knee Rehabilitation to P-017: 3 sessions/week from 2026-03-01`; a second `assign … --exercises squat,pushup --start 2026-03-15` prints the assigned line plus `Ended previous assignment (Knee Rehabilitation) on 2026-03-14`; `tracker assignments P-017` lists both newest first with statuses; `--exercises bogus` → exit 1 naming `bogus`; `--per-week 15` → exit 1; `--end 2026-02-01` with start 2026-03-01 → exit 1; assigning to `unassigned` → exit 1; `--json` on `assignments` parses
- [ ] T020 [P] [US2] Extend `tests/test_app_pages.py`: `test_patients_page_program_form` renders the Patients page and asserts a selectbox whose options include the four config program names and "Custom", a number input labelled with "sessions per week", a date input, and a "Assign program" button; after `store.assign_program(...)` in the fixture, the page shows the history dataframe with the program name

### Implementation for User Story 2

- [ ] T021 [US2] `interfaces/cli.py` (depends on T019): add `tracker assign` (mutually exclusive `--program` / `--exercises`, `--per-week` default 3, `--start` default today, `--end`) and `tracker assignments`; resolve program name via `programs.get_program`
- [ ] T022 [US2] `interfaces/app.py` (depends on T020): in `page_patients()` add a "Program" section for the selected patient: program selectbox (config programs plus Custom), a multiselect of exercise keys shown by display name when Custom, sessions per week, start and end date inputs, an "Assign program" button calling `store.assign_program`, and the assignment history table with status from `adherence.assignment_status`

**Checkpoint**: programs assignable with history

---

## Phase 5: User Story 3 - See Adherence to the Plan (Priority: P3)

**Goal**: the week-by-week adherence view on the CLI and the Tracker page.

**Independent Test**: the 3/1/0 + current-week history from T006 rendered as rows with a 44% total.

### Tests for User Story 3 (write first, MUST FAIL)

- [ ] T023 [P] [US3] Add the adherence section to `tests/test_ptlog_tracker.py`: `tracker.adherence_for(store, "P-017", today)` equals `adherence.compute` over the patient's sessions since the assignment start; `views.adherence_lines(adherence)` renders `week 3  2026-03-15..2026-03-21  0/3  missed | performed: — | missing: knee_extension, partial_squat`, the current week with `in progress`, and `Adherence: 44% over 3 complete weeks`; the no-program and first-week notes render as single lines
- [ ] T024 [P] [US3] Extend `tests/test_cli_ptlog.py`: `tracker adherence P-017` prints the assignment line, the weekly rows, and the percentage line; unknown patient → exit 1; `--json` parses with `weeks` and `percentage`
- [ ] T025 [P] [US3] Extend `tests/test_app_pages.py`: the Adherence section renders a weekly dataframe for the sidebar patient without exception, and "no program" when none is assigned

### Implementation for User Story 3

- [ ] T026 [US3] Implement `adherence_for(store, patient_id, today=None)` in `src/ptlog/tracker.py` and `adherence_lines(adherence)` plus `adherence_table_rows(adherence)` in `src/ptlog/views.py` (depends on T023)
- [ ] T027 [US3] `interfaces/cli.py` (depends on T024, T026): add `tracker adherence`
- [ ] T028 [US3] `interfaces/app.py` (depends on T025, T026): implement the Adherence section (weekly table with exercises performed/missing, percentage or note)

**Checkpoint**: adherence visible per patient

---

## Phase 6: User Story 4 - Work Through a Cross-Patient Queue (Priority: P4)

**Goal**: the queue of four kinds, oldest first, resolved by action; the adherence threshold setting.

**Independent Test**: one item of each kind across three patients, then review the pending session and see it leave.

### Tests for User Story 4 (write first, MUST FAIL)

- [ ] T029 [P] [US4] Add the queue section to `tests/test_ptlog_tracker.py`: P-017 with pending sessions 5 and 2 days old and P-018 with one 9 days old → `pending_review` items ordered P-018, P-017 (older), P-017 (newer) with `session_id`, `target == "session:<id>"`, `age_days`; a form-declining history → one `attention_flag` item with the rule in `description`; a patient 9 days since last session with gap 7 → `practice_gap` item with `age_days == 9`; a patient with an assignment at 40% → `low_adherence` item with "40%" and "60%" in the description, gone after `set_adherence_threshold(30)`; `queue().totals` counts per kind; after `set_review` on a pending session the item is gone; a discharged patient contributes nothing; an empty caseload gives no items; performance: 50 patients × 20 sessions (built with `make_session`, `PRAGMA synchronous=OFF`) — `roster()` and `queue()` each under 3 s
- [ ] T030 [P] [US4] Extend `tests/test_cli_ptlog.py`: `tracker queue` prints sections with counts and one line per item, or `Caseload is up to date.`; `tracker settings` prints `Adherence threshold: 60%`; `--adherence-threshold 30` updates; `0` → exit 1
- [ ] T031 [P] [US4] Extend `tests/test_app_pages.py`: the Queue section renders without exception and shows either items or the up-to-date message

### Implementation for User Story 4

- [ ] T032 [US4] Implement `queue(store, now=None) -> QueueResult` in `src/ptlog/tracker.py` per research D8 (reuses `snapshot`), and `queue_lines(result)` in `src/ptlog/views.py` (depends on T029)
- [ ] T033 [US4] `interfaces/cli.py` (depends on T030, T032): add `tracker queue` and `tracker settings`
- [ ] T034 [US4] `interfaces/app.py` (depends on T031, T032): implement the Queue section (one expander per kind with counts, items as warnings/info with the target) and the threshold number input under the Queue section

**Checkpoint**: a working caseload work list

---

## Phase 7: User Story 5 - Discharge and Reactivate (Priority: P5)

**Goal**: discharge with reason and date, exclusion from roster and queue, a discharged list, reactivation; on CLI and web.

**Independent Test**: discharge a patient with a pending review, confirm exclusion and the discharged list, reactivate, confirm return with data.

### Tests for User Story 5 (write first, MUST FAIL)

- [ ] T035 [P] [US5] Extend `tests/test_cli_ptlog.py`: `tracker discharge P-018 --reason "goals met"` prints `Discharged P-018 on <today>`; `tracker roster` no longer lists P-018 and `tracker queue` has none of its items; `tracker discharged` lists P-018 with the reason; `--reason "moved to Jane Doe clinic"` → exit 1 naming "name"; `tracker discharge unassigned` → exit 1; `tracker reactivate P-018` prints `Reactivated P-018` then `P-018 is already active`; `sessions list --patient P-018` still shows the sessions
- [ ] T036 [P] [US5] Extend `tests/test_app_pages.py`: the Discharged section renders (empty message or table); the Patients page shows a "Discharge patient" button for an active selected patient and "Reactivate" for a discharged one

### Implementation for User Story 5

- [ ] T037 [US5] `interfaces/cli.py` (depends on T035): add `tracker discharge`, `tracker reactivate`, `tracker discharged`
- [ ] T038 [US5] `interfaces/app.py` (depends on T036): implement the Discharged section (table with reactivate buttons) and the discharge/reactivate control (date, reason, button) on the Patients page

**Checkpoint**: caseload membership manageable

---

## Phase 8: User Story 6 - Export the Roster (Priority: P6)

**Goal**: roster CSV with units, named by time only.

**Independent Test**: export with three patients and compare rows to the roster.

### Tests for User Story 6 (write first, MUST FAIL)

- [ ] T039 [P] [US6] Write `tests/test_ptlog_roster_export.py`: `to_roster_csv(rows, now)` starts with the exact header from `contracts/exports.md`, uses `\r\n`, one row per active patient in attention order, empty cells for None, `practice_gap` true/false; `write_roster_export(store, tmp_path, now=D0)` writes `roster_20260323_091500.csv`; the filter state does not affect the export (all active patients); extend `tests/test_cli_ptlog.py` with `tracker export-roster --out DIR` printing the path; extend `tests/test_app_pages.py` with the Export section showing a "Roster (CSV)" download button
- [ ] T040 [US6] Implement `src/ptlog/exports/roster_csv.py` (`to_roster_csv`, `write_roster_export`) and register `to_roster_csv` in `src/ptlog/exports/__init__.py` (depends on T039)
- [ ] T041 [US6] `interfaces/cli.py` (depends on T040): add `tracker export-roster`
- [ ] T042 [US6] `interfaces/app.py` (depends on T040): implement the Export section with the download button

**Checkpoint**: all six stories complete

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T043 [P] Add "Update 5 — Multi-Patient PT Tracker" to `docs/UPDATES.md` (roster columns and sort, programs and assignment with supersession, adherence weeks and percentage, queue kinds and threshold, discharge, roster export, tracker CLI group, Tracker page, migration 3)
- [ ] T044 [P] Update `README.md`: tracker commands in Quick Start, Project Structure (add `programs.py`, `adherence.py`, `tracker.py`, roster export), feature bullet
- [ ] T045 [P] Update `docs/PROJECT_OVERVIEW.md`: architecture tree and Key Files for the tracker modules
- [ ] T046 Run `specs/003-pt-tracker/quickstart.md` steps 1–8 against a scratch database (step 9 via `tests/test_app_pages.py`) and record outcomes under `## Notes` in `specs/003-pt-tracker/checklists/requirements.md`
- [ ] T047 Final gate: full suite green; `git diff --stat main -- analyze.py src/form_assessment.py src/utils.py config.yaml tests/test_analysis.py tests/test_form_assessment.py requirements.txt` empty; `grep -rnE '^(import|from) (socket|urllib|http|requests)' src/ptlog/` empty; the 50-patient performance test passing; then run `/speckit-analyze`

---

## Dependencies & Execution Order

- **Setup → Foundational → US1 → US2 → US3 → US4 → US5 → US6 → Polish**.
- Adherence computation (T006, T010) and assignment storage (T005, T009) sit in Foundational because the roster (US1) shows adherence and the queue (US4) uses both; US2, US3, and US5 add the interfaces and the user-facing behaviour on top.
- US4 depends on US1's `snapshot`; US5 depends on the roster and queue existing to prove exclusion; US6 depends on the roster.
- Interface tasks touching `cli.py` and `app.py` run sequentially within and across stories.

### Parallel Opportunities

- Phase 2: T003, T004, T005, T006 together; then T007; then T008, T010 together; then T009
- Each story: its test tasks together; then the module task; then CLI; then app
- Phase 9: T043, T044, T045 together

---

## Implementation Strategy

1. Setup + Foundational (10 tasks) → schema v3, catalog, assignments, adherence
2. US1 (8 tasks) → **MVP checkpoint**: the roster; commit
3. US2 → US3 → US4 → US5 → US6, suite green and a commit at each checkpoint
4. Polish → docs, quickstart run, final gate, `/speckit-analyze`

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- Week and threshold definitions are quoted from data-model.md and research.md; do not change them at implementation time
- Never edit the engine files or their tests (constitution I)
- Commit only when the suite is green and at story checkpoints
