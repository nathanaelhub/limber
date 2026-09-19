# Implementation Plan: Multi-Patient PT Tracker

**Branch**: `003-pt-tracker` | **Date**: 2026-09-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-pt-tracker/spec.md`

## Summary

Add the caseload layer on top of the canonical record and the review feature: a roster of
active patients with counts, adherence, pending reviews, open flags, and the last next step;
program assignment from the configuration's pre-built programs or a custom exercise list;
week-by-week adherence against the plan; a cross-patient queue of pending reviews, attention
flags, practice gaps, and low adherence; discharge and reactivation; and a roster CSV export.
Schema migration 3 adds `assignments`, `discharges`, and `tracker_settings`. Nothing about
recording changes.

## Technical Context

**Language/Version**: Python 3.13 (repo venv `.venv`)

**Primary Dependencies**: standard library; PyYAML (already installed) for the program
catalog in `config.yaml`; pandas and Streamlit only inside `interfaces/app.py`.

**Storage**: the existing SQLite file; forward-only migration 3 (see data-model.md).

**Testing**: pytest with `tmp_path` databases, the fixed clock, and the `make_session`
fixture; a temporary config file for the catalog tests; a 50-patient × 20-session
performance test.

**Target Platform**: macOS/Linux desktop, single user, offline.

**Project Type**: single Python project with CLI and Streamlit interface.

**Performance Goals**: roster and queue for 50 active patients with 20 sessions each render
in under 3 s (SC-002). Each patient's sessions are loaded once for the widest window needed
and reused for counts, flags, and adherence (research D6).

**Constraints**: read-only with respect to recording (FR-019, constitution I/II); local and
pseudonymous (FR-020, constitution III); discharge reasons validated with the notes rules.

**Scale/Scope**: tens of patients per installation, hundreds of sessions each, four pre-built
programs plus custom lists.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine is a dependency | PASS | No engine file is touched. Programs are read from `config.yaml` without changing it; recorded sets already carry `exercise_key`. |
| II. One canonical record | PASS | Assignments, discharges, and settings live in the same SQLite file via migration 3 with an upgrade test; roster, adherence, and queue are derived on request, never stored. |
| III. Local-first, privacy | PASS | Discharge reasons pass `validate_notes`; roster export name carries only the generation time; labels are already non-identifying by rule. |
| IV. Test-first | PASS | Every module has a test file written before it; engine tests untouched. |
| V. Simplicity, readability | PASS | No dependencies; adherence units and definitions added to `METRIC_DEFINITIONS`; thresholds are named constants; `docs/UPDATES.md` entry required. The exercise catalog loader moves from `importer.py` to `programs.py` so there is one loader. |
| Sequencing rule | PASS | Depends on 001 and 002, both merged on `main`. |

Post-design re-check (after Phase 1): PASS, no changes.

## Project Structure

### Documentation (this feature)

```text
specs/003-pt-tracker/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── tracker-api.md       # programs, adherence, tracker modules and store API
│   ├── cli.md               # tracker command group
│   └── exports.md           # roster CSV layout
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/ptlog/
├── models.py                # + Program, Assignment, Discharge, AdherenceWeek, Adherence, RosterRow,
│                            #   QueueItem, QueueResult, TrackerSettings; ASSIGNMENT_STATUSES, QUEUE_KINDS;
│                            #   adherence metric definitions; ProgramValidationError, AssignmentValidationError
├── store.py                 # + migration 3; assignments CRUD with supersession; discharge/reactivate;
│                            #   active/discharged patient lists; adherence threshold; latest_review
├── programs.py              # NEW: config catalog (exercises + programs), custom-key validation
├── adherence.py             # NEW: assignment weeks, coverage, percentage, status (pure)
├── tracker.py               # NEW: patient snapshot, roster rows, sort/filter, queue, roster rows for CSV
├── importer.py              # exercise_catalog() now delegates to programs.py
├── views.py                 # + roster/queue/adherence rendering
└── exports/
    ├── roster_csv.py        # NEW: to_roster_csv, write_roster_export
    └── __init__.py          # + roster export registration

interfaces/cli.py            # + tracker command group
interfaces/app.py            # + page_tracker (sections); Patients page gains assignment + discharge controls

tests/
├── conftest.py              # + D0_DATE, caseload fixture
├── test_ptlog_views.py      # + roster/adherence/queue rendering
├── test_ptlog_programs.py
├── test_ptlog_adherence.py
├── test_ptlog_tracker.py    # migration 3, store CRUD, roster, queue, discharge, performance
├── test_ptlog_roster_export.py
├── test_cli_ptlog.py        # + tracker commands
├── test_app_pages.py        # + Tracker page sections, Patients page controls
└── fixtures/config_small.yaml  # temp catalog for program tests
```

**Structure Decision**: same single-project layout. Pure computation (`adherence`, the
snapshot/roster/queue assembly in `tracker`) is separated from persistence (`store`) and
rendering (`views`, interfaces) so every column and queue item is testable without Streamlit.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations.
