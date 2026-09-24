# Implementation Plan: Exercise Diary, Medication and Sleep Logs

**Branch**: `012-diary-logs` | **Date**: 2026-09-24 | **Spec**: [spec.md](spec.md)

## Summary

Schema v11 rebuilds `sessions` so `source` also allows `diary`, and adds reported reps, sets, and
effort to `exercise_sets`, plus a per-patient medication list and a diary switch. `capture_origin`
gains `self-reported`; adherence, done-today, the streak, and the session summary count diary
sessions; trends, flags, goal progress, and comparison skip them. Two new entry kinds (`medication`,
`sleep`) reuse the feature 010 registry and routes. Patient pages: "I did this without the camera"
and a daily log. PT: diary, medication, and sleep in the "From the patient" tab, and the list and
switch on the Patients page.

## The dangerous part, and how it is made safe

SQLite cannot alter a CHECK constraint, so `sessions` must be rebuilt. With foreign keys on, dropping
the old table cascades and would delete every set, rep, review, and entry. The migration therefore:
turns foreign keys off outside a transaction, creates `sessions_new`, copies, drops the old table,
renames (never renaming first, since modern SQLite rewrites child references to follow a rename),
recreates both indexes, and runs `PRAGMA foreign_key_check`. A test writes a realistic v10 record
(patients, sessions, sets, reps, reviews, entries, media, messages, audit), upgrades it, and compares
every table's row count before and after. `deploy` already backs up before migrating in the runbook.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine | PASS | Untouched; diary sessions carry no angles and never reach the engine's rules. |
| II. One record | PASS | One writer; forward-only v11; the rebuild is row-preserving and tested. |
| III. Privacy (1.2.0) | PASS | Numbers and fixed choices; the medication list is the therapist's words, privacy-checked; notes privacy-checked. |
| IV. Test-first | PASS | Migration test first; rules then interfaces. |
| V. Simplicity | PASS | No new dependency; reuses the entries registry and the origin split. |

## Structure

```text
src/ptlog/store.py        # v11 rebuild; reported_* columns; medication list; diary switch; summary counts diary
src/ptlog/origin.py       # DIARY = "self-reported"
src/ptlog/adherence.py    # a set counts when it has a counted rep or reported reps
src/ptlog/review.py       # comparison rules skip the diary origin
src/ptlog/entries.py      # medication and sleep kinds
src/portal/diary.py       # log_exercise(): builds the diary session through the store
interfaces/patient_portal.py + portal_static/diary.html, log.html
interfaces/app.py         # Patients: medication list + diary switch; From the patient: diary, medication, sleep
```
