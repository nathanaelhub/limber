# Tasks: Assigned Questionnaires

Test-first throughout (constitution IV): each implementation task has a failing-test task before it,
and the suite stays free of network, browser, camera, and model. `[P]` marks work that touches
different files from the task beside it. One commit per green checkpoint.

## Phase 1: Setup

- [x] T001 Branch `013-questionnaires`; spec; plan; tasks

## Phase 2: Foundational (blocks every story)

- [x] T002 [P] Failing `tests/test_ptlog_instruments.py`: a valid definition loads with items, choices,
      reversed items, subscales, method, missing rule, and version; refusals each name the file and the
      problem (unknown method, no items, duplicate item key, a choice value outside the item's range, a
      subscale naming an unknown item, a missing meaning or unit, item text that looks identifying); one
      bad file does not stop the others; an absent `instruments/` directory yields no instruments and no
      error; `yaml.safe_load` only
- [x] T003 Implement `src/ptlog/instruments.py` and the models (`Instrument`, `Item`, `Subscale`) in
      `src/ptlog/models.py`, with the per-directory cache used by `src/ptlog/programs.py`
- [x] T004 [P] Failing `tests/test_ptlog_questionnaires.py` with worked examples: `sum` and `mean`;
      reversal within the item's own range; subscale scores over their own items; the missing-item rule
      (below the minimum is refused, the mean of the answered items stands in when the rule says so, and
      the missing count is reported); the scoring snapshot rescores to the same total with the installed
      definition deleted or changed; `next_due` for once, weekly, fortnightly, and monthly, never
      answered and answered, and overdue by more than seven days
- [x] T005 Implement `src/ptlog/questionnaires.py` (scoring, snapshot, `next_due`, `accept`)
- [x] T006 [P] Failing `tests/test_ptlog_store_v12.py`: schema v12 adds `instrument_assignments`;
      assign, list, end, and reassign (one live assignment per instrument per patient, the ended one
      kept); deleting a patient removes their assignments and their questionnaire entries; an existing
      v11 record upgrades with every table's count intact
- [x] T007 Implement the v12 migration and the store methods

**Checkpoint**: the engine and the record are ready; no interface has changed yet.

## Phase 3: User Story 1 — the patient answers what is due (P1) 🎯 MVP

- [x] T008 [P] [US1] Failing tests in `tests/test_portal_questionnaires.py`: `/api/questionnaires`
      returns only this patient's due and assigned instruments with their items; `POST /api/entries`
      with kind `questionnaire` stores one entry carrying the answers, instrument key and version, the
      total as the score, the subscale scores, and the missing count; refusals (not assigned, unknown
      instrument, unknown item, a value not in the item's choices, too few answered, discharged
      patient); a resent client id stores nothing twice; the no-leak walk covers the new route
- [x] T009 [US1] Implement the `questionnaire` entry kind in `src/ptlog/entries.py` (fields defined by
      the instrument, not the registry), the route in `interfaces/patient_portal.py`, and the due list in
      `src/portal/viewmodels.py`
- [x] T010 [P] [US1] Failing tests: Today carries what is due with its next due date and shows it as
      done once answered
- [x] T011 [US1] Implement `interfaces/portal_static/questionnaire.html` and `questionnaire.js` (one
      scrolling form, progress, the half-finished answers kept under `limber.*` and cleared once sent,
      the total and its meaning shown on sending) and the Today entry point

**Checkpoint**: a patient can answer an assigned questionnaire on a phone, online or offline.

## Phase 4: User Story 2 — the therapist assigns and reads the score (P1)

- [x] T012 [P] [US2] Failing AppTest in `tests/test_app_pages.py`: the Patients page assigns an
      instrument with an interval, shows the next due date, and ends the assignment (keys carry the
      patient id); From the patient shows the scores with unit, direction, meaning, subscales, the
      first-to-latest change, and the item answers of one questionnaire
- [x] T013 [US2] Implement both in `interfaces/app.py`
- [x] T014 [P] [US2] Failing tests: queue kind `overdue_questionnaire` and the roster mark in
      `src/ptlog/tracker.py`; the review export row and the report lines in `src/ptlog/exports/`
- [x] T015 [US2] Implement the tracker, review, and export changes

**Checkpoint**: the therapist can assign, read the scores over time, and export them.

## Phase 5: User Story 3 — a new instrument needs no code (P2)

- [x] T016 [P] [US3] Failing test: a definition written into a temporary directory at test time is
      offered for assignment and answered end to end without touching any code; the therapist's view
      carries the "not a validated instrument" sentence from the file
- [x] T017 [US3] Write `instruments/demo_knee_function.yaml` (ten items, 0-4, two reversed, two
      subscales, `sum`, at least eight answered, its own "not a validated or licensed instrument"
      sentence) and make the therapist's view and the export carry that sentence

## Phase 6: Polish

- [x] T018 Demo data in `scripts/seed_demo.py` (two patients assigned, one with two completed
      questionnaires and one overdue); `docs/UPDATES.md` Update 15; `README`/`docs` note on adding an
      instrument
- [x] T019 Phone-emulation run in Chrome (due on Today, answering, the half-finished answers surviving
      a reload, offline send and replay, the therapist reading the score and the item answers); record
      what was verified and what was not
- [x] T020 Full suite green; checklist notes written; commit and merge to `main`

## Dependencies

- T002-T007 block everything; within them the two `[P]` test tasks can be written together.
- US1 (T008-T011) and US2 (T012-T015) both need the foundation; US2 needs US1's stored entries to have
  anything to show, so US1 goes first.
- US3 (T016-T017) needs US1 and US2 to prove "no code" end to end.
- T018-T020 come last.

## MVP

The foundation plus User Story 1: a patient answering an assigned questionnaire on their phone, stored
and scored. That alone is demonstrable; the therapist's view follows immediately after.
