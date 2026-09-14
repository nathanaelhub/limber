# Implementation Plan: Unified PT Session Log

**Branch**: `001-unified-session-log` | **Date**: 2026-09-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-unified-session-log/spec.md`

## Summary

Replace the four legacy session writers (`SessionLogger` text files, `PTARawLogger` pipe text,
`ObservationLogger` JSON, `SessionTracker` JSON/CSV) with one canonical, schema-versioned
session record stored in a single local SQLite file, written by a single `SessionStore` and
fed by a single engine-facing `SessionRecorder`. Patients are pseudonymous. Every legacy
format becomes a pure export of a loaded session, verified against golden files produced by
the legacy loggers before they are deleted. A one-time importer brings existing files in
`sessions/` and `observation_logs/` into the record. The engine (`ExerciseTracker`,
`FormAnalyzer`, `config.yaml`) is not modified; only the logger call sites in `analyze.py`
change.

## Technical Context

**Language/Version**: Python 3.13 (repo venv at `.venv`, created from
`/opt/homebrew/bin/python3.13`)

**Primary Dependencies**: standard library only for the new package (`sqlite3`, `dataclasses`,
`json`, `csv`, `re`, `pathlib`, `datetime`). Existing `pandas` and Streamlit are used only in
`interfaces/app.py` for display. No new runtime dependencies.

**Storage**: one SQLite database file at `data/ptassist.db` (directory gitignored), WAL
journal mode, `synchronous=FULL`, one committed transaction per event. Schema versioned via a
`schema_version` table and a forward-only migration list in `src/ptlog/store.py`.

**Testing**: pytest (`.venv/bin/python -m pytest tests`). Every new test uses a `tmp_path`
database and an injected clock; no camera, network, or model weights. Export tests compare
against golden files in `tests/fixtures/golden/`.

**Target Platform**: macOS and Linux desktop, single user, offline.

**Project Type**: single Python project with a CLI and a Streamlit web interface.

**Performance Goals**: an event is durable within 1 s of the engine reporting it (spec
FR-010); a 500-event session renders in under 2 s and a 200-session history lists in under
2 s (SC-004); recording adds no more than 2 ms per inference frame so the webcam loop keeps
its current frame rate.

**Constraints**: local-only, pseudonymous IDs, no PHI in filenames or logs (constitution III);
engine untouched (constitution I); one writer, exports are pure functions (constitution II).

**Scale/Scope**: tens of patients, hundreds of sessions, up to ~20k frame samples per
session; database expected to stay under 100 MB for a full semester of use.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine is a dependency | PASS | Only the logger call sites in `analyze.py` change (video loop ~L918-1055, webcam loop ~L1238-1495). No threshold, state-machine, smoothing, or form-check edits. `SessionRecorder` reads only `ExerciseTracker.update()` output, `tracker.session` (`ExerciseSession`, `RepMetrics`, `PartialRepMetrics`), `tracker.current_state`, `tracker.rep_count`, and `OverallFormAssessment`. The `--patient` flag is interface code. |
| II. One canonical record | PASS | Single `SessionStore` writer; four exports are pure functions of a loaded `Session`; all five legacy writers (the four loggers plus `generate_session_report()`, D14) deleted once golden files exist; `schema_version` table with migrations; review pages read from the store. |
| III. Local-first, privacy | PASS | SQLite file under gitignored `data/`; exports under gitignored `exports/`; `privacy.py` enforces ID/label rules (FR-013, FR-014); export names are `{patient_id}_{start}.{ext}`; fixtures are synthetic; cascade delete (FR-017). |
| IV. Test-first | PASS | Tests listed per module in Project Structure; written before implementation per task order; `tmp_path` DBs; engine tests untouched. `tests/test_logging.py` covers the legacy writers and is replaced by `test_ptlog_exports.py` against goldens (those tests are not the engine guard). |
| V. Simplicity, readability | PASS | No new dependencies; units and plain-language definitions live in `models.py` docstrings and are surfaced in UI labels; `docs/UPDATES.md` entry required; no ORM. |
| Sequencing rule | PASS | This is the canonical-record feature that the workflow section requires first. |

Post-design re-check (after Phase 1): PASS, no changes. The `frame_samples` table is not a
second writer; it is written by the same `SessionStore` and exists only so the PTA-Log export
can reproduce the legacy per-frame "Observing" lines (see research.md D2).

## Project Structure

### Documentation (this feature)

```text
specs/001-unified-session-log/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── recorder.md      # SessionRecorder and SessionStore API
│   ├── cli.md           # CLI flags and subcommands
│   └── exports.md       # Byte-level structure of the four export formats
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/ptlog/                      # NEW package: the canonical session log
├── __init__.py                 # public re-exports
├── models.py                   # dataclasses + unit/definition docstrings
├── store.py                    # SessionStore: schema, migrations, single writer, reads
├── recorder.py                 # SessionRecorder: the only engine-facing adapter
├── privacy.py                  # patient ID / label validation
├── views.py                    # unit-labelled rows/lines for CLI + web; trend loader (D13)
├── importer.py                 # one-time legacy import with ledger
└── exports/
    ├── __init__.py
    ├── pta_log.py              # PTA-Log pipe-delimited text
    ├── observation_json.py     # observation JSON (also feeds session_summary)
    ├── csv_report.py           # CSV report
    └── text_log.py             # plain-text numbered session log

