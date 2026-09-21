# Implementation Plan: Online Patient View

**Branch**: `007-online-patient-view` | **Date**: 2026-09-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/007-online-patient-view/spec.md`

## Summary

A separate patient service (Starlette on uvicorn, already installed with Streamlit) serves four
thin pages and a small JSON API, plus one WebSocket. The patient's browser runs MoveNet on the
camera and sends 17 body points per frame at 15 Hz; the service feeds them to the existing
`LiveSession` adapter through its injected `infer`, so the clinic's engine and recording path are
reused unchanged. Access is by therapist-issued codes stored as keyed hashes, with revocable
server-side sign-ins, rate limits, origin checks, and an access history. Schema v6 adds the three
access tables. Because the browser's pose model measures range of motion differently from the
clinic's (research D2), sessions get a capture origin (clinic or home) and every comparison across
sessions is made within one origin.

## Technical Context

**Language/Version**: Python 3.13 (`.venv`); browser JavaScript (no build step, no Node toolchain).

**Primary Dependencies**: Starlette 1.6, uvicorn 0.52, websockets 16, httpx 0.28 (test client),
all already installed as Streamlit dependencies and now used directly. Browser: TensorFlow.js
4.22 and pose-detection 2.1.3 with MoveNet SinglePose Lightning v4 (Apache-2.0), fetched by a
script into a gitignored folder.

**Storage**: SQLite schema v6 (`portal_access`, `portal_sessions`, `portal_audit`); server key in
`data/portal.key`.

**Testing**: pytest; Starlette `TestClient` for HTTP and WebSocket in-process; synthetic body
points from `tests/fixtures/poses.py`; no network, camera, model, or browser in the suite. Browser
behaviour is checked by the quickstart and a scripted fake-camera run kept outside the repo.

**Target Platform**: service on macOS/Linux; patients on a current Chrome, Safari, or Edge.

**Project Type**: single Python project; third interface surface (constitution 1.1.0).

**Performance Goals**: accept 15 frames per second per patient and answer state changes within
200 ms on one machine; 8 concurrent home sessions.

**Constraints**: engine untouched; camera video never leaves the device; only the signed-in
patient's data is served; study participants only.

**Scale/Scope**: tens of patients, a handful concurrent.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine is a dependency | PASS | `analyze.py`, `src/form_assessment.py`, `src/utils.py`, `config.yaml` untouched. The portal reuses the `LiveSession` adapter; the only adapter change is an optional `extras` argument and an `interrupt()` helper. Body points are scaled uniformly before the engine sees them, which changes no angle. |
| II. One canonical record | PASS | `SessionStore` stays the only writer, including the three new tables; schema v6 is forward-only. Home sessions are ordinary sessions. |
| III. Local-first, privacy (1.1.0) | PASS | The spec carries the networked-feature check: what is sent, what never is, who may use it, off until a code is issued, only the patient's own data, video stays on the device. Pose assets are served by the service itself, not by third parties. |
| IV. Test-first | PASS | Every task pair is test then code; the suite needs no network, camera, model, or browser. |
| V. Simplicity, readability | PASS with tracking | No new Python package is installed; see Complexity Tracking for the direct use of Streamlit's dependencies and for the browser assets. Every number shown to a patient comes with its unit and definition from `METRIC_DEFINITIONS`. |
| Interface rule (1.1.0) | PASS | Logic lives in `src/portal/`; `interfaces/patient_portal.py` only routes and renders; browser JavaScript holds no clinical logic. |

Post-design re-check: PASS.

## Project Structure

```text
specs/007-online-patient-view/
├── plan.md  research.md  data-model.md  quickstart.md  tasks.md
└── contracts/  http-api.md  websocket.md  cli-and-therapist.md

src/portal/
├── __init__.py
├── access.py        # code generation and normalisation, keyed lookup hash, expiry rules, login limiter, key file
├── viewmodels.py    # today_view, progress_view, adherence_view, streak (pure; patient's own data only)
├── frames.py        # validate_frame, to_engine_keypoints (uniform scale to 720), RateMeter
└── live.py          # PortalLiveSession (wraps LiveSession), live-session registry

src/ptlog/origin.py  # capture_origin(session) -> "clinic" | "home"; split helpers used by review, flags, tracker
src/ptlog/store.py   # schema v6, portal methods, same-patient supersede
src/ptlog/measures.py, review.py, tracker.py, views.py, exports/   # origin on measures; comparisons within one origin
src/live_session.py  # optional extras; interrupt(reason)

interfaces/patient_portal.py      # Starlette app factory, routes, security headers, main()
interfaces/portal_static/         # index.html today.html session.html progress.html portal.css portal.js session.js
interfaces/portal_static/vendor/  # gitignored; filled by scripts/fetch_portal_assets.py
interfaces/cli.py                 # portal code create|list|revoke, portal audit, portal serve
interfaces/app.py                 # Patients page: Home access block; origin shown where sessions are listed
scripts/fetch_portal_assets.py    # pinned URLs + SHA-256
scripts/seed_demo.py              # a few home sessions and one demo code

tests/test_portal_access.py  test_portal_store.py  test_portal_viewmodels.py  test_portal_frames.py
tests/test_portal_live.py  test_portal_http.py  test_portal_ws.py  test_cli_portal.py
tests/test_ptlog_origin.py   (+ additions to review, flags, tracker, exports, app page tests)
```

**Structure Decision**: `src/portal/` is separate from `src/ptlog/` because it depends on the
live adapter (and therefore on the engine), while `ptlog` must stay importable without it. The
origin split lives in `ptlog` because the therapist's views need it too.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|------|------------|-------------------------------------|
| Direct use of Starlette, uvicorn, websockets, httpx (pinned in `requirements.txt`) | An internet-facing service needs routing, cookies, WebSockets, TLS flags, and an in-process test client | A hand-written HTTP and WebSocket server on the standard library would be security-critical code we would have to maintain; Streamlit cannot run pose detection in the patient's browser or hide therapist pages |
| Browser assets (TensorFlow.js, pose-detection, MoveNet weights, about 6 MB) fetched by script | Pose detection must run on the patient's device (constitution III) | Loading them from a CDN would show every participant's address to third parties and weaken the content security policy; committing binaries would bloat the repository |
| A second pose model alongside YOLO | The clinic model cannot run in a phone browser | Streaming video to the server was rejected by the owner and by constitution III; the measured difference is contained by the origin split (FR-020) |
| Origin split touches features 002, 003, 005 code | Mixing home and clinic range of motion would raise false flags (research D2) | Labelling alone would leave the ROM rules wrong; excluding home sessions from review would hide home practice from the therapist |
| Change to feature 004's rule (one running session per patient) | Two people must be able to exercise at once | Keeping one per installation would corrupt sessions as soon as two patients are active |
