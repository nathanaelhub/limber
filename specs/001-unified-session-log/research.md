# Research: Unified PT Session Log

**Feature**: 001-unified-session-log | **Date**: 2026-09-14

All unknowns from the Technical Context are resolved below. No NEEDS CLARIFICATION remains.

## D1. Storage engine and durability

- **Decision**: one SQLite file `data/ptassist.db` via stdlib `sqlite3`; `journal_mode=WAL`,
  `synchronous=FULL`; one `BEGIN`/`COMMIT` per event (rep, partial rep, form event, control
  event, session start/end). Frame samples are buffered and flushed in one transaction at most
  once per second or on any event.
- **Rationale**: FR-010 requires durability within one second including power loss. With
  `synchronous=FULL` every commit is fsynced; event rate is low (a rep every 1-4 s, form
  events throttled to one per 2 s), so per-event fsync costs well under 2 ms per frame on
  average. WAL keeps readers (the Streamlit app) from blocking the writer.
- **Alternatives considered**: JSON append-only file per session (what `ObservationLogger`
  does; rewrites the whole file per event and cannot be queried across sessions); `synchronous=
  NORMAL` (loses the last commits on power loss, violates FR-010 wording); a server database
  (violates local-first and constitution V).

## D2. Reproducing the PTA-Log per-frame "Observing" lines

- **Decision**: add a `frame_samples` table (session, set, frame number, timestamp, angle,
  state, rep count) written at the same cadence the legacy logger used: every 15th inference
  frame when an angle is present. The PTA-Log export emits one "Observing" line per sample.
- **Rationale**: FR-022 requires the export to match the legacy structure, and the legacy
  file interleaves per-frame lines with event lines. Storing the samples is cheap (about 2
  rows per second, under 1 MB per hour) and gives the review-over-time feature a raw angle
  trace for free.
- **Alternatives considered**: omit observation lines from the export (breaks structural
  parity); store every inference frame (15x the rows for no export benefit; can be raised
  later by a spec).

## D3. Schema versioning

- **Decision**: `schema_version(version INTEGER, applied_at TEXT)`; `store.py` holds an
  ordered list of `(version, sql)` migrations applied in one transaction each on open.
  Version 1 is the initial schema. Sessions carry the schema version they were written under.
- **Rationale**: constitution II requires a schema version and a tested migration path;
  a list of SQL strings is the simplest thing that satisfies it.
- **Alternatives considered**: Alembic or another migration framework (new dependency,
  violates constitution V); no versioning (violates constitution II).

## D4. Recorder interface shape

- **Decision**: `SessionRecorder` exposes `start(patient_id, source, source_ref,
  exercise_config)`, `observe(tracker, metrics, angle, frame_num, assessment)`,
  `switch(new_exercise_config)`, `reset()`, `end()`. `observe()` is called once per inference
  frame and internally detects new reps and partial reps by comparing the lengths of
  `tracker.session.rep_metrics` and `tracker.session.partial_rep_metrics` with what it last
  saw, applies the 2 s form-message throttle, and samples every 15th frame. The two call
  sites in `analyze.py` shrink from ~80 lines each to five calls.
- **Rationale**: the engine already exposes everything needed on its public outputs; delta
  detection currently lives at both call sites and is duplicated. Moving it into the recorder
  removes duplication without touching the tracker.
- **Alternatives considered**: callbacks or an observer hook inside `ExerciseTracker`
  (modifies the engine, violates constitution I); keeping delta detection at the call sites
  (duplicated logic, harder to test).

## D5. Timestamps and clocks

- **Decision**: store timestamps as ISO 8601 local time with microseconds (matching the
  legacy files) in TEXT columns, plus the inference frame number. `SessionStore` and
  `SessionRecorder` accept an optional `clock: Callable[[], datetime]` defaulting to
  `datetime.now`. Tests inject a stepping fake clock.
- **Rationale**: exports must reproduce legacy timestamp formats byte for byte, and tests
  must be deterministic.
- **Alternatives considered**: UTC epoch integers (cleaner, but every export would need a
  conversion and the legacy formats are local time); patching `datetime` globally in tests
  (fragile).

## D6. Golden files for export parity

- **Decision**: a one-off script (`tests/fixtures/golden/generate.py`, run once and kept for
  regeneration) drives the four legacy writers with a fixed synthetic event sequence and a
  patched module clock, and writes the reference files. `test_ptlog_exports.py` feeds the same
  sequence through the store and compares each export to its golden file exactly. Only after
  the parity tests pass are the legacy writer classes and `tests/test_logging.py` deleted.
- **Rationale**: FR-022 and SC-005 demand structural and value identity; a golden file is
  the only contract that can prove it, and it survives the deletion of the legacy code.
- **Alternatives considered**: keeping the legacy loggers permanently as test doubles
  (keeps four writers alive, against constitution II); hand-written expected strings (drift).

## D7. Patient ID and PHI heuristics

- **Decision**: ID must match `^[A-Za-z0-9-]{1,32}$` and be unique case-insensitively; label
  up to 60 characters. ID and label are rejected when they contain two or more consecutive
  capitalized words (`[A-Z][a-z]+(?: [A-Z][a-z]+)+`), a numeric date (`\d{1,4}[/-]\d{1,2}[/-]
  \d{1,4}`), or six or more consecutive digits. Notes are free text and are not scanned, but
  the UI shows a reminder not to enter identifying details.
