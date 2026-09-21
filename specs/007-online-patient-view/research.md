# Research: Online Patient View

**Feature**: 007-online-patient-view | **Date**: 2026-09-21. No NEEDS CLARIFICATION remains.
The two experiments below were run with throwaway scripts outside the repository (YOLO body points
cached once per clip; MoveNet run in headless Chrome by stepping through each clip frame by frame;
both replayed through the real `LiveSession`). Sample: `videos/Squats.demo.video.mp4` (222 frames)
and `videos/Pushups.demo.video.mp4` (254 frames), four reps each. It is a small sample without
ground truth.

## D1. Frame rate: nominal 15 Hz, floor 12 Hz

Clinic model body points replayed at full and reduced rates:

| Clip | Rate | Reps | Avg ROM | Avg form | Avg rep duration | Form events |
|------|------|------|---------|----------|------------------|-------------|
| Squat | 30 Hz | 4 | 117.3° | 67.5 | 1.58 s | 1 |
| Squat | 15 Hz | 4 | 117.5° | 66.2 | 1.61 s | 1 |
| Squat | 10 Hz | 4 | 110.4° | 64.4 | 1.65 s | 1 |
| Push-up | 30 Hz | 4 | 84.9° | 67.7 | 1.76 s | 4 |
| Push-up | 15 Hz | 4 | 82.6° | 65.9 | 1.80 s | 3 |
| Push-up | 10 Hz | 4 | 80.6° | 66.1 | 1.82 s | 2 |

- **Decision**: the browser sends at a steady 15 Hz; the service builds `LiveSession(fps=15)` and
  ticks the engine once per accepted message, using its own frame counter. Below 12 Hz for five
  seconds the patient is told and the session is tagged `low_rate`. No interpolation (it would
  invent data and inflate the smoothness score).
- **Why the rate matters**: the engine's rep duration is frames divided by fps, its smoothing is a
  5-frame mean, and the smoothness part of the form score uses per-frame differences.
- **Finding for a later spec**: the therapist's web Live Session passes `fps=30` whatever the real
  rate is, so its durations are mis-scaled when the machine is slow. Not changed here.

## D2. Browser pose model: MoveNet Lightning; home and clinic are kept apart

| Clip | Model | Reps 30/15 Hz | Avg ROM 30 Hz | Avg form 30 Hz | Angle vs clinic model (mean, p95) |
|------|-------|---------------|---------------|----------------|-----------------------------------|
| Squat | YOLO11m (clinic) | 4 / 4 | 117.3° | 67.5 | - |
| Squat | MoveNet Lightning | 4 / 4 | 111.9° | 68.1 | 6.0°, 12.5° |
| Squat | MoveNet Thunder | 4 / 4 | 114.7° | 68.3 | 5.3°, 12.5° |
| Push-up | YOLO11m (clinic) | 4 / 4 | 84.9° | 67.7 | - |
| Push-up | MoveNet Lightning | 4 / 4 | 98.0° | 69.5 | 6.6°, 15.3° |
| Push-up | MoveNet Thunder | 4 / 4 | 108.9° | 69.8 | 8.8°, 19.1° |

- Rep counts, rep durations, and form scores agree. **Range of motion does not**: 3° to 6° lower
  on squats, 13° to 24° higher on push-ups. Without ground truth this shows disagreement, not
  which model is right. MoveNet produced an angle on every frame but one, so the 0.3 confidence
  gate is not a problem on these clips.
- **Decision**: Lightning by default (closer on push-ups, lighter on phones), `enableSmoothing`
  off (the engine already smooths), single pose, no flip before inference.
- **Decision (FR-020)**: sessions carry a capture origin, `home` when `source_extras.origin` is
  `portal`, otherwise `clinic`. Trends, changes, goal progress, comparison, and every attention
  rule that compares sessions run per origin. Adherence, done-today, pending reviews, and the
  practice gap count all sessions.
- **Rejected**: requiring ROM within 5° (not achievable); running the clinic model in the browser
  through ONNX (heavier, AGPL weights shipped to browsers, and a smaller YOLO would differ too);
  a per-model correction factor (no ground truth to fit it, and it would hide the uncertainty).

## D3. Server stack: Starlette on uvicorn

Streamlit 1.63 installs Starlette, uvicorn, websockets, itsdangerous, and httpx. Tornado and
aiohttp are not installed. Starlette gives routing, static files, WebSockets, and a synchronous
`TestClient` with WebSocket support, verified in this venv. FastAPI would add pydantic for no
gain. Store calls run through `run_in_threadpool` because writes use `synchronous=FULL`.

