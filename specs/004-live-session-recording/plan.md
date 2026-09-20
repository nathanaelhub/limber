# Implementation Plan: Live Web Session Recording

**Branch**: `004-live-session-recording` | **Date**: 2026-09-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-live-session-recording/spec.md`

## Summary

Replace the live-session page's private rep counter with a small engine-facing adapter,
`LiveSession`, that runs the same per-frame steps as the command-line webcam loop (engine
tracker with smoothing, form analyzer, recorder, panel drawing) and records into the canonical
record through `SessionRecorder`. A new WebRTC processor drives `LiveSession` from the browser
stream, applies switch and reset requests inside the frame callback, ends the session when the
stream stops, and keeps the last annotated frame for screenshots. No schema change; the
engine file is not edited.

## Technical Context

**Language/Version**: Python 3.13 (repo venv `.venv`)

**Primary Dependencies**: already installed: streamlit-webrtc 0.77 (`recv` / `on_ended`
callbacks), av, ultralytics, OpenCV; `src/ptlog` for recording.

**Storage**: none new; sessions land in the existing record. `SessionStore` gains a
`check_same_thread` option because the WebRTC processor's callbacks run on worker threads, and
recovery on open learns to leave alone a running session owned by a living process (research D11),
because the app opens the record on every page render.

**Testing**: pytest; `LiveSession` driven by a fake `infer` producing synthetic 17-keypoint
arrays; page render test with the WebRTC component stubbed; an end-to-end parity check on
`videos/Squats.demo.video.mp4` gated by `PTASSIST_E2E=1` (needs the model).

**Target Platform**: macOS/Linux desktop, one browser tab, local.

**Project Type**: single Python project with CLI and Streamlit interface.

**Performance Goals**: recording adds at most 2 ms per processed frame on average over a
300-frame run (SC-004, FR-011); the stream keeps its current frame rate.

**Constraints**: engine untouched (constitution I); one recording path (constitution II);
pseudonymous only (constitution III).

**Scale/Scope**: one stream at a time; sessions of minutes; a few hundred events.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine is a dependency | PASS | `analyze.py` is not edited. `LiveSession` is the "small, documented adapter in src/" the principle asks for, consuming `ExerciseTracker`, `FormAnalyzer`, `get_angle_from_keypoints`, and the two draw helpers through their public surfaces. The page's own counter is deleted, removing a duplicate of engine logic. |
| II. One canonical record | PASS | Recording goes through `SessionRecorder` and `SessionStore` only; no new tables or writers. |
| III. Local-first, privacy | PASS | Screenshots are named `<pseudonymous id>_<time>.png` under `exports/`; nothing leaves the machine. |
| IV. Test-first | PASS | `tests/test_live_session.py` and the page test are written first; no test needs a camera, the network, or the model (the parity run is opt-in and part of the quickstart). Engine tests untouched. |
| V. Simplicity, readability | PASS | No new dependencies; the panel reuses the engine's labels; `docs/UPDATES.md` entry required. |
| Sequencing rule | PASS | Depends on 001 (recorder), merged. |

Post-design re-check (after Phase 1): PASS. One accepted duplication is recorded in
Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/004-live-session-recording/
├── plan.md
├── research.md
├── data-model.md            # runtime entities only; no schema change
├── quickstart.md
├── contracts/
│   ├── live-session.md      # LiveSession and LiveVideoProcessor API
│   └── page.md              # live-session page controls and states
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/live_session.py          # NEW: LiveSession adapter (engine + recorder per frame, switch, reset, end, screenshot frame)
src/ptlog/store.py           # + check_same_thread flag; recovery skips sessions owned by a living pid; interrupt_session()
interfaces/app.py            # PoseVideoProcessor → LiveVideoProcessor; live page: session id in state,
                             #   summary on stop with link, screenshot to exports/, Save Session removed,
                             #   exercise list from analyze.load_config
tests/
├── test_live_session.py     # fake-infer driven: reps, partials, form events, switch, reset, end, recovery, timing
├── test_app_pages.py        # + live page render with webrtc_streamer stubbed
└── test_live_parity_e2e.py  # opt-in (PTASSIST_E2E=1): LiveSession vs analyze.main on the sample clip
```

**Structure Decision**: the adapter lives beside the engine in `src/` (not inside `ptlog`)
because it imports ultralytics-dependent code; `ptlog` stays importable without the model
stack.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| The per-frame runner logic now exists twice: in `analyze_webcam()` and in `LiveSession.process()` | Constitution I forbids editing the engine file's control flow, and the browser stream delivers frames through a callback rather than a capture loop | Refactoring `analyze_webcam()` to call `LiveSession` would edit the runner loop; a parity test (unit level with synthetic keypoints, plus the opt-in clip run) guards the two copies against drift |
