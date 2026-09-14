# Tasks: Unified PT Session Log

**Input**: Design documents from `/specs/001-unified-session-log/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (recorder.md, cli.md, exports.md), quickstart.md

**Tests**: REQUIRED. Constitution principle IV (Test-First, non-negotiable): every story's tests are
written first, MUST fail before implementation, and the full suite (`.venv/bin/python -m pytest tests`)
MUST be green at every checkpoint. Tests use `tmp_path` databases and an injected clock; no camera,
network, or model weights. Engine tests (`tests/test_analysis.py`, `tests/test_form_assessment.py`)
are never edited by this feature.

**Organization**: Tasks are grouped by user story so each story is an independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US5 from spec.md
- Exact file paths are included in every task

## Path Conventions

Single project: new package `src/ptlog/`, tests in `tests/` (flat files, `tests/fixtures/` for data),
interfaces in `interfaces/`, engine runner `analyze.py` at the repo root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package skeleton, ignore rules, shared test fixtures

- [X] T001 Create package skeleton: `src/ptlog/__init__.py` (docstring + `__all__` placeholder), `src/ptlog/exports/__init__.py` (empty `FORMATS = {}`), and directories `tests/fixtures/golden/`, `tests/fixtures/legacy/sessions/`, `tests/fixtures/legacy/observation_logs/` each with a `.gitkeep`
- [X] T002 [P] Add `data/` and `exports/` to `.gitignore` under the "User data and outputs" block (constitution III: canonical store and export folder are never committed)
- [X] T003 [P] Create `tests/conftest.py` with fixtures: `tmp_db` (returns `tmp_path / "ptassist.db"`), `fake_clock` (callable stepping from `2026-03-23T09:15:00` by 1 s per call, with `.advance(seconds)`), and `cli_env` (copy of `os.environ` with `PTASSIST_DB` set to `tmp_db`) for subprocess CLI tests

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Models with units, schema v1, the store's open/migrate/read foundation, and the golden files that freeze the legacy formats before anything is touched

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Write `tests/test_ptlog_models.py` (must FAIL first): dataclasses `Patient`, `Session`, `ExerciseSet`, `RepEvent`, `PartialRepEvent`, `FormEvent`, `ControlEvent`, `FrameSample`, `SessionSummaryRow`, `LogRow`, `DeleteReport`, `LedgerRow` exist with the fields in data-model.md; `METRIC_DEFINITIONS` maps every numeric field (`min_angle`, `max_angle`, `rom`, `duration_seconds`, `form_score`, `avg_form_score`, `avg_rom`, `total_reps`, `angle`, `target_reps`) to `{"unit": ..., "definition": ...}` with non-empty text; `RepEvent.out_of_range` is 1 when "duration < 0, form_score ∉ [0,100], or rom ∉ [0,180]" and 0 otherwise; exception classes `PatientValidationError`, `DuplicatePatientError`, `BuiltinPatientError`, `PatientNotFoundError`, `SessionNotFoundError` exist
- [X] T005 [P] Write foundation section of `tests/test_ptlog_store.py` (must FAIL first): `SessionStore(tmp_db, clock).open()` creates all 10 tables from data-model.md; `schema_version` holds version 1; `PRAGMA journal_mode` is `wal`, `PRAGMA foreign_keys` is 1, `PRAGMA synchronous` is 2 (FULL); the built-in patient `unassigned` exists with `is_builtin=1` and is first in `list_patients()`; opening twice is idempotent; `get_patient("nope")` returns None; `default_db_path()` honours `PTASSIST_DB` and otherwise returns `<repo>/data/ptassist.db`
- [X] T006 Implement `src/ptlog/models.py` (depends on T004): the dataclasses above with docstrings stating unit and plain-language definition per field (constitution V, FR-012), the `METRIC_DEFINITIONS` dict, `Session.status` restricted to `running`, `completed`, `interrupted`; `ExerciseSet.side` restricted to `left`, `right`, `bilateral`; `PartialRepEvent.reason` restricted to `insufficient_rom`, `reversed_early`, `interrupted`; `FormEvent.severity` restricted to `suggestion`, `warning`, `stop`; `ControlEvent.kind` restricted to `switch`, `reset`; and the exception classes
- [X] T007 Implement store foundation in `src/ptlog/store.py` (depends on T005, T006): `default_db_path()`, `SessionStore.__init__(db_path, clock=datetime.now)`, `open()` (connect, `PRAGMA journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`, apply `MIGRATIONS = [(1, SCHEMA_V1_SQL)]` in order recording `schema_version`, insert `unassigned` if missing, then call `_recover_running_sessions()` stub), `close()`, context-manager support, `get_patient()`, `list_patients()`; `SCHEMA_V1_SQL` creates `patients` (id TEXT PRIMARY KEY COLLATE NOCASE), `sessions` (including `source_extras TEXT NULL` holding a JSON object), `exercise_sets`, `reps`, `partial_reps`, `form_events`, `control_events`, `frame_samples` (index on `(set_id, frame_num)`), `exports`, `import_ledger`, `schema_version`, every child FK `ON DELETE CASCADE`
- [X] T008 [P] Create `tests/fixtures/golden/sequence.py`: a fixed synthetic session as plain data (patient `P-001`, source `webcam`, camera `0`, imgsz 320, skip 1; set 1 `knee_extension` "Knee Extension" side left target 10 up 170 down 90; frame samples every 15 frames at angles 90→170→90; reps 1-3 with ROM 78.4/79.1/77.8, form 95/94/93, duration 3.1/3.0/3.2, min 10.2/9.8/11.0, max 88.6/88.9/88.8; one partial rep `reversed_early` ROM 40.2 min 95.0 max 135.2 duration 1.3; one form warning status `warning` message "Keep your back straight against the chair"; switch to `squat` "Squat" side bilateral target 10 up 170 down 90 (records an `interrupted` partial); reps 1-2; reset at count 2; rep 1; end) plus `FakeClock` producing deterministic timestamps starting `2026-03-23 09:15:00.000000`; export `SEQUENCE` and `expected_summary()`
- [X] T009 Create and run `tests/fixtures/golden/generate.py` (depends on T008): drives the four legacy writers — `analyze.SessionLogger`, `src.pta_raw_logger.PTARawLogger`, `src.observation_logger.ObservationLogger`, and `src.session_tracker.SessionTracker._save_csv` — with `SEQUENCE` and monkeypatched module clocks (`analyze.datetime`, `src.pta_raw_logger.datetime`, `src.observation_logger.datetime`, `src.session_tracker.datetime`) so timestamps are deterministic; writes `tests/fixtures/golden/pta_log.txt`, `observation.json`, `report.csv`, `session.log` (and `session-02.log` if the 50-line cap rolls); run once with `.venv/bin/python tests/fixtures/golden/generate.py`; header comment names the git commit at which the legacy writers exist; the script is not collected by pytest

**Checkpoint**: Models and schema exist, store opens, golden files are committed — user story work can begin

---

## Phase 3: User Story 1 - Record a Session into One Canonical Record (Priority: P1) 🎯 MVP

**Goal**: Every rep, partial rep, form message, switch, and reset from a webcam or video session lands in the canonical record through one writer, durable within one second, recoverable after a crash; legacy writers no longer run.

**Independent Test**: Run `python analyze.py video --input <sample> --exercise squat --patient unassigned`, then inspect the database: the reps shown on screen are all present in order with identical values, and `sessions/`, `observation_logs/`, `pta_logs/`, `logs/` gain no files. Kill a session mid-way and reopen: status `interrupted`, events intact.

### Tests for User Story 1 (write first, MUST FAIL)

- [X] T010 [P] [US1] Extend `tests/test_ptlog_store.py` with a session-write section: `start_session(patient_id, source, source_ref)` returns an id with `status='running'`, `schema_version=1`; `open_set()` stores `exercise_key`, `exercise_name`, `side`, `target_reps`, `up_angle`, `down_angle`, `ordinal`; each of `add_rep`, `add_partial_rep`, `add_form_event`, `add_control_event` is visible to a second connection immediately after return (commit per event, FR-010); `add_frame_samples()` writes a batch in one transaction; `end_session()` sets `status='completed'`, `end_time`, `duration_seconds`, and `total_reps`/`avg_form_score`/`avg_rom` equal to values recomputed from stored reps (FR-009); a rep with `form_score=101` is stored with `out_of_range=1` and excluded from averages; zero reps → averages NULL; `start_session()` while another session is `running` marks the old one `interrupted`; a set closed with zero reps is still present; two sessions started in the same clock second get distinct ids
- [X] T011 [P] [US1] Write `tests/test_ptlog_recorder.py`: build `FakeTracker` (attributes `session: ExerciseSession`, `current_state`, `rep_count`), a fake `ExerciseConfig`, and fake `OverallFormAssessment`/`FormFeedback` objects (import the real dataclasses from `analyze` and `src.form_assessment`, no model needed); assert `observe()` stores a `RepMetrics` appended since the last call as one `reps` row with the observing `frame_num`; a new `PartialRepMetrics` → one `partial_reps` row; a frame sample is buffered only on every 15th frame with `angle is not None` and flushed on the next event or after 1 s; form events stored only for status `warning`/`poor`/`stop`, at most once per 60 frames, and never with an identical message within 2 s for the same set; severity mapping `INFO/SUGGESTION→suggestion`, `WARNING or poor→warning`, `CRITICAL or stop→stop`; `switch()` closes the set, writes a `switch` control event, opens a new set; `reset()` writes a `reset` control event with `tracker.rep_count`; `end()` returns a `Session` whose summary equals `ExerciseSession.total_reps/avg_form_score/avg_rom` to one decimal; with a store stub whose `add_rep` raises `OSError`, `observe()` does not raise, `recorder.degraded` is True, and `end()` re-raises the first error; a long run of `observe()` calls with `angle=None` stores no rep, partial, form, or sample rows and `end()` still returns a valid summary (edge case: no keypoints); the degraded-mode log line contains the session id only and never the patient's label or notes (FR-028); a static test reads `analyze.py` source and asserts none of `ObservationLogger(`, `PTARawLogger(`, `SessionLogger(`, `generate_session_report(` appear as calls or instantiations (SC-006 guard)
- [X] T012 [P] [US1] Write `tests/test_ptlog_recovery.py`: (a) in-process — start a session, add three reps, do not end, open a second `SessionStore` on the same path → session `status='interrupted'`, `end_time` equals the last rep timestamp, `interrupted_reason='recovered_on_open'`, summary computed from the three reps; (b) subprocess — spawn `.venv/bin/python -c "<script>"` that opens the store on `tmp_db`, starts a session, and adds one rep every 50 ms forever; after 0.6 s send `SIGKILL`; reopen and assert at least 5 reps exist and the session is `interrupted` (SC-002)

### Implementation for User Story 1

- [X] T013 [US1] Implement write methods in `src/ptlog/store.py` (depends on T010): `start_session()` (marks any `running` session interrupted first), `open_set()`, `close_set()`, `add_rep()` (computes `out_of_range`), `add_partial_rep()`, `add_form_event()`, `add_control_event()`, `add_frame_samples()`, `end_session()`, `_compute_summary(session_id)` (mean of non-flagged reps, NULL when none), `_recover_running_sessions()` (sets `interrupted`, `end_time` = last event timestamp or `start_time`, stores summary), and `record_export(session_id, fmt, path)` (needed by the US2 cascade test before US4 exists)
- [X] T014 [US1] Implement `src/ptlog/recorder.py` `SessionRecorder` per `contracts/recorder.md` (depends on T011, T013): `start()`, `observe()`, `switch()`, `reset()`, `end()`, `session_id`, `degraded`; delta detection on `len(tracker.session.rep_metrics)` and `len(tracker.session.partial_rep_metrics)`; `sample_every=15`, `form_throttle_frames=60`, `form_throttle_seconds=2.0`; sample buffer flushed on any event or when ≥1 s since last flush; store errors logged once via `logging.getLogger("ptlog")` then swallowed until `end()`
- [X] T015 [US1] Replace the legacy logger call sites in the video loop of `analyze.py` `main()` (≈lines 918-1055): delete the `ObservationLogger(...)`/`PTARawLogger(...)` construction and every `obs_logger.` / `pta_logger.` call; add a `patient_id: Optional[str] = None` parameter (None → `"unassigned"`); before opening the video, open `SessionStore(default_db_path())` and raise `PatientNotFoundError` if `get_patient(patient_id)` is None; create `SessionRecorder(store)` and call `recorder.start(patient_id, "video", Path(input_path).name, exercise_config)`; call `recorder.observe(tracker, metrics, angle, frame_num, last_assessment)` right after `metrics = tracker.update(angle)`; call `recorder.end(session)` in the finalization block; leave every other line of the loop unchanged (constitution I)
- [X] T016 [US1] Replace the legacy logger call sites in `analyze_webcam()` of `analyze.py` (≈lines 1238-1495): delete `SessionLogger`, `ObservationLogger`, `PTARawLogger` construction and all `logger.log(...)`, `obs_logger.`, `pta_logger.` calls including those in the `'r'` reset branch (→ `recorder.reset(tracker)`), the `'n'` switch branch (→ `recorder.switch(exercise_config, tracker)` after the new config is loaded), the throttled form-warning block (now inside `observe()`), and the finalization block (→ `recorder.end(session)`); pass `source_ref` as `str(camera_id)` and `extras={"camera_id": camera_id, "imgsz": imgsz, "frame_skip": frame_skip}` to `recorder.start()` so it lands in `sessions.source_extras` and the text-log export can reproduce the `SESSION START` line; accept `patient_id` as in T015; leave every other line unchanged
- [X] T017 [US1] Add `--patient` to the `webcam` and `video` subparsers in the argparse block of `analyze.py` and pass it into `analyze_webcam()`/`main()`; on `PatientNotFoundError` print `Patient '<ID>' not found. Register it with: patients add <ID>` and exit 1; after a session print `Session <id> saved for patient <ID> (<n> reps)` (contracts/cli.md)
- [X] T018 [US1] Pass `--patient` through `interfaces/cli.py`: add the argument to the `webcam` and `analyze` subparsers, forward it in `cmd_webcam()` and `cmd_analyze()`; remove the `--report` argument and the `generate_session_report(...)` call from `cmd_analyze()`
- [X] T019 [US1] Remove the fifth legacy writer that no design doc named: in `analyze.py` delete the `--report` argument from the `video` subparser (≈L1717) and both `generate_session_report(...)` calls in the `__main__` dispatch (≈L1760–1761 after video, ≈L1773 after webcam); in `interfaces/cli.py` delete the unconditional `generate_session_report(session)` call in `cmd_webcam()` (≈L255) and the name from its import (≈L236); in `interfaces/app.py` drop `generate_session_report` from the import at L46; leave the function body in place until T045 deletes it (FR-024, SC-006, constitution II)
- [X] T020 [US1] Run `.venv/bin/python -m pytest tests -q`: T010–T012 pass, engine suites unchanged and green; run `git diff --stat analyze.py` and confirm changes are confined to the two loops' logger sites, the two function signatures, and the argparse block

**Checkpoint**: MVP — sessions are recorded once, durably, and recoverably; legacy folders stay empty

---

## Phase 4: User Story 2 - Register and Manage Pseudonymous Patients (Priority: P2)

**Goal**: Register, edit, reassign, and delete patients by pseudonymous ID with PHI guards and cascading delete.

**Independent Test**: `patients add P-017 --label "Post-op knee"`, `patients add "John Smith"` (rejected), record a session, `patients reassign <id> --to P-017`, `patients delete P-017 --yes` → nothing of P-017 remains.

### Tests for User Story 2 (write first, MUST FAIL)

- [X] T021 [P] [US2] Write `tests/test_ptlog_privacy.py`: `validate_patient_id()` accepts `P-017`, `abc123`, a 32-char ID; rejects empty, 33 chars, `P 017`, `P_017` (pattern is "`^[A-Za-z0-9-]{1,32}$`"), `John Smith` ("two or more consecutive capitalized words"), `01/02/1990` and `1990-01-02` ("a date in any common numeric layout"), `123456` ("a run of six or more digits"); `validate_label()` accepts 60 chars, rejects 61 and the same PHI patterns; every rejection raises `PatientValidationError` whose message names the violated rule
- [X] T022 [P] [US2] Extend `tests/test_ptlog_store.py` with a patients section: `add_patient()` stores `label`, `notes`, `created_at`; `add_patient("p-017")` after `P-017` raises `DuplicatePatientError` (COLLATE NOCASE); `update_patient()` changes label/notes only; `list_patients()` returns `unassigned` first then the rest alphabetically with session counts; `delete_patient()` on a patient with sessions, sets, reps, partials, form events, control events, frame samples, and two export files recorded via `record_export()` (T013) removes every row (cascade) and unlinks both files, returning `DeleteReport(sessions=…, events=…, export_files=…)`; `delete_patient("unassigned")` raises `BuiltinPatientError`; deleting an unknown ID raises `PatientNotFoundError`; `reassign_session()` moves a session and updates counts; reassigning to an unknown patient raises `PatientNotFoundError`
- [X] T023 [P] [US2] Write the patients section of `tests/test_cli_ptlog.py`: run `.venv/bin/python interfaces/cli.py patients add|list|edit|delete --yes|reassign` via `subprocess.run` with `cli_env`; assert exit codes (0 success, 1 validation/not found) and the messages in `contracts/cli.md` (`Registered patient P-017`, `The built-in 'unassigned' patient cannot be deleted`); `delete` without `--yes` reads `n` from stdin and deletes nothing; `--json` output parses; an error path for a patient registered with a label (e.g. `reassign 999 --to P-017`) prints the ID and never the label (FR-028, SC-008)

### Implementation for User Story 2

- [X] T024 [US2] Implement `src/ptlog/privacy.py` (depends on T021): `ID_RE = re.compile(r"^[A-Za-z0-9-]{1,32}$")`, `NAME_RE = r"[A-Z][a-z]+(?: [A-Z][a-z]+)+"`, `DATE_RE = r"\d{1,4}[/-]\d{1,2}[/-]\d{1,4}"`, `DIGITS_RE = r"\d{6,}"`, `LABEL_MAX = 60`; `validate_patient_id()`, `validate_label()` raising `PatientValidationError` with the rule name
- [X] T025 [US2] Implement patient methods in `src/ptlog/store.py` (depends on T022, T024): `add_patient()` (validate, NOCASE uniqueness → `DuplicatePatientError`), `update_patient()`, `delete_patient()` (refuse builtin; collect `exports.path` rows; `DELETE FROM patients`; cascade; unlink files; return `DeleteReport`), `reassign_session()`; `list_patients()` gains session counts and last-session date
- [X] T026 [US2] Add the `patients` subcommand group to `interfaces/cli.py` per `contracts/cli.md` (`add`, `list [--json]`, `edit`, `delete [--yes]` with `Delete patient <ID> and N sessions? [y/N]` prompt, `reassign <SESSION_ID> --to <ID>`); the commands only call `SessionStore` methods and print; exit codes 0/1/2

**Checkpoint**: Patients are first-class; sessions can be attributed, moved, and fully erased

---

## Phase 5: User Story 3 - Browse History and Read a Session Log (Priority: P3)

**Goal**: Newest-first history per patient and a full, unit-labelled event log for any session, in the CLI and the web app, all read from the store.

**Independent Test**: Record three sessions for one patient, `sessions list --patient P-017` shows them newest first, `sessions show <middle id>` prints every event in order with units; the web app's Sessions, Observation Logs, and Session Logs pages show the same data without touching legacy folders.

### Tests for User Story 3 (write first, MUST FAIL)

- [X] T027 [P] [US3] Extend `tests/test_ptlog_store.py` with a reads section: `list_sessions()` newest first returning `SessionSummaryRow(id, patient_id, start_time, source, status, exercises, total_reps, avg_form_score)`, `list_sessions(patient_id=…)` filters; `load_session()` returns the full graph (sets → reps/partials/form events, control events, samples); `event_log()` returns rows ordered by `(timestamp, frame_num)` tagged `type` in `session_start, rep, partial_rep, form, switch, reset, session_end` with the set ordinal; an interrupted session's log has no `session_end` row and `status='interrupted'`; unknown id raises `SessionNotFoundError`; performance: `event_log()` on a 500-event session completes in under 2 s and `list_sessions()` over 200 sessions in under 2 s (SC-004)
- [X] T028 [P] [US3] Write `tests/test_ptlog_views.py`: `event_log_lines(store, session_id)` renders `REP 1 | ROM 78.4° | form 95/100 | 3.1 s | 10.2°–88.6°`, partial/form/switch/reset lines, and `STATUS: interrupted` when applicable; `session_header_lines()` shows `not available` for NULL averages; every metric label used by the views exists in `METRIC_DEFINITIONS` (FR-012); `load_session_data_for_trends(store, patient_id)` returns `SessionData`/`ExerciseRecord` objects (from `src.session_tracker`) such that `SessionTracker.calculate_progress()` works unchanged on them
- [X] T029 [P] [US3] Extend `tests/test_cli_ptlog.py`: `sessions list [--patient] [--json]` newest first with the columns in `contracts/cli.md`; `sessions show <id> [--json]` prints header, event lines, summary, status; unknown id → exit 1

### Implementation for User Story 3

- [X] T030 [US3] Implement read methods in `src/ptlog/store.py` (depends on T027): `list_sessions()`, `load_session()`, `event_log()` (SQL `UNION ALL` over the four event tables plus synthetic start/end rows, `ORDER BY timestamp, frame_num`)
- [X] T031 [US3] Implement `src/ptlog/views.py` (depends on T028, T030): `session_table_rows()`, `session_header_lines()`, `event_log_lines()`, `metric_label(field)` using `METRIC_DEFINITIONS`, `load_session_data_for_trends()` building `SessionData`/`ExerciseRecord` from store rows (research D13)
- [X] T032 [US3] `interfaces/cli.py`: add `sessions list` and `sessions show` per `contracts/cli.md`; remove the `report` and `history` subcommands and their `SessionTracker` writer usage; re-point `cmd_progress()` to `views.load_session_data_for_trends()` and keep its output unchanged
- [X] T033 [US3] `interfaces/app.py` `render_sidebar()`: replace the hardcoded `st.selectbox("Patient ID", ["Default", "Patient 001", "Patient 002"])` with a selector over `store.list_patients()` stored in `st.session_state.patient_id`; pass it as `patient_id` to `analyze_video()` on the Video Analysis page
- [X] T034 [US3] `interfaces/app.py`: add `page_patients()` (list, add with label/notes, edit, delete with confirmation checkbox, all via `SessionStore`, validation errors shown as `st.error`) and `page_sessions()` (history newest first for the selected patient via `views.session_table_rows()`, session detail via `views.event_log_lines()`, status badge); register `'patients'` and `'sessions'` in the `pages` dict and the page dispatcher; no logic beyond calling `src/ptlog` functions
- [X] T035 [US3] `interfaces/app.py`: switch `page_observation_logs()` and `page_session_logs()` from `list_observation_logs()`/`load_observation_log()` and `sessions/*.json` + `logs/logfile-*.log` to `store.list_sessions()`/`store.event_log()` (charts read rep rows from the store); remove the raw logfile viewer; switch `page_progress_report()` to `views.load_session_data_for_trends()`; leave `page_pt_summary()` for T044

**Checkpoint**: Everything recorded is readable, newest first, with units, from CLI and web

---

## Phase 6: User Story 4 - Export a Session in Legacy Formats (Priority: P4)

**Goal**: The four legacy formats are generated from the record with byte-level parity, and the legacy writers are deleted.

**Independent Test**: Replay the golden sequence through the store and compare each export to its golden file; export the same session twice and diff; `export <id> --format all` writes four correctly named files under `exports/`.

### Tests for User Story 4 (write first, MUST FAIL)

- [X] T036 [P] [US4] Write `tests/test_ptlog_exports.py`: replay `tests/fixtures/golden/sequence.py` through `SessionStore` + `SessionRecorder` with the same `FakeClock`; assert `to_pta_log_text(session, samples, ordinal=1) == golden pta_log.txt` exactly; `to_observation_json(session) == observation.json`; `to_csv_report(session) == report.csv` (including `\r\n`); `to_text_log(session) == [session.log(, session-02.log)]`; exporting twice yields identical strings; interrupted-session variants add the `ERROR | "Session interrupted"` line, `"Session interrupted"` in `warnings`, and the `Flags for Review` block; `session_summary.generate_session_summary(to_observation_dict(session))` returns a summary without error; `write_export(store, id, fmt, out_dir)` names files `{patient_id}_{YYYYMMDD_HHMMSS}.{txt|json|csv|log}` and inserts an `exports` row
- [X] T037 [P] [US4] Extend `tests/test_cli_ptlog.py`: `export <id> --format all` prints four paths under `--out`; `--format csv_report` prints one; unknown id → exit 1

### Implementation for User Story 4

- [X] T038 [P] [US4] Implement `src/ptlog/exports/pta_log.py` `to_pta_log_text()` per `contracts/exports.md` §1 (header block, `" |".join` line format, `Observing` lines from frame samples, event lines in stored order, `Session Summary`, `System halted.`, `ERROR` line for interrupted)
- [X] T039 [P] [US4] Implement `src/ptlog/exports/observation_json.py` `to_observation_dict()` and `to_observation_json()` per §2 (key order, event field order, rounding rules, `session_id` = `session_YYYY-MM-DD_HHMMSS`, `summary.exercises_performed` first-seen order)
- [X] T040 [P] [US4] Implement `src/ptlog/exports/csv_report.py` `to_csv_report()` per §3 (`csv.writer` defaults, header rows, one row per set, optional `Flags for Review` and `Therapist Notes` blocks)
- [X] T041 [P] [US4] Implement `src/ptlog/exports/text_log.py` `to_text_log()` per §4 (`# logfile created:` header, `[HH:MM:SS]` lines, 50-line cap with `# continued:` header, `SESSION START` variant from `source_ref` extras)
- [X] T042 [US4] Implement `FORMATS` registry and `write_export()` in `src/ptlog/exports/__init__.py` (depends on T038–T041), calling `store.record_export()` from T013; default out dir `exports/`
- [X] T043 [US4] Add the `export` subcommand to `interfaces/cli.py` per `contracts/cli.md`
- [X] T044 [US4] `interfaces/app.py`: add four `st.download_button` exports to the session detail on `page_sessions()`; switch `page_pt_summary()` to `store.load_session()` → `to_observation_dict()` → `generate_session_summary()`; remove the last `list_observation_logs`/`load_observation_log` imports
- [X] T045 [US4] Retire the legacy writers once T036 passes: delete `src/observation_logger.py`, `src/pta_raw_logger.py`, and both the `SessionLogger` class and the `generate_session_report()` function from `analyze.py`; remove the writer methods from `src/session_tracker.py` (`start_session`, `add_exercise_record`, `end_session`, `save_session`, `_save_json`, `_save_csv`, `export_patient_history`, `_export_history_csv`, `_export_history_json`, `create_exercise_record_from_tracker`, `quick_session_report`) keeping `calculate_progress`, `_calculate_trend`, `compare_sessions`, `get_exercises_needing_attention`, `plot_progress`, `generate_session_summary_card`; delete `tests/test_logging.py`; remove writer tests from `tests/test_session_tracker.py` keeping trend/compare tests; update `src/__init__.py` exports; add a header note to `tests/fixtures/golden/generate.py` that it requires the legacy modules at the named commit; run the full suite green

**Checkpoint**: One writer remains; every legacy format is an export proven against goldens

---

## Phase 7: User Story 5 - Import Legacy Session Files Once (Priority: P5)

**Goal**: Existing files in `sessions/` and `observation_logs/` become canonical sessions under `unassigned`, idempotently.

**Independent Test**: `import-legacy --dry-run`, then `import-legacy` twice: first run imports one session per legacy session, second run reports all as duplicates and creates nothing.

### Tests for User Story 5 (write first, MUST FAIL)

- [X] T046 [P] [US5] Create synthetic fixtures (no PHI) under `tests/fixtures/legacy/`: `sessions/pt_session_knee_extension_20260127_134857.json` (`generate_session_report` shape: `session_summary` + `rep_details`), `sessions/pt_session_knee_extension_20260127_134857.csv` (must be skipped as derived), `sessions/tracker_shape.json` (`session_id`, `patient_id`, `exercises` shape), `observation_logs/session_2026-03-23_234321.json` (event stream with reps, a partial rep, an exercise change, a reset, `session_end`), `observation_logs/malformed.json` (truncated), and a cross-folder duplicate pair: `sessions/pt_session_squat_20260127_150551.json` and `observation_logs/session_2026-01-27_150551.json` describing the same squat session (same exercise, start second, total reps)
- [X] T047 [P] [US5] Write `tests/test_ptlog_importer.py`: `import_legacy(store, sessions_dir, obs_dir)` creates one session per legacy session under `unassigned` with source, start/end time, set, per-rep metrics, and summary equal to the file; `.csv` skipped; `malformed.json` reported by name with a reason while the others import; second run → every file `duplicate (already imported)` via `import_ledger` SHA-256 and no new sessions (SC-007); the cross-folder pair yields exactly one session and one `duplicate (same session found in both folders)` line; `dry_run=True` writes nothing; ledger rows carry `outcome` in `imported`, `duplicate`, `malformed`
- [X] T048 [P] [US5] Extend `tests/test_cli_ptlog.py`: `import-legacy [--sessions-dir] [--obs-dir] [--dry-run]` prints one line per file and a totals line per `contracts/cli.md`

### Implementation for User Story 5

- [X] T049 [US5] Implement `src/ptlog/importer.py` (depends on T047): parsers `parse_session_report()`, `parse_observation_log()`, `parse_tracker_json()`, `detect_shape()`, `file_sha256()`, dedup key `(exercise_name, start_time to the second, total_reps)`, `ImportReport` with per-file outcomes, `import_legacy(store, sessions_dir, obs_dir, dry_run=False)`; imported sessions get `source` from the file (`video`/`webcam`, default `video`) and `source_ref='legacy-import'`
- [X] T050 [US5] Add `ledger_lookup()`/`ledger_add()` to `src/ptlog/store.py` and the `import-legacy` subcommand to `interfaces/cli.py`

**Checkpoint**: Prior history lives in the record; repeated imports are harmless

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, quickstart validation, constitution re-check

- [X] T051 [P] Add "Update 3 — Unified PT Session Log" to `docs/UPDATES.md`: canonical record and its location, retired writers, `--patient`, `patients`/`sessions`/`export`/`import-legacy` commands, export formats, import, crash recovery, privacy rules
- [X] T052 [P] Update `README.md`: `--patient` on webcam/video, the new subcommands, `data/ptassist.db` and `PTASSIST_DB`, `exports/` default, updated Project Structure block (add `src/ptlog/`, remove deleted modules)
- [X] T053 [P] Update `docs/PROJECT_OVERVIEW.md` architecture tree and Key Files for `src/ptlog/` and the removed logger modules
- [X] T054 Execute every step of `specs/001-unified-session-log/quickstart.md` against a sample video (steps 1–4, 6–9; step 5 with the subprocess test as the stand-in if no webcam) and record outcomes under `## Notes` in `specs/001-unified-session-log/checklists/requirements.md`; confirm SC-006 by listing the four legacy folders before and after a session
- [X] T055 Final gate: `.venv/bin/python -m pytest tests -q` green; `git diff --stat` shows no edits to `src/form_assessment.py`, `src/utils.py`, `config.yaml`, `tests/test_analysis.py`, `tests/test_form_assessment.py`; `requirements.txt` unchanged; `grep -rn` of fixtures finds no name/date/MRN-like strings; `grep -rnE '^(import|from) (socket|urllib|http|requests)' src/ptlog/` returns nothing (FR-027); then run `/speckit-analyze`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; BLOCKS all user stories. T009 (golden generation) must run before any legacy writer is modified.
- **US1 (Phase 3)**: depends on Foundational. MVP.
- **US2 (Phase 4)**: depends on Foundational; independent of US1 (patients exist without sessions), though its cascade-delete test uses US1 write methods (T013), so run after T013 in practice.
- **US3 (Phase 5)**: depends on US1 (needs recorded sessions to read) and, for the web sidebar, US2's patient list.
- **US4 (Phase 6)**: depends on US1 (data to export) and US3 (session page hosts the download buttons); T045 deletion depends on T036 passing.
- **US5 (Phase 7)**: depends on US1 write methods only; can run in parallel with US3/US4.
- **Polish (Phase 8)**: depends on all stories.

### Within Each User Story

- Tests first, confirmed FAILING, then models → store → recorder/views → CLI → web app
- Story complete and suite green before moving to the next priority

### Parallel Opportunities

- Phase 1: T002, T003 in parallel with T001
- Phase 2: T004, T005, T008 in parallel; T006 after T004; T007 after T005+T006; T009 after T008
- US1: T010, T011, T012 in parallel; T015 and T016 touch different functions of `analyze.py` but the same file — do sequentially
- US2: T021, T022, T023 in parallel; T024 then T025 then T026
- US3: T027, T028, T029 in parallel; T033, T034, T035 all edit `interfaces/app.py` — sequential
- US4: T036, T037 in parallel; T038–T041 in parallel (four files); then T042 → T043 → T044 → T045
- US5: T046, T047, T048 in parallel; T049 → T050
- Polish: T051, T052, T053 in parallel

---

## Parallel Example: User Story 1

```bash
# Write the three failing test files together:
Task: "Extend tests/test_ptlog_store.py with the session-write section"
Task: "Write tests/test_ptlog_recorder.py with FakeTracker-driven cases"
Task: "Write tests/test_ptlog_recovery.py with in-process and SIGKILL cases"

# Then implement in order (same files depend on each other):
Task: "Implement write methods in src/ptlog/store.py"
Task: "Implement SessionRecorder in src/ptlog/recorder.py"
Task: "Replace call sites in analyze.py video loop, then webcam loop"
```

## Parallel Example: User Story 4

```bash
# Four export modules are independent files:
Task: "Implement src/ptlog/exports/pta_log.py"
Task: "Implement src/ptlog/exports/observation_json.py"
Task: "Implement src/ptlog/exports/csv_report.py"
Task: "Implement src/ptlog/exports/text_log.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational, including golden files)
2. Complete Phase 3 (US1): tests fail → store writes → recorder → `analyze.py` call sites → `--patient`
3. **STOP and VALIDATE**: quickstart steps 1, 3, 4, 5; legacy folders gain no files
4. Demo: a recorded, crash-safe session readable from the database

### Incremental Delivery

1. Setup + Foundational → schema and goldens exist
2. US1 → MVP: one writer, durable, recoverable
3. US2 → patients, reassignment, cascading delete
4. US3 → history and event log in CLI and web
5. US4 → exports proven against goldens; legacy writers deleted
6. US5 → legacy history imported
7. Polish → docs, quickstart run, final constitution gate

### Parallel Team Strategy

After Foundational: one person on US1 (the critical path); a second can start US2's privacy module and tests and US5's fixtures and parsers, which do not touch `analyze.py`; US3/US4 web-app tasks queue behind US1 because they edit the same `interfaces/app.py`.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- Every store/recorder task quotes its constraints from `data-model.md`; do not loosen them at implementation time
- Verify each story's tests fail before implementing (constitution IV)
- Commit only when the suite is green and only when asked (constitution workflow section)
- Never edit `ExerciseTracker`, `FormAnalyzer`, `src/utils.py`, or `config.yaml` (constitution I)