## D4. Access codes and sign-ins

- 12 characters of Crockford base32 (no I, L, O, U) from `secrets`, shown `XXXX-XXXX-XXXX`: 60 bits.
  Input is normalised (case, spaces, dashes, O→0, I/L→1).
- Stored as `HMAC-SHA256(server_key, normalised_code)` in a unique column: sign-in needs the code
  only, lookup is direct, and patient IDs cannot be enumerated. For a random 60-bit secret a keyed
  hash is the right control; a slow password hash adds little.
- Server key: 32 random bytes in `data/portal.key` (mode 0600; `data/` is gitignored) or
  `PTASSIST_PORTAL_KEY`. Keeping it outside the database protects the hashes if the database leaks.
- Sign-in: opaque 32-byte token in a cookie (`HttpOnly`, `SameSite=Strict`, `Secure` under TLS);
  the server stores its SHA-256. Idle limit 30 minutes, absolute limit 12 hours, at most three per
  patient. Server-side so that revoking a code ends sign-ins at once.
- Limiter: in memory with an injected clock; five failures per fifteen minutes per client, then
  doubling lock-out; a global breaker at thirty failures per minute. Behind a tunnel every client
  looks local, so `--trust-proxy` reads the forwarded address; otherwise only the global breaker
  applies, which the quickstart states.
- Access history stores `HMAC(server_key, address)[:16]`, never the address or the code.

## D5. Request safety

`SameSite=Strict` plus an Origin allow-list (localhost and each `--public-origin`) on every POST
and on the WebSocket handshake; JSON bodies only. No route, query, or message carries a patient
ID. Headers: a content security policy of `default-src 'self'` with `script-src 'self'
'wasm-unsafe-eval'`, `connect-src 'self'`, `img-src 'self' data: blob:`, `media-src 'self' blob:`,
`worker-src 'self' blob:`, `frame-ancestors 'none'`; `Permissions-Policy: camera=(self)`;
`nosniff`; `no-referrer`; `no-store` on the API. Whether the WebGL backend needs more than
`wasm-unsafe-eval` is checked in the quickstart's browser run.

## D6. Frames and coordinates

The engine expects 17 rows of x, y in pixels (origin top-left) and a confidence, and drops points
under 0.3. Several form checks use absolute pixel distances tuned near 720p, so the service scales
x and y by one factor, `720 / frame height`, which leaves every angle unchanged. The message is
`{"type":"frame","k":[51 numbers],"w":W,"h":H}`; points slightly outside the frame are clamped,
not rejected; messages over 4 KB, wrong shapes, and non-finite numbers are rejected. The client's
time and frame numbers are ignored.

## D7. Live session lifecycle

`PortalLiveSession` wraps `LiveSession(store, patient, first_key, target, "home", infer, fps=15,
draw=False, extras={origin: portal, pose_model, fps_nominal})`. `next` calls `set_target_reps`
then `switch`. Stop ends as completed. Disconnect, revocation, sixty idle seconds, or sixty
minutes end it; disconnect and revocation mark it interrupted through a new
`LiveSession.interrupt(reason)` that flushes the recorder first. A registry allows one home
session per patient and eight in total. `start_session` supersedes only the same patient's
running sessions.

## D8. Pose assets

`scripts/fetch_portal_assets.py` downloads pinned files (jsDelivr for the four libraries, the
model manifest and two weight shards from TensorFlow Hub) and verifies SHA-256 before writing to
`interfaces/portal_static/vendor/` (gitignored). The hashes measured on 2026-09-21 are recorded in
the script. Without the assets the service starts, prints the command to run, and the session page
says setup is incomplete.

## D9. Reaching it from a phone

Browsers allow the camera only on HTTPS or localhost, and iOS refuses WebSockets over untrusted
certificates. Supported paths: this machine (localhost); a temporary HTTPS tunnel with
`--public-origin` and `--trust-proxy` (recommended; the tunnel operator can see body-point numbers
in transit, which the study's consent text should mention); or a locally trusted certificate
through `--certfile` and `--keyfile`.

## D10. Known costs

The service imports `analyze.py`, which imports Ultralytics and torch: several seconds of start-up
and a few hundred megabytes, acceptable on one machine. Ultralytics is AGPL; ask the university
before public hosting. Starlette's `TestClient` warns that httpx support is deprecated; no pytest
setting turns warnings into errors, and the pins note it.
