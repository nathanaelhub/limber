# Tasks: The Clinic App (feature 019)

Each slice is one issue, branch, and pull request. The Streamlit app keeps working until slice 8. Tests come first
in every slice. A page's old UI tests are removed only at cutover, once its clinic tests exist. Every slice ends by
deploying to the hosted demo (`scripts/deploy_vercel.sh`) and checking its pages there, at 1280px with Larger text
and Higher contrast on. Revised 11 November 2026 with the hosted demo (020) and the owner's decisions. Milestones:
M2 after slice 2, M3 (the first showing) after slice 4, M4 after slice 6, M5 at cutover.

## Slice 0: Spec

- [x] T001 Spec, tasks, constitution 1.4.0, and the Claude Design prompt
- [x] T002 **G1**: the owner ran the prompt; the export is in `design/limber-clinic-export/` (PR #42)

## Slice 1: Foundation (Story 1; FR-001 to FR-006, FR-010, FR-012, FR-016)

- [x] T003 `interfaces/web_common.py`: the portal's shared web helpers lifted out of `patient_portal.py` with
      parameters (CSP builder, security headers with a `csp=` argument, JSON and error responses, `check_post`,
      the client marker, HTML pages with first-render classes, the hosted 503 handler); the portal keeps its names
- [x] T004 `src/clinic/`: `signin.py` (account from the cookie, role check, safe `next`), `nav.py` (top bar, Tools
      and Me menus by role, which pages are online), `prefs.py` (preferences to `lt`/`hc`/`lm`), `charts.py`
      (SVG line and bar charts with a table, text that scales)
- [x] T005 `interfaces/clinic.py` under `/therapist`: one store opener per request that always applies
      `ptaccounts.restrict`; every route registered with the role it needs; Origin and content-type checks; CSP
- [x] T006 Sign-in: redeem the pass and remove it from the address, the `limber_staff` cookie, the in-app sign-in
      screen with the portal's lockouts, sign out, the setup message when no staff password is set
- [x] T007 Shell from the design: converted `limber.css` (no `style=`, `[hidden]` rule), self-hosted Sora, top bar
      and menus; My settings (Larger text, Higher contrast, Less motion), applied on first render
- [x] T008 Tests: sign-in (gate, pass single use, cookie flags, reload keeps sign-in, expiry, in-app form, 403, 415),
      static files (no inline style or script, no outside URL), charts, nav by role
- [x] T009 Route-table test (SC-004): every route declares its role; `rivera` gets 404 for another therapist's
      patient, plan, visit or file on every route; admin-only accounts get 403 on clinical routes
- [x] T010 The portal's service worker never handles `/therapist` (FR-016), with a test
- [x] T011 `interfaces/cli.py clinic` (port 8502); the hosted demo mounts the clinic at `/therapist` in
      `interfaces/vercel_app.py`; importing the clinic loads nothing heavy (test); deploy and check

## Slice 2: Inbox (Story 2; FR-007 to FR-009) → milestone M2

- [x] T012 `src/clinic/inbox.py`: "Needs you" (unread by plan, reschedule requests, red flags), plan summary,
      send-anyway as a confirm round trip, the draft guard, read-only precedence, voice-note states, with tests
- [x] T013 Routes and page: list, thread (`messages.thread(viewer="therapist", mark_read=False)`), explicit read,
      reply, attachments, voice notes, remove, messaging switch, reschedule answer
- [x] T014 AI draft, withheld notice, mark handled by phone, and AI labels, with tests
- [x] T015 Test: opening the Inbox marks nothing read (FR-007); deploy and check

## Slice 3a: Patients (Story 3)

- [x] T016 `src/clinic/patients.py`: list rows, header and metrics, plans-section rules, questionnaire grouping,
      home-access display, with tests
- [x] T017 Patient list and detail; register; Overview; Exercises (program, questionnaires); Details (plans of care,
      visits, what the patient can log, home access, caseload status, label and notes, delete)
- [x] T018 Tests for each behaviour pinned in `tests/test_app_pages.py`, `test_app_layout.py` (patient tabs), and
      `test_app_plans.py`; deploy and check

## Slice 3b: Notes and AI (Story 3)

- [ ] T019 `src/clinic/assist_view.py`: the weekly-summary states, citation labels, coach-log counts, "no key, no
      AI control", with tests
- [ ] T020 Session notes, weekly summary, AI settings and coach log; tests for each behaviour in
      `test_app_assist.py`; deploy and check

## Slice 4: Schedule and People (Story 4) → milestone M3, the first showing

- [ ] T021 `src/clinic/schedule.py` (the visit list moved from `app.py`), with tests; Schedule page
- [ ] T022 `src/clinic/people.py`: invite, revoke, disable and re-enable (never the last admin), reassign;
      refused for non-admins; no clinical fields
- [ ] T023 Deploy and run the "daily work" dry run on the hosted demo

## Slice 5a: Dashboard, Sessions, Observation logs (Story 5; FR-011)

- [ ] T024 `src/clinic/dashboard.py`; Sessions with exports; Observation logs (charts, rep table, timeline)
- [ ] T025 `src/clinic/exports.py` with the standard library, checked against golden files taken from today's
      pandas output first (rep CSV, full log JSON, video report)

## Slice 5b: Review (Story 5)

- [ ] T026 Measures, flags, compare, session review, from the patient, goals and thresholds (save rules moved,
      with tests), exports

## Slice 5c: Tracker (Story 5)

- [ ] T027 Roster, queue, adherence (line filter moved), discharged, export, installation thresholds; deploy and check

## Slice 6: Video analysis and How it works (Story 5, scenario 3; FR-014) → milestone M4

- [ ] T028 `src/clinic/video.py`: count and score browser body points with the engine's rules (a `source` parameter
      on `LiveSession`); `video.js` runs MoveNet over the clip and sends one request; results, rep chart, downloads
- [ ] T029 How it works, without the placeholder images or the made-up formula
- [ ] T030 **G2** comparison: MoveNet and YOLO11 on the three Ultralytics clips (rep count, range of motion, form
      score), a regression test on saved fixtures, the owner's decision

## Slice 7: Live session (Story 5, scenario 4; FR-013)

- [ ] T031 Therapist session page on the browser pose path, recorded under the chosen patient, using 020 slice F's
      transport and lease; switch, reset, target reps; screenshot as a browser download

## Slice 8: Cutover (FR-015) → milestone M5

- [ ] T032 **G3**: re-run the 16 user cases against the clinic app, locally and on the hosted demo
- [ ] T033 Move to :8501; update the portal default, `deploy/*`, and `interfaces/cli.py`
- [ ] T034 Remove `interfaces/app.py`, `interfaces/app_theme.py`, `.streamlit/`, `streamlit`, `streamlit-webrtc`,
      `pyarrow`, `pandas` (if unused), and the old UI tests, after a list maps each behaviour to its clinic test or
      to SC-003's retired list
- [ ] T035 Constitution: remove the transition wording and the Streamlit mention in Principle V
- [ ] T036 `docs/UPDATES.md`, `README.md`, `docs/PROJECT_OVERVIEW.md`, `docs/DEPLOYMENT.md`; retake the user-case
      screenshots and rebuild the User Cases PDF
