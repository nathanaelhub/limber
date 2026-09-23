# Implementation Plan: Installable App and Pain Check-ins

**Branch**: `010-installable-app-checkins` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

## Summary

Make the patient portal installable (manifest, root-served service worker that caches only the shell,
install hint), give device sign-ins a 30-day lifetime, add an `entries` table (schema v9) with a
registry of kinds and fields in `src/ptlog/entries.py` modelled on the thresholds registry, a check-in
page and API with an offline queue in the page script, pain on the progress page, two whole-patient
thresholds and two rules, and a "From the patient" tab plus queue and roster marks for the PT.

## Technical Context

Python 3.13; no new dependency. SQLite v9 (`entries`), forward-only; the audit event CHECK list gains
`entry_stored` and `entry_note_removed`, so `portal_audit` is rebuilt by the documented recipe with a
migration test that counts rows before and after under `foreign_keys=ON`. Tests: pytest (entries
registry, store, flags, tracker, HTTP, AppTest); Chrome phone emulation with the network toggled off
for the quickstart.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine | PASS | Untouched. |
| II. One record | PASS | `SessionStore` writes `entries`; v9 forward-only; the rebuild migration keeps every row (tested). |
| III. Privacy (1.2.0) | PASS | Spec carries the check; notes go through `messages.check_text`; the offline snapshot is per patient and wiped on sign-out; 30-day device sign-in is the amended rule. |
| IV. Test-first | PASS | Test then code per task; no browser in the suite. |
| V. Simplicity | PASS | No new dependency; every field has a unit and meaning in the registry. |

## Structure

```text
src/ptlog/entries.py            # ENTRY_KINDS registry (checkin), validate(), definitions; pain series
src/ptlog/store.py              # v9 entries + portal_audit rebuild; entry methods; delete cascade
src/ptlog/thresholds.py         # pain_rise, pain_high (patient-level: excluded from EXERCISE_KEYS)
src/ptlog/flags.py, review.py, tracker.py, models.py   # pain rules, flags_for, queue/roster marks
src/portal/access.py            # device sign-in lifetime
src/portal/pwa.py               # manifest dict, precache list from STATIC_DIR (pure)
src/portal/viewmodels.py        # checkin_view, today gains checkin prompt, progress gains pain
interfaces/patient_portal.py    # /manifest.webmanifest, /sw.js, /api/entries, /checkin
interfaces/portal_static/       # manifest icons, sw.js, checkin.html/js, install hint in portal.js
interfaces/app.py               # Review tab "From the patient"; Patients unchanged
tests/test_portal_pwa.py test_ptlog_entries.py test_ptlog_store_v9.py + additions
```
