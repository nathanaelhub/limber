# Implementation Plan: Review Over Time

**Branch**: `002-review-over-time` | **Date**: 2026-09-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-review-over-time/spec.md`

## Summary

Add the clinical review layer on top of the canonical session record: per-session,
per-exercise measures derived from recorded reps; trend series over a period; seven explicit
attention rules with evidence; side-by-side comparison; one review per session (notes, next
step, reviewed time) with a pending list; goals and a per-patient gap threshold; and a review
summary export as text and CSV. Schema migration 2 adds `reviews`, `goals`,
`review_settings`, and `review_exports`. The legacy trend code in `src/session_tracker.py`,
the CLI `progress` command, and the web Progress Report and PT Summary pages are retired and
replaced by a `review` command group and one Review page. Nothing about recording changes.

## Technical Context

**Language/Version**: Python 3.13 (repo venv `.venv`)

**Primary Dependencies**: standard library (`statistics.pstdev`, `csv`, `datetime`,
`sqlite3`); `src.session_summary` reused unchanged for the per-session summary; pandas and
Streamlit only inside `interfaces/app.py`. No new runtime dependencies.

**Storage**: the existing SQLite file; forward-only migration 2 adds four tables (see
data-model.md). Reviews key on `session_id`, so they follow a session on reassignment and
vanish on cascade delete; goals, settings, and review exports key on `patient_id`.

**Testing**: pytest with `tmp_path` databases and the fixed clock from
`tests/fixtures/golden/sequence.py`; rule tests build one history per rule plus a clean
history; export tests compare against expected text; CLI via subprocess; web pages via
Streamlit `AppTest`; a 200-session performance test.

**Target Platform**: macOS/Linux desktop, single user, offline.

**Project Type**: single Python project with CLI and Streamlit interface.

**Performance Goals**: trend, flags, comparison, and pending views for a patient with 200
sessions each render in under 2 s (SC-004); exports in under 2 s.

**Constraints**: read-only with respect to recording (FR-024, constitution I/II); local and
pseudonymous (FR-025, constitution III); notes rejected on the label patterns (FR-009).

**Scale/Scope**: tens of patients, hundreds of sessions each, up to ~15 exercises per patient.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine is a dependency | PASS | No file under the engine's definition is touched; `analyze.py` is not modified. Everything derives from `Session` objects loaded by `SessionStore`. |
| II. One canonical record | PASS | Reviews, goals, and settings live in the same SQLite file via migration 2 with a migration test that opens a version-1 database; no new writer for session data; exports are pure functions of a `ReviewSummary`. |
| III. Local-first, privacy | PASS | Notes validated with `privacy.validate_notes` (same patterns as labels); review export names carry only the pseudonymous ID, period, and time; `review_exports` rows let `delete_patient` unlink the files. |
| IV. Test-first | PASS | Every module has a test file written before it; engine tests untouched; `tests/test_session_tracker.py` is deleted with the module it tested (not an engine guard). |
| V. Simplicity, readability | PASS | No dependencies; three new definitions added to `METRIC_DEFINITIONS` (rep duration, tempo consistency, partial-rep share); `docs/UPDATES.md` entry; flag thresholds are named constants with docstrings quoting FR-014. |
| Sequencing rule | PASS | Depends on 001, which is merged on `main`. |

Post-design re-check (after Phase 1): PASS, no changes.

## Project Structure

### Documentation (this feature)

```text
specs/002-review-over-time/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── review-api.md        # measures, flags, review module and store API
│   ├── cli.md               # review command group
│   └── exports.md           # review report and CSV layouts
├── checklists/requirements.md
└── tasks.md                 # /speckit-tasks output
```

### Source Code (repository root)

```text
src/ptlog/
├── models.py                # + Review, Goal, ReviewSettings, SessionMeasure, Flag, Trend,
│                            #   Comparison, ReviewSummary; NEXT_STEPS; PERIODS; 3 metric definitions
├── store.py                 # + migration 2; reviews/goals/settings CRUD; sessions_in_period;
│                            #   exercise_names; record_review_export; delete_patient unlinks review exports
├── privacy.py               # + validate_notes (same patterns, no length cap)
├── measures.py              # NEW: per-session per-exercise measures (pure)
├── flags.py                 # NEW: the seven rules with thresholds and evidence (pure)
├── review.py                # NEW: trend, compare, pending, goal progress, ReviewSummary assembly
├── views.py                 # + rendering for trends/flags/comparison/reviews; − load_session_data_for_trends
└── exports/
    ├── review_report.py     # NEW: text report (pure)
    ├── review_csv.py        # NEW: CSV (pure)
    └── __init__.py          # + write_review_export

src/session_summary.py       # UNCHANGED (consumed via to_observation_dict)
src/session_tracker.py       # DELETED (superseded)
interfaces/cli.py            # + review command group; − progress command
interfaces/app.py            # + page_review (tabs); − page_progress_report, page_pt_summary

tests/
├── conftest.py              # + fixed_store, make_session fixtures
├── test_ptlog_privacy.py    # + validate_notes cases
├── test_ptlog_measures.py
├── test_ptlog_flags.py
├── test_ptlog_review.py     # store CRUD, cascade/reassign, trend, compare, pending, summary, migration, perf
├── test_ptlog_review_exports.py
├── test_cli_ptlog.py        # + review commands
├── test_app_pages.py        # review page replaces progress/pt_summary
├── test_ptlog_views.py      # − trend loader test
└── test_session_tracker.py  # DELETED
```

**Structure Decision**: same single-project layout as feature 001. Pure computation
(`measures`, `flags`, review assembly, exports) is separated from persistence (`store`) and
from rendering (`views`, interfaces), so every rule and number is testable without Streamlit
or a database.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations.
