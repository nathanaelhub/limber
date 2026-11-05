# Tasks: The Clinic App (feature 019)

Each slice is one issue, branch, and pull request. The Streamlit app keeps working until slice 8. Tests come first
in every slice. A page's old UI tests are removed only at cutover, once its clinic tests exist.

## Slice 0: Spec

- [ ] T001 Spec, tasks, constitution 1.4.0, and the Claude Design prompt
- [ ] T002 **G1**: the owner runs the prompt, saves the export to `design/limber-clinic-export/`, and approves it

## Slice 1: Foundation (Story 1; FR-001 to FR-006, FR-010, FR-012)

- [ ] T003 `interfaces/clinic.py`: app factory, shared store opener with `ptaccounts.restrict`, Origin and content-type checks, content security policy
- [ ] T004 Sign-in: redeem the pass, set the cookie, sign out, setup message when no staff password is set; the portal's `therapist_url` points at :8502 only when configured
- [ ] T005 Tests: sign-in gate, pass redemption, cookie flags, reload keeps sign-in, cross-origin refusal, no outside resources
- [ ] T006 Shell: top bar, Tools and Me menus by role, patient search, tokens from the export, self-hosted Sora, accessibility classes on first render
- [ ] T007 SVG chart helper with a table equivalent
- [ ] T008 Route-table test: role and caseload rules apply to every route as routes are added (SC-004)
- [ ] T009 `interfaces/cli.py`: a launch command for the clinic app

## Slice 2: Inbox (Story 2; FR-007 to FR-009)

- [ ] T010 `src/clinic/`: "Needs you" list, send-anyway state, draft guard, default selection, plan summary, with tests
- [ ] T011 Routes and page: list, thread, attachments, voice notes, reply, remove, messaging switch
- [ ] T012 AI draft, withheld notice, and AI labels, with tests
- [ ] T013 Test: opening the Inbox marks nothing read (FR-007)

## Slice 3: Patients (Story 3)

- [ ] T014 Patient list and detail layout; register a patient
- [ ] T015 Overview, Exercises (program), Messages, Session notes and weekly summary
- [ ] T016 AI settings and coach log
- [ ] T017 Details: plans of care, visits, questionnaires, what the patient can log, home access, caseload status, label and notes, delete
- [ ] T018 Tests for each behaviour pinned in `tests/test_app_pages.py`, `test_app_assist.py`, and `test_app_plans.py`

## Slice 4: Schedule and administration (Story 4)

- [ ] T019 Schedule visit list moved to `src/clinic/`, with tests; Schedule page
- [ ] T020 People: invite, revoke, disable, reassign; refused for non-admins
- [ ] T021 My settings

## Slice 5: Records (Story 5, scenarios 1 and 2; FR-011)

- [ ] T022 Dashboard from real data (replaces the sample rows at `interfaces/app.py:429-433`)
- [ ] T023 Sessions and exports
- [ ] T024 Review: measures, first to latest, per-session summary, thresholds, goals, patient videos, logs, medication, sleep, questionnaires, check-ins, voice notes, exports
- [ ] T025 Tracker and installation thresholds
- [ ] T026 Observation logs: charts, rep table, event timeline
- [ ] T027 Test: exports match the current output for the same data

## Slice 6: Video analysis and How it works (Story 5, scenario 3; FR-014)

- [ ] T028 Upload, background job, progress, annotated video, report downloads
- [ ] T029 How it works, with the form score calculator and no placeholder images

## Slice 7: Live session (Story 5, scenario 4; FR-013)

- [ ] T030 Therapist session page on the browser pose path, recorded under the chosen patient
- [ ] T031 Comparison of MoveNet and YOLO11 on the same clips: rep count, range of motion, form score
- [ ] T032 **G2**: the owner reviews the comparison and decides

## Slice 8: Cutover (FR-015)

- [ ] T033 **G3**: re-run the 16 user cases against the clinic app
- [ ] T034 Move to :8501; update the portal default, `deploy/*`, and `interfaces/cli.py`
- [ ] T035 Remove `interfaces/app.py`, `interfaces/app_theme.py`, `streamlit`, `streamlit-webrtc`, and the old UI tests, after checking each behaviour has a clinic test (SC-003)
- [ ] T036 Constitution: remove the transition wording and the Streamlit mention in Principle V
- [ ] T037 `docs/UPDATES.md`, `README.md`, `docs/PROJECT_OVERVIEW.md`; rebuild the User Cases PDF
