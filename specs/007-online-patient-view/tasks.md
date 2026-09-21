---
description: "Task list for feature 007: online patient view"
---

# Tasks: Online Patient View

**Input**: Design documents from `/specs/007-online-patient-view/`

**Tests**: REQUIRED (constitution IV). Each test task fails before its implementation task. The
suite needs no network, camera, model, or browser: `.venv/bin/python -m pytest tests`.

## Phase 1: Setup

- [X] T001 Amend the constitution to 1.1.0; branch `007-online-patient-view`; commit spec, research, plan
- [X] T002 Add lower-bound pins for starlette, uvicorn, websockets, httpx to requirements.txt; add `interfaces/portal_static/vendor/` to .gitignore; create `src/portal/__init__.py`

## Phase 2: Foundation (blocks every story)

- [X] T003 [P] Failing tests in tests/test_portal_store.py: a fresh store is at schema v6 with the three tables; a v5 file upgrades keeping data; `portal_set_code` replaces the row and deletes the patient's sign-ins; `portal_lookup` by lookup hash; `portal_revoke`; `portal_touch`; `portal_status` states none/active/expired/revoked; sign-in create/get/touch/delete/prune (three per patient); audit add/list with the CHECK vocabulary; cascade on delete and ID change; refusal for built-in, discharged, unknown patients
- [X] T004 Implement schema v6 and the portal methods in src/ptlog/store.py; entities and errors in src/ptlog/models.py
- [X] T005 [P] Failing tests in tests/test_store_live.py: patient B starting a session does not interrupt patient A's running session; the same patient's running session is still superseded (FR-012)
- [X] T006 Scope `_interrupt_running` in `start_session` to the same patient in src/ptlog/store.py
- [X] T007 [P] Failing tests in tests/test_live_session.py: `LiveSession(extras={...})` merges into the start extras and can override `origin`; `interrupt(reason)` flushes, marks the session interrupted with that reason, keeps reps, is idempotent, and `end()` afterwards returns the interrupted session
- [X] T008 Implement `extras` and `interrupt()` in src/live_session.py

## Phase 3: User Story 1 - Get access and see today's program (P1) 🎯 MVP part 1

