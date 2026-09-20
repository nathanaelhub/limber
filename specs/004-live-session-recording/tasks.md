---
description: "Task list for feature 004: live web session recording"
---

# Tasks: Live Web Session Recording

**Input**: Design documents from `/specs/004-live-session-recording/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED (constitution IV). Every test task is written first and must fail before
its implementation task. Suite command: `.venv/bin/python -m pytest tests`.

**Organization**: by user story; each story is independently testable.

## Phase 1: Setup

- [X] T001 Create branch `004-live-session-recording`, confirm the suite is green, and commit the design documents under specs/004-live-session-recording/
- [X] T002 [P] Add the synthetic pose helpers to tests/fixtures/poses.py: `keypoints_for_angle(angle)` returning a (17, 3) float array whose left hip (11), knee (13), ankle (15) form the requested angle with confidence 1.0, `rep_cycle(top, bottom, hold)` yielding an angle sequence that holds each end for `hold` frames, and `FakeInfer(angles)` returning keypoints per call (None for a None angle)

## Phase 2: Foundational (blocks all stories)

- [X] T003 [P] Write failing store tests in tests/test_store_live.py: `check_same_thread=False` lets another thread write; a running session whose `source_extras.pid` is this process survives a second `SessionStore.open()`; one with a dead pid (spawn and wait a subprocess for its pid) or no pid is marked interrupted with reason `recovered_on_open`; `start_session` supersedes a running session even with a living pid; `interrupt_session(id, reason)` marks a running session interrupted and is a no-op on a completed one
- [X] T004 Implement in src/ptlog/store.py: `check_same_thread: bool = True` constructor flag passed to `sqlite3.connect`; `_pid_alive(pid)`; recovery skips sessions owned by a living pid; `interrupt_session(session_id, reason)` inserted before module-level `_ts_key`

## Phase 3: User Story 1 - Record a live session with the real engine (P1) 🎯 MVP

**Goal**: frames processed by the page run the real engine and are recorded; stopping shows the stored summary.

**Independent test**: drive `LiveSession` with synthetic rep cycles; the stored reps equal the tracker's own `ExerciseSession`; the page renders the new controls with the stream stubbed.

- [X] T005 [P] [US1] Write failing tests in tests/test_live_session.py for start and reps: `start()` creates a running session with source `webcam`, the camera label as source_ref, extras `{"camera_id", "imgsz": 320, "frame_skip": 1, "origin": "web", "pid"}`, one set with the chosen `target_reps`; unknown exercise key raises `ValueError`; unknown patient raises `PatientNotFoundError`; None patient records under `unassigned`; three synthetic rep cycles store three reps whose number, ROM, duration, and form score equal `tracker.session.rep_metrics`; `metrics["rep_count"]` equals the stored count; `process()` returns a frame of the same shape and sets `last_frame`
- [X] T006 [P] [US1] Write failing tests in tests/test_live_session.py for partial reps, form events, no person, end: an early reversal stores one partial rep; a stubbed analyzer factory returning a warning assessment stores a throttled form event and sets `metrics["form_status"]` and `metrics["form_messages"]` (max two); frames with no keypoints record nothing and do not raise; `end()` returns a completed `Session` whose total reps, average form, and average ROM equal the tracker's `ExerciseSession`, is idempotent, and `process()` after `end()` returns the frame unchanged
- [X] T007 [P] [US1] Write a failing timing test in tests/test_live_session.py: 300 frames through `process()` with recording on versus a `LiveSession` whose recorder is a no-op; mean difference under 2 ms per frame (FR-011, `draw=False`)
- [X] T008 [US1] Implement `LiveSession` in src/live_session.py per contracts/live-session.md: constructor, `start()`, `process()`, `end()`, properties, internal `threading.Lock`, `infer` returning keypoints or `(keypoints, plotted_frame)`, target-reps override through `dataclasses.replace` on the config
- [X] T009 [P] [US1] Write a failing page test in tests/test_app_pages.py: with `webrtc_streamer` stubbed (not playing), the live page lists the configuration's exercise display names, has Target Reps and Camera controls, has no "Save Session" button, and with `live_session_id` in session state for a completed session shows the summary line and an "Open in Sessions" button that sets `current_page` to `sessions` and `sessions_open` to the id
- [X] T010 [US1] In interfaces/app.py replace `PoseVideoProcessor` and `EXERCISE_CONFIGS` with `LiveVideoProcessor` (lazy `LiveSession` on first frame with `SessionStore(default_db_path(), check_same_thread=False)`, `on_ended` ends it, `error` attribute) and a `_live_exercises()` helper over `analyze.load_config()`
- [X] T011 [US1] Rewrite `page_live_session()` in interfaces/app.py per contracts/page.md for start, playing caption, and stopped summary: set processor attributes, copy `session_id` into `st.session_state["live_session_id"]`, summary from the store, "Open in Sessions", remove Save Session, exercise info from the configuration
- [X] T012 [US1] Run the suite; confirm SC-006 with a grep that interfaces/app.py holds no rep-count state machine; checkpoint commit

## Phase 4: User Story 2 - Switch exercise and reset mid-stream (P2)

**Goal**: switch and reset are recorded the way the command-line keys record them.

**Independent test**: reps, switch, reps, reset, reps, end; the event log shows the order and the reps sit under the right sets.

- [X] T013 [P] [US2] Write failing tests in tests/test_live_session.py: `switch("squat")` mid-movement stores an interrupted partial rep, closes the set, stores a switch event with both exercise names, opens a set with a zero counter; `reset()` stores a reset with the count, keeps the set open, zeroes `metrics["rep_count"]`; a `target_reps` change applies to the set opened by the next switch only; switch to an unknown key raises `ValueError` and leaves the session unchanged
- [X] T014 [US2] Implement `switch()`, `reset()`, and the `target_reps` setter in src/live_session.py
- [X] T015 [P] [US2] Write failing tests in tests/test_live_processor.py for `LiveVideoProcessor` with a fake frame object and injected infer: `request_switch` and `request_reset` are applied on the next `recv`; `recv` before attributes are set passes the frame through
- [X] T016 [US2] Implement `request_switch` / `request_reset` in `LiveVideoProcessor` and the "Switch exercise" and "Reset reps" buttons in `page_live_session()` in interfaces/app.py; extend the page test for the buttons while playing (stub playing with a fake processor)
- [X] T017 [US2] Run the suite; checkpoint commit

## Phase 5: User Story 3 - Interruptions and one open session (P3)

**Goal**: a killed process leaves an interrupted session with its reps; a new stream supersedes an old one; page reruns never interrupt a live stream.

- [X] T018 [P] [US3] Write failing tests in tests/test_live_interrupt.py: a subprocess runs a `LiveSession` for four reps and is SIGKILLed; reopening the store shows the session interrupted with four reps (SC-003); opening a second store in the same process while a `LiveSession` runs leaves it running and `end()` completes it; starting a second `LiveSession` marks the first interrupted with reason `superseded_by_new_session`; 30 seconds of fake clock with no keypoints then `end()` completes normally
- [X] T019 [US3] Make the tests pass: `on_ended` safety in `LiveVideoProcessor`, and in `page_live_session()` interrupt a session still `running` in state when the stream is not playing and no processor holds it (`interrupt_session(id, "stream_lost")`), showing the status in the summary block
- [X] T020 [US3] Run the suite; checkpoint commit

## Phase 6: User Story 4 - Screenshot and cleanup (P4)

- [ ] T021 [P] [US4] Write failing tests in tests/test_live_processor.py: `save_screenshot(frame, "P-017", out_dir, now)` writes `P-017_<YYYYMMDD_HHMMSS>.png` readable by OpenCV with the frame's shape; None frame raises `ValueError`; page test: pressing Save Screenshot while not playing shows "No frame to save"
- [ ] T022 [US4] Implement `save_screenshot` in src/live_session.py and the button in `page_live_session()` in interfaces/app.py (path shown on success)
- [ ] T023 [US4] Run the suite; checkpoint commit

## Phase 7: Polish

- [ ] T024 [P] Add tests/test_live_parity_e2e.py, skipped unless `PTASSIST_E2E=1` and the model and clip exist: `LiveSession` fed every frame of videos/Squats.demo.video.mp4 stores the same reps and partial reps as `analyze.main()` for the clip (SC-001)
- [ ] T025 [P] Add Update 6 to docs/UPDATES.md, a live-session note to README.md, and the adapter to docs/PROJECT_OVERVIEW.md
- [ ] T026 Run quickstart steps 1 and 4 (and step 2 if the model is present); record results in specs/004-live-session-recording/checklists/requirements.md; final commit

## Dependencies

- Phase 2 blocks everything. US1 blocks US2, US3, US4 (they extend `LiveSession` and the page). US2, US3, US4 are independent of each other.
- Parallel: T002 with T003; T005, T006, T007, T009 together (same file for T005–T007: write in one pass); T024 with T025.

## Implementation Strategy

MVP is Phases 1–3 (T001–T012): the page records real sessions. Then US2, US3, US4 in order, a commit per green checkpoint, then polish and merge.
