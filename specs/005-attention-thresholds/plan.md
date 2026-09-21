# Implementation Plan: Configurable Attention Thresholds

**Branch**: `005-attention-thresholds` | **Date**: 2026-09-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-attention-thresholds/spec.md`

## Summary

Move the eight attention thresholds into one registry with units, meanings, defaults, and
ranges; store per-patient overrides and installation values in two small tables (schema v4);
resolve an effective set per patient (patient, else installation, else built-in); pass that set
into the flag rules and the tracker instead of module constants; show and edit it from the
command line and the web app; state it in flag evidence and review exports.

## Technical Context

**Language/Version**: Python 3.13 (repo venv `.venv`)

**Primary Dependencies**: none new; stdlib sqlite3, existing Streamlit and pandas.

**Storage**: SQLite schema v4: `patient_thresholds`, `installation_thresholds`. The v4
migration copies `review_settings.gap_days` rows and a non-default
`tracker_settings.adherence_threshold` into the new tables. The old tables stay in place and are
no longer read (forward-only, non-destructive).

**Testing**: pytest; pure-function tests for the registry and rules; store tests for the
migration from a v3 file; CLI subprocess tests; Streamlit AppTest page tests; a no-override
regression test comparing flags, roster, and queue with the pre-feature behaviour.

**Target Platform**: macOS/Linux desktop, local.

**Project Type**: single Python project with CLI and Streamlit interface.

**Performance Goals**: roster for 50 patients × 20 sessions stays inside the existing test
budget; thresholds for all patients are loaded in one query per roster build.

**Constraints**: engine untouched; one store writer; pseudonymous only; whole-number values.

**Scale/Scope**: 8 thresholds; tens of patients.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine is a dependency | PASS | No engine file is read or edited; only `src/ptlog` and the interfaces change. |
| II. One canonical record | PASS | New tables are written only by `SessionStore`; migration is forward-only and versioned (v4); exports stay pure functions that receive the effective thresholds. |
| III. Local-first, privacy | PASS | Settings are numbers keyed by pseudonymous ID; nothing leaves the machine. |
| IV. Test-first | PASS | Every task pair is test then code; the no-override regression test (FR-010) is written before the rules change. |
| V. Simplicity, readability | PASS | One registry is the single source of names, units, meanings, defaults, ranges (also exposed through `METRIC_DEFINITIONS`-style lookups); no new dependencies; `docs/UPDATES.md` entry required. |

Post-design re-check: PASS. No complexity deviations.

## Project Structure

```text
specs/005-attention-thresholds/
├── plan.md  research.md  data-model.md  quickstart.md
├── contracts/thresholds-api.md   contracts/cli.md   contracts/web.md
└── tasks.md

src/ptlog/thresholds.py       # NEW: ThresholdDef registry, Thresholds (values + origins), resolve(), validate()
src/ptlog/store.py            # schema v4 + get/set/reset for patient and installation values; effective_thresholds();
                              #   effective_thresholds_all(); get/set_gap_days and get/set_adherence_threshold become wrappers
src/ptlog/flags.py            # rules take a Thresholds argument (defaults = built-ins); evidence states the threshold
src/ptlog/review.py           # flags_for / review_summary resolve and pass thresholds; ReviewSummary.thresholds
src/ptlog/tracker.py          # per-patient adherence and gap thresholds from the effective set
src/ptlog/views.py            # threshold_rows(), threshold_lines()
src/ptlog/exports/review_report.py, review_csv.py   # thresholds section
interfaces/cli.py             # review thresholds [list|set|reset], review thresholds --installation
interfaces/app.py             # Review → Goals & settings: thresholds editor; Tracker settings: installation values
tests/test_ptlog_thresholds.py, test_ptlog_thresholds_store.py, additions to flags/review/tracker/exports/cli/app tests
```

**Structure Decision**: the registry is its own module so `flags.py`, `tracker.py`, the store,
and both interfaces share one definition without importing each other.