- [X] T009 [P] [US1] Failing tests in tests/test_portal_access.py: code format `XXXX-XXXX-XXXX` from the Crockford alphabet, 1000 codes unique; `normalize` (case, spaces, dashes, O→0, I/L→1) and rejection of wrong length or characters; `lookup_hash` keyed and deterministic, different keys differ; `load_key` creates a 0600 file, reuses it, honours `PTASSIST_PORTAL_KEY`; `LoginLimiter` with a fake clock (five failures per fifteen minutes, doubling lock-out, success clears, global breaker); `client_marker` is 16 hex and never contains the address
- [X] T010 [US1] Implement src/portal/access.py, including `issue_code(store, key, patient_id, days)`, `sign_in(store, key, code, client, limiter, clock)`, `sign_out`, `current_patient(store, token, clock)` with idle and absolute limits
- [X] T011 [P] [US1] Failing tests in tests/test_portal_viewmodels.py for `today_view` and `streak`: exercises in assignment order by display name; target from the goal, else the configuration; `done_today` needs a counted rep today; no program message; week done/planned; streak rules of spec US4; removed exercise skipped with a note; the result holds only allowed keys and no other patient's ID
- [X] T012 [US1] Implement `today_view`, `adherence_view`, `streak` in src/portal/viewmodels.py
- [X] T013 [P] [US1] Failing tests in tests/test_portal_http.py with Starlette `TestClient`: health; login success sets an `HttpOnly; SameSite=Strict` cookie and returns the patient ID; wrong, expired, revoked, discharged codes get the same 401 body; sixth failure gets 429 with a wait; POST without an allowed Origin or JSON content type is refused; `/api/today` needs a sign-in, returns the contract shape, and carries `no-store`; logout ends the sign-in; revoking the code ends it at once; security headers and the content security policy on pages and API; inner pages redirect to `/` when signed out; the no-leak test over a seeded caseload (forbidden keys and other patients' IDs); audit rows for login_ok, login_failed, locked_out, logout
- [X] T014 [US1] Implement interfaces/patient_portal.py (`create_app`, routes, header middleware, `main`) and the pages index.html, today.html, portal.css, portal.js in interfaces/portal_static/
- [X] T015 [P] [US1] Failing CLI tests in tests/test_cli_portal.py: `portal code create` prints the code once with expiry and the study-use reminder, refuses built-in, discharged, unknown; `list` states; `revoke`; `audit` lines without code or address; `serve --host 0.0.0.0` without a certificate exits 1
- [X] T016 [US1] Implement the `portal` group in interfaces/cli.py
- [X] T017 [US1] Run the suite; checkpoint commit

## Phase 4: Capture origin (FR-020, SC-009; must land before home sessions are recorded)

- [ ] T018 [P] Failing tests in tests/test_ptlog_origin.py and additions to review, flags, tracker, exports tests: `capture_origin`; `SessionMeasure.origin`; trends, changes, goal progress per origin; attention rules evaluated per origin with evidence naming it; a 12° gap between a home and a clinic session raises no ROM flag; comparing a home with a clinic session is refused; adherence, pending, practice gap count all sessions; with clinic sessions only, every result equals feature 006's
- [ ] T019 Implement src/ptlog/origin.py and the per-origin evaluation in measures.py, review.py, flags use, tracker.py, views.py, exports
- [ ] T020 [P] Failing page and CLI tests: origin shown in session lists, trends, flags, compare refusal
- [ ] T021 Implement in interfaces/cli.py and interfaces/app.py; suite; checkpoint commit

## Phase 5: User Story 2 - Guided session at home (P1) 🎯 MVP part 2

- [ ] T022 [P] [US2] Failing tests in tests/test_portal_frames.py: `validate_frame` accepts 51 finite numbers with sensible w and h, null `k`, clamps slightly off-frame points, rejects wrong shapes, NaN, oversize; `to_engine_keypoints` scales uniformly to 720 and leaves angles equal; `RateMeter` observed rate, dropped count, low-rate after five seconds under 12 Hz
- [ ] T023 [US2] Implement src/portal/frames.py
- [ ] T024 [P] [US2] Failing tests in tests/test_portal_live.py: rep cycles for two exercises store two sets, the switch, `origin: portal`, targets from goal or configuration, start at the first exercise not done today; `next` ignored on the last; stop completes with the summary; interrupt keeps reps; registry refuses a second session per patient and beyond eight in total; another patient's session is untouched (SC-004)
- [ ] T025 [US2] Implement src/portal/live.py
- [ ] T026 [P] [US2] Failing tests in tests/test_portal_ws.py: handshake refused without sign-in or allowed Origin; start, frames, state messages, next, stop, ended; second device refused; rate cap drops extras; ten bad messages close with 1008 and audit; abrupt close interrupts; revoked code closes and interrupts; idle limit
- [ ] T027 [US2] Implement `WS /ws/session` in interfaces/patient_portal.py and session.html, session.js (camera, MoveNet, 15 Hz sender, mirrored overlay, state rendering)
- [ ] T028 [P] [US2] Failing test for scripts/fetch_portal_assets.py (hash check against local files, refuses a mismatch); implement it with the recorded hashes
- [ ] T029 [US2] Suite; checkpoint commit

## Phase 6: User Story 3 - Progress (P2) and User Story 4 - Streak (P2)

- [ ] T030 [P] [US3] Failing tests for `progress_view` (per-origin series, change, goal sentence, too-few message, definitions, allowed keys) and `/api/progress`; streak shown on today and progress pages
- [ ] T031 [US3] Implement in src/portal/viewmodels.py, interfaces/patient_portal.py, progress.html; suite; checkpoint commit

## Phase 7: User Story 5 - Therapist control (P3)

- [ ] T032 [P] [US5] Failing page test: Patients page Home access block (state, issue shows the code once, revoke); audit view
- [ ] T033 [US5] Implement in interfaces/app.py; suite; checkpoint commit

## Phase 8: Polish

- [ ] T034 [P] scripts/seed_demo.py: home sessions for one patient and an optional demo code; docs/UPDATES.md (Update 9), README.md, docs/PROJECT_OVERVIEW.md
- [ ] T035 Quickstart steps 1-5 and 7 (scripted fake-camera browser run outside the repo); record results, including whether step 6 was run; final commit and merge

## Dependencies

Phase 2 blocks all. US1 needs Phase 2. Phase 4 must precede Phase 5. US3 needs Phase 4. US5 needs US1.
MVP = Phases 1-5.
