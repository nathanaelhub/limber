# Research: Live Web Session Recording

**Feature**: 004-live-session-recording | **Date**: 2026-09-20. No NEEDS CLARIFICATION remains.

## D1. An adapter, not a refactor of the engine loop

- **Decision**: `src/live_session.py` implements `LiveSession` with the same per-frame sequence
  as `analyze_webcam()`: infer → keypoints → `get_angle_from_keypoints` → `ExerciseTracker.update`
  → `FormAnalyzer.analyze_frame` → `SessionRecorder.observe` → draw skeleton/angle/panel. It
  calls only public engine functions and classes. `analyze.py` is not edited.
- **Rationale**: constitution I names this exact seam. The browser delivers frames through a
  callback, so a loop cannot be shared anyway.
- **Alternatives considered**: calling `analyze_webcam()` in a thread with a virtual camera
  (no way to feed browser frames into `cv2.VideoCapture`); editing the runner loop to call the
  adapter (engine file edit).

## D2. Inference is injected

- **Decision**: `LiveSession(..., infer=callable)`; the app passes a function wrapping the
  cached YOLO model (`load_pose_model()` with `imgsz=320`), tests pass a fake that returns
  synthetic keypoint arrays or None.
- **Rationale**: tests must not need the model (constitution IV); the adapter's job is the
  engine and recording steps, not detection.

## D3. Synthetic keypoints for tests

- **Decision**: a test helper `keypoints_for_angle(angle)` builds a (17, 3) array with hip,
  knee, and ankle placed so the knee angle equals the requested value (confidence 1.0), so a
  sequence of angles drives the real tracker through real rep cycles. Form events are tested
  with a stubbed analyzer returning a fixed assessment, because the real analyzer's checks
  depend on full-body geometry.

## D4. Threads and the store connection

- **Decision**: `SessionStore(..., check_same_thread=False)` for the live processor, and a
  `threading.Lock` inside `LiveSession` around `process`, `switch`, `reset`, and `end`.
  streamlit-webrtc invokes `recv` on a worker thread and `on_ended` possibly on another;
  SQLite connections default to single-thread use.
- **Rationale**: the lock serialises all store access from the adapter; WAL keeps the app's
  read connections independent.

## D5. Session lifecycle inside the processor

- **Decision**: the page sets `patient_id`, `exercise_key`, `target_reps`, and `camera_label`
  on `ctx.video_processor` before frames flow; the processor creates the `LiveSession` on the
  first `recv` (this is when the session is created, after the model is loaded) and exposes
  `session_id`; switch and reset are request flags consumed inside `recv` so they run on the
  same thread as `process`; `on_ended` calls `end()` under the lock; `end()` is idempotent.
- **Rationale**: keeps every engine and store call on the processor thread; the page never
  touches the tracker.

## D6. Showing the summary after stop

- **Decision**: while `ctx.state.playing` the page copies `processor.session_id` into
  `st.session_state["live_session_id"]`; when not playing and an id is present, the page loads
  the session from the store and shows the summary with a "Open in Sessions" button that sets
  `current_page = "sessions"` and `sessions_open = id`. If `on_ended` did not run (browser
  killed), the next `open()` marks the session interrupted, and the page shows it as such.
- **Rationale**: the processor object may be gone after the stream stops; the record is the
  reliable place to read the result.

## D7. Screenshot

- **Decision**: the processor keeps `last_frame` (annotated BGR); Save Screenshot writes
  `exports/<patient>_<YYYYMMDD_HHMMSS>.png` with OpenCV; not recorded in the exports table.
- **Rationale**: spec assumption; images are not data exports.

## D8. Exercise list and target reps

- **Decision**: the page lists `analyze.load_config()` exercises by display name (mapping to
  keys), replacing the page's hardcoded `EXERCISE_CONFIGS`; `target_reps` overrides the
  config target for the set opened at stream start and for sets opened by a switch after the
  change (the running set keeps its target). Camera choice stays as today; its label is the
  source reference.

## D9. Parity guard

- **Decision**: `tests/test_live_parity_e2e.py` runs only with `PTASSIST_E2E=1`: it feeds every
  frame of `videos/Squats.demo.video.mp4` to a `LiveSession` with the real model and compares
  the stored reps and partials with those `analyze.main()` records for the same clip. It is a
  quickstart step, not part of the default suite.
- **Rationale**: SC-001 with the real engine on real video, without making the default suite
  depend on the model.

## D10. Timing budget

- **Decision**: the unit test measures `process()` over 300 frames with recording enabled and
  with a no-op recorder, on the same fake `infer`; the difference must stay under 2 ms per
  frame (FR-011).

## D11. Recovery must not interrupt a session that is still being recorded

- **Problem found in planning**: `SessionStore.open()` marks every `running` session
  `interrupted`. The web app opens a short-lived store on every page render (sidebar, pages),
  so the first rerun during a stream would interrupt the live session and `end_session` would
  then leave it interrupted instead of completed.
- **Decision**: `LiveSession` writes `"pid": os.getpid()` into the session's `source_extras`.
  Recovery on open skips a running session whose extras carry the pid of a living process
  (`os.kill(pid, 0)` succeeds). Sessions without a pid (command-line runs, imported sessions)
  recover exactly as before. `start_session` still supersedes every running session, pid or
  not, so there is never more than one running session (FR-003).
- **Consequences**: after a killed process the pid is dead, so the next open recovers the
  session (US3 scenario 1). After a closed tab the library's `on_ended` normally ends the
  session as completed; if it never fires, the session stays running until the next stream
  supersedes it or the app restarts. The page also ends a session it still holds in state
  when the stream is not playing (`LiveVideoProcessor` gone), through a new
  `SessionStore.interrupt_session(session_id, reason)`.
- **Alternatives considered**: a heartbeat column (schema change, more writes per frame); an
  `open(recover=False)` flag for the app (does not protect against the command-line tool
  opening the record during a stream); an in-process registry (same gap).
- **No schema change**: the pid lives in the existing JSON extras column; no export reads it.
