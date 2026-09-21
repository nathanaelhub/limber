# Implementation Plan: Threshold Refinements

**Branch**: `006-threshold-refinements` | **Date**: 2026-09-21 | **Spec**: [spec.md](spec.md)

## Summary

Schema v5 adds `exercise_thresholds` and `threshold_changes`. `thresholds.resolve` gains an
exercise layer; `flags.evaluate` accepts a per-exercise map; the store records a history row on
every effective change, inside the same transaction as the change. CLI and web editors gain an
exercise selector and a history view; review exports name exercise overrides.

## Technical Context

**Language/Version**: Python 3.13 (`.venv`). **Dependencies**: none new. **Storage**: SQLite v5,
forward-only. **Testing**: pytest (pure, store, CLI subprocess, Streamlit AppTest).
**Performance**: one extra query per roster build (all exercise overrides at once).

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine is a dependency | PASS | No engine file touched. |
| II. One canonical record | PASS | `SessionStore` is the only writer of both new tables; history is written in the same transaction as the change. |
| III. Local-first, privacy | PASS | History holds keys and whole numbers only; removed with the patient. |
| IV. Test-first | PASS | Tests precede code per task pair; FR-009 regression test first. |
| V. Simplicity | PASS | Reuses the 005 registry and editors; `docs/UPDATES.md` entry. |

## Project Structure

```text
src/ptlog/thresholds.py   # EXERCISE_KEYS, resolve(..., exercise=), origin "exercise", validate_exercise_key
src/ptlog/store.py        # schema v5; exercise get/set/reset; _log_change; threshold_history(); effective_thresholds_by_exercise(_all)
src/ptlog/flags.py        # evaluate(..., per_exercise=None)
src/ptlog/review.py       # resolve per-exercise sets; ReviewSummary.exercise_thresholds
src/ptlog/tracker.py      # pass per-exercise sets from one bulk load
src/ptlog/views.py        # history_lines/rows; threshold rows for an exercise
src/ptlog/exports/review_report.py, review_csv.py
interfaces/cli.py         # review thresholds --exercise NAME, --history
interfaces/app.py         # exercise selector in the editor; history expanders
```
