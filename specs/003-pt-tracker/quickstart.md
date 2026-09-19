# Quickstart: Multi-Patient PT Tracker

Validation guide. Commands assume the repo venv and a scratch database
(`export PTASSIST_DB=/tmp/tracker.db`). See [contracts/cli.md](contracts/cli.md).

## 1. Tests

```bash
.venv/bin/python -m pytest tests -q
```

Expected: green, including `test_ptlog_programs.py`, `test_ptlog_adherence.py`,
`test_ptlog_tracker.py` (with the 50-patient performance test), `test_ptlog_roster_export.py`,
the tracker CLI tests, and the Tracker page tests.

## 2. Seed a small caseload

```bash
python interfaces/cli.py patients add P-017 --label "Post-op knee"
python interfaces/cli.py patients add P-018 --label "Shoulder"
python interfaces/cli.py import-legacy --sessions-dir tests/fixtures/legacy/sessions --obs-dir tests/fixtures/legacy/observation_logs
# reassign a few imported sessions to P-017 and P-018 with: patients reassign <id> --to P-017
```

## 3. Programs and assignment

```bash
python interfaces/cli.py tracker programs
python interfaces/cli.py tracker assign P-017 --program knee_rehab --per-week 3 --start 2026-09-01
python interfaces/cli.py tracker assign P-018 --exercises shoulder_flexion,shoulder_flexion_right --per-week 2
python interfaces/cli.py tracker assign P-017 --program hip_strengthening --start 2026-09-15
python interfaces/cli.py tracker assignments P-017
```

Expected: four pre-built programs listed plus custom; the second assignment for P-017 ends the
first on 2026-09-14 and the history shows both; an unknown exercise key is rejected by name.

## 4. Adherence

```bash
python interfaces/cli.py tracker adherence P-017
```

Expected: one row per assignment week with recorded/planned, missed weeks marked, the current
week as in progress, per-exercise performed/missing lists, and the percentage over complete
weeks (or "first week in progress").

## 5. Roster

```bash
python interfaces/cli.py tracker roster
python interfaces/cli.py tracker roster --needs-attention
python interfaces/cli.py tracker roster --program knee_rehab --sort id
```

Expected: every active patient with the columns in the contract; the attention sort puts
patients with flags first; the filters narrow the list.

## 6. Queue and threshold

```bash
python interfaces/cli.py tracker queue
python interfaces/cli.py tracker settings --adherence-threshold 30
python interfaces/cli.py tracker queue
python interfaces/cli.py review mark <pending session id> --next-step continue
python interfaces/cli.py tracker queue
```

Expected: sections for pending reviews, attention flags, practice gaps, and low adherence;
raising the threshold removes low-adherence items; reviewing a session removes its item.

## 7. Discharge and reactivate

```bash
python interfaces/cli.py tracker discharge P-018 --reason "goals met"
python interfaces/cli.py tracker roster
python interfaces/cli.py tracker discharged
python interfaces/cli.py tracker discharge P-017 --reason "moved to Jane Doe clinic"   # expect: rejected
python interfaces/cli.py tracker reactivate P-018
```

Expected: P-018 leaves the roster and queue, appears in the discharged list with the reason,
and returns on reactivation with history intact; the name-like reason is rejected.

## 8. Export

```bash
python interfaces/cli.py tracker export-roster --out /tmp/tracker-exports
```

Expected: `roster_<time>.csv` with the header in [contracts/exports.md](contracts/exports.md)
and one row per active patient.

## 9. Web app

```bash
streamlit run interfaces/app.py
```

Expected: a Tracker page with Roster, Queue, Adherence, Discharged, and Export sections; the
Patients page shows a program form with the assignment history and a discharge control.

## Done criteria

All steps behave as stated, the suite is green, `docs/UPDATES.md` has an entry, and the README
lists the tracker commands.
