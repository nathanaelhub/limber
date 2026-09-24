# Implementation Plan: Assigned Questionnaires

**Branch**: `013-questionnaires` | **Date**: 2026-09-24 | **Spec**: [spec.md](spec.md)

*(As with features 010-012, the design artefacts the template lists separately — research, data model,
contracts, quickstart — are folded into this one file and `tasks.md`. Nothing here is unresolved, so a
research document would be empty, and the contract is three routes and one file format, described
below.)*

## Summary

A scoring engine reads instrument definitions from `instruments/*.yaml` beside `config.yaml`, so a new
instrument needs one file and no code. Schema v12 adds `instrument_assignments` (which instrument a
patient answers, how often, from when, whether it has ended). A completed questionnaire is stored as one
entry of kind `questionnaire` — a kind the `entries` table has allowed since v9, so **no table rebuild
is needed this time**. The patient answers what is due from Today, through the existing offline queue.
The therapist assigns and ends assignments on the Patients page and reads the scores over time in
Review → From the patient, with the unit, the direction, and the meaning taken from the definition.
One demo instrument ships with the repository; it is not a licensed one.

## The dangerous parts, and how they are made safe

1. **A definition file is input, not code.** It is parsed with `yaml.safe_load` (never `load`), every
   field is checked by type and range, and nothing in it is ever evaluated. An invalid file is reported
   with its name and the problem and is skipped; the other instruments and the whole app still work,
   including with the `instruments/` directory absent. Item text goes through the same privacy check as
   patient text, so an instrument cannot ask for a name or a record number.
2. **A stored score must never change under the therapist's feet.** The entry payload carries a
   *scoring snapshot*: the method, each answered item's key, value, range, and whether it was reversed,
   the subscale membership, and the missing-item rule, alongside the computed total. The record is
   therefore self-contained: any stored questionnaire can be rescored to the same total years later even
   if the file has been edited or deleted (SC-002), and the therapist is told when the installed
   definition differs from the one answered rather than being shown a silently rescored number.
3. **Scoring is arithmetic, not interpretation.** `sum` or `mean`, reversal within the item's own range,
   subscales over their own items, and one missing-item rule. No threshold, no attention flag, and no
   clinical judgement is derived from a score in this feature; the sentence that says what the score
   means comes from the file.
4. **Arithmetic that is easy to get subtly wrong** — reversal, the mean of answered items, a subscale
   with a missing item — is where the tests go first, with worked examples in the test file itself.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine | PASS | Untouched. A questionnaire carries no angles and never reaches the engine. |
| II. One record | PASS | One writer; forward-only v12; a plain `CREATE TABLE`, no rebuild; the scoring snapshot keeps the record self-contained. |
| III. Privacy (1.2.0) | PASS | Fixed choices the therapist assigned, plus the instrument's own optional note through the privacy check; instruments may not ask for identifying details; scoring is arithmetic on the host. |
| IV. Test-first | PASS | The engine's arithmetic and the loader's refusals are tested before they exist; no network, browser, camera, or model in the suite. |
| V. Simplicity | PASS | No new dependency (PyYAML is already used for `config.yaml`); every number carries a unit and a meaning, taken from the definition. |

## Structure

```text
instruments/demo_knee_function.yaml   # the one shipped instrument, explicitly not a licensed one
src/ptlog/instruments.py              # load and validate definitions; cache per directory, like programs.py
src/ptlog/questionnaires.py           # scoring, the due-date rule, accepting an answer set
src/ptlog/store.py                    # v12 instrument_assignments; assign / end / list; cascade on patient delete
src/ptlog/entries.py                  # the questionnaire kind: fields defined by the instrument, not the registry
src/ptlog/models.py                   # Instrument, Item, Subscale, Assignment, QuestionnaireScore; QUEUE_KINDS
src/ptlog/tracker.py                  # overdue questionnaires in the queue and on the roster
src/ptlog/review.py + exports/        # scores over time, first-to-latest change, export rows and report lines
src/portal/viewmodels.py              # what is due on Today; the instrument to answer
interfaces/patient_portal.py          # GET /api/questionnaires; POST /api/entries accepts kind questionnaire
interfaces/portal_static/questionnaire.html + .js
interfaces/app.py                     # Patients: assign and end; From the patient: scores, items, definitions
```

## Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Where definitions live | `instruments/*.yaml` at the repository root, next to `config.yaml`; overridable by path for tests | The owner asked for one file per instrument beside the configuration; tests point at a temporary directory |
| Repeat intervals | `once`, `weekly`, `fortnightly`, `monthly` | The owner's example was "every 2 weeks"; whole weeks and calendar months cover the clinical cases without a scheduling language |
| Due date | The start date when never answered, else the last answered date plus the interval; `once` stops after one answer | Simple, explainable to the patient, and testable without a clock |
| Overdue | More than 7 days past due reaches the work queue (`overdue_questionnaire`) and the roster | Matches the existing practice-gap style of nudge rather than adding a new kind of alarm |
| One live assignment per instrument per patient | A partial unique index (`WHERE ended_at IS NULL`) | Assigning again replaces rather than duplicating; the history of ended assignments stays |
| Sending an answer set | The existing `POST /api/entries` with kind `questionnaire` | The offline queue already replays that route; a new route would need its own queue |
| A half-finished questionnaire | Kept in the phone's own storage under `limber.*`, cleared when sent, wiped on sign-out | Nothing unfinished belongs on the host, and the patient should not lose six answers to a phone call |
| Missing items | Per instrument: the minimum number answered, and whether the mean of the answered items stands in for a missing one; below the minimum the answer set is refused | Scoring rules differ per instrument, and a total from three of ten items would mislead |
| No flags from a score | Out of scope, stated in the spec | Deriving attention rules from an unvalidated demo instrument would be pretending to clinical knowledge we do not have |

## The demo instrument

`instruments/demo_knee_function.yaml`: "Demo Knee Function", ten items, five choices each valued 0-4
with words at both ends, higher is better, total 0-40 by `sum`, two subscales (Pain, four items;
Activity, six items), two reversed items so that reversal is exercised by the demo itself, a
missing-item rule of at least eight answered with the mean standing in. Its own description says in one
line that it is written for this project for demonstration and is not a validated or licensed
instrument, and the therapist's view shows that sentence wherever its score appears.

## Risks

1. **Mistaking the demo for a clinical instrument.** The file, the therapist's view, and the export all
   carry the "not a validated instrument" sentence. The owner sources real instruments and licences.
2. **Scoring arithmetic.** Reversal and missing items are the classic errors; worked examples in the
   tests, and the record stores the snapshot that produced each score so any number can be checked.
3. **An instrument that grows too long for a phone.** Ten items is the demo; the page is one scrolling
   form with progress, and SC-001 (two minutes) is measured in the browser run.
4. **Editing a definition after answers exist.** Handled by the snapshot and by telling the therapist
   the version differs; nothing is rescored silently.
5. **Scope creep towards a form builder.** Out of scope: branching, skip logic, free-text items beyond
   one optional note, reminders, and scoring bands.