- **Rationale**: FR-013 and FR-014 name these patterns; regexes are testable and need no
  dependency.
- **Alternatives considered**: a named-entity recognizer (heavy dependency, false positives);
  scanning notes too (the spec only constrains ID and label, and notes need clinical freedom).

## D8. Interrupted-session recovery

- **Decision**: on every `SessionStore.open()`, any session with `status='running'` is set to
  `interrupted`, its `end_time` is set to its last event timestamp, and its summary is computed
  from stored events. The recorder writes `status='running'` at start and `completed` at end.
- **Rationale**: FR-011; single-session-per-machine assumption makes "running on open" an
  unambiguous crash signal.
- **Alternatives considered**: heartbeat column with a timeout (more state, no benefit under
  the single-session assumption).

## D9. Web app integration

- **Decision**: add a Patients page and a Sessions page. The existing Observation Logs,
  Session Logs, and PT Summary pages switch their data source to `SessionStore`; PT Summary
  keeps calling `session_summary.generate_session_summary()` by passing it the dict returned
  by the observation-JSON export, which has the exact legacy shape. Export buttons use
  `st.download_button` with bytes from the export functions. The hardcoded "Patient ID"
  selectbox in the sidebar becomes a real selector over stored patients.
- **Rationale**: FR-020 with the smallest change; `session_summary.py` is unchanged.
- **Alternatives considered**: rewriting the pages (out of scope); leaving them on legacy
  files (violates FR-020 and SC-006).

## D10. Legacy import

- **Decision**: `importer.import_legacy(store, sessions_dir, observation_logs_dir)` parses
  three known JSON shapes: `generate_session_report` output (`session_summary` +
  `rep_details`), `ObservationLogger` output (`events` list), and `SessionTracker` output
  (`session_id` + `exercises`). CSV and text log files are skipped as derived formats. An
  `import_ledger` table stores each file's SHA-256 and the session it produced; a second run
  skips known hashes. Cross-folder duplicates are detected by matching exercise name, start
  time to the second, and total reps. Malformed files are reported by name and skipped.
- **Rationale**: FR-025, FR-026, US5 scenario 4.
- **Alternatives considered**: moving files after import (spec assumption says copy only).

## D11. Export naming and location

- **Decision**: exports default to `exports/` (gitignored) and are named
  `{patient_id}_{YYYYMMDD_HHMMSS}.{txt|json|csv|log}`; the PTA-Log header's second line still
  carries a `PTA-Log-NNNN.txt` style name derived from the session's per-patient ordinal so the
  header block matches the legacy layout. Exports are recorded in an `exports` table so
  patient deletion can remove the files.
- **Rationale**: FR-023, FR-017.

## D12. CLI placement

- **Decision**: `--patient` is added to `analyze.py`'s `webcam` and `video` subcommands
  (the runner the README documents) and passed through from `interfaces/cli.py`. New
  subcommands `patients`, `sessions`, `export`, and `import-legacy` live in
  `interfaces/cli.py` and call `src/ptlog` functions only.
- **Rationale**: keeps interface files logic-free (constitution V) and one obvious place for
  each command.

## D13. Fate of `SessionTracker` and the `report` / `progress` / `history` commands

- **Decision**: `SessionTracker`'s writer methods (`start_session`, `add_exercise_record`,
  `end_session`, `save_session`, `_save_json`, `_save_csv`, `export_patient_history`) are
  deleted; its read-side trend math (`calculate_progress`, `_calculate_trend`,
  `compare_sessions`, `get_exercises_needing_attention`) is kept and fed by a small
  store-backed loader so `cli.py progress` and the web Progress Report page keep working
  from the canonical record. `cli.py report` and `history` are replaced by `sessions list`
  and `sessions show`. `tests/test_session_tracker.py` loses its writer tests and keeps its
  trend tests.
- **Rationale**: constitution II retires writers, not analysis; the trend math is the seed of
  feature 002 (review over time), which will replace it under its own spec.
- **Alternatives considered**: deleting the whole module now (breaks the progress page with
  nothing to replace it until feature 002); keeping the writer (a parallel source of truth).

## D14. `generate_session_report()` is a fifth legacy writer

- **Decision**: `analyze.generate_session_report()` (writes `pt_session_*.json` with
  `session_summary`/`rep_details` and a per-rep CSV into `sessions/`) is retired with the
  other writers. Its two shapes are not reproduced as exports: the CSV export contract is the
  `SessionTracker` report (one row per exercise set), and the observation JSON export covers
  per-rep detail. The importer parses the `session_summary`/`rep_details` JSON so existing
  files are preserved. Its call sites (analyze.py `__main__`, `cli.py cmd_webcam`) and the
  `--report` flag are removed in US1; the function is deleted in US4.
- **Rationale**: found by `/speckit-analyze`; leaving it would keep a parallel writer alive
  (constitution II) and fail SC-006. Its only reader is the web Session Logs page, which
  moves to the store in US3.
- **Alternatives considered**: a fifth export reproducing both shapes (more surface for no
  remaining consumer); keeping the writer for the CLI `--report` flag (parallel writer).