analyze.py                      # MODIFIED: logger call sites -> SessionRecorder; --patient;
                                #   --report flag + generate_session_report() calls removed (D14)
interfaces/cli.py               # MODIFIED: --patient; patients/sessions/export/import-legacy
interfaces/app.py               # MODIFIED: Patients + Sessions pages; store-backed data
src/session_summary.py          # UNCHANGED (consumes observation-JSON dict from export)
src/observation_logger.py       # DELETED after goldens captured
src/pta_raw_logger.py           # DELETED after goldens captured
src/session_tracker.py          # WRITER METHODS DELETED after goldens captured; trend/compare
                                #   read-side kept, fed from the store (see research D13)
SessionLogger in analyze.py     # DELETED after goldens captured
generate_session_report()       # DELETED after goldens captured (fifth writer, D14)

tests/
├── conftest.py                 # tmp_db, fake_clock, cli_env fixtures
├── test_ptlog_models.py        # unit/definition metadata, validation of value ranges
├── test_ptlog_store.py         # schema, migrations, writes, reads, cascade delete
├── test_ptlog_recorder.py      # fake tracker sequence -> stored events
├── test_ptlog_recovery.py      # kill mid-sequence -> interrupted + summary
├── test_ptlog_privacy.py       # FR-013 / FR-014 rules
├── test_ptlog_views.py         # unit-labelled rendering, trend loader
├── test_ptlog_exports.py       # four formats vs golden files
├── test_ptlog_importer.py      # legacy import, idempotency, malformed files
├── test_cli_ptlog.py           # subcommand contract (argparse level, no camera)
├── test_session_tracker.py     # MODIFIED: writer tests removed, trend tests kept
├── test_logging.py             # DELETED with the legacy writers (not an engine guard)
└── fixtures/
    ├── golden/                 # legacy-format reference outputs (generated once)
    │   ├── sequence.py         # fixed synthetic event sequence + FakeClock
    │   ├── generate.py         # one-off generator driving the legacy writers
    │   ├── pta_log.txt
    │   ├── observation.json
    │   ├── report.csv
    │   └── session.log
    └── legacy/                 # synthetic legacy files for importer tests
        ├── sessions/
        └── observation_logs/

data/                           # NEW, gitignored: ptassist.db
exports/                        # NEW, gitignored: default export location
```

**Structure Decision**: single project. The new code is one package under `src/` with one
sub-package for exports, mirroring the existing flat `src/` and `tests/` layout. Interface
files only render and dispatch; all logic is importable and testable without Streamlit, a
camera, or the model.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations. One design note that is not a violation: the `frame_samples` table stores a
downsampled angle stream (every 15th inference frame, matching the legacy cadence) purely so
the PTA-Log export can reproduce the legacy "Observing" lines. It is written by the same
single writer and is not an event under FR-010.
