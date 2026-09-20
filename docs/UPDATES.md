# PT Assist — Project Updates

---

## Update 5 — 2026-09-20 — Multi-Patient PT Tracker

Feature spec: `specs/003-pt-tracker/`. Reads from the canonical record and the review feature;
nothing about recording changed. Schema moved to version 3 (`assignments`, `discharges`,
`tracker_settings`), applied automatically on first open.

### 1. Roster

`tracker roster [--sort attention|id] [--program ID] [--needs-attention]` lists every active
patient with: program and its status, days since the last session, sessions in the last 7 and 30
days, adherence over the last four complete assignment weeks, pending reviews, open attention
flags (last 30 days), a practice-gap marker, and the next step from the most recent review. The
attention sort puts more flags, then more pending reviews, then lower adherence, then the longest
absence first.

### 2. Programs and assignment

`tracker programs` lists the four pre-built programs from `config.yaml`; `tracker assign
<patient> --program knee_rehab | --exercises k1,k2 [--per-week 3] [--start DATE] [--end DATE]`
assigns one (or a custom list of exercise keys). A patient has one active assignment; a new one
ends the previous one the day before it starts, and `tracker assignments <patient>` shows the
history with statuses (scheduled, active, completed, superseded).

### 3. Adherence

`tracker adherence <patient>` shows seven-day assignment weeks from the start date: sessions
recorded against planned (a session counts once, and only with a counted rep), which assigned
exercises were performed, missed weeks, the current week in progress, and the percentage over
the last four complete weeks, capped per week.

### 4. Queue and threshold

`tracker queue` lists everything needing action across active patients, oldest first within each
kind: pending reviews, attention flags, practice gaps, and adherence below the threshold
(`tracker settings --adherence-threshold 60`). There is no acknowledgement state; items leave
when the underlying condition is resolved.

### 5. Discharge and export

`tracker discharge <patient> [--on DATE] [--reason …]` removes a patient from the roster and queue
while keeping every session, review, goal, and assignment; `tracker reactivate` brings them back;
`tracker discharged` lists them. `tracker export-roster` writes `roster_<time>.csv`.

### 6. Web app

A Tracker page (Roster, Queue, Adherence, Discharged, Export) and, on the Patients page, a
program assignment form with history and a discharge control.

---

## Update 4 — 2026-09-19 — Review Over Time

Feature spec: `specs/002-review-over-time/`. Everything reads from the canonical session record;
nothing about recording changed.

### 1. Per-session measures

For every session and exercise: reps completed against target, average range of motion (°),
average form score (0-100), average rep duration (s), tempo consistency (population standard
deviation of rep durations, s), partial-rep share (%), safety stops, and an interrupted marker.
Several sets of one exercise in a session combine into one point. Measures are derived on request
and never stored.

### 2. Trends, comparison, goals

```
python interfaces/cli.py review trends P-017 --exercise "Knee Extension" --period 30d
python interfaces/cli.py review compare 12 15
python interfaces/cli.py review goal set P-017 --exercise "Knee Extension" --rom 120 --reps 10
python interfaces/cli.py review goals P-017 | review goal clear ...
```

Periods: `14d`, `30d`, `90d`, `all`. A trend shows first → latest → change per measure and the
progress toward a range-of-motion goal (capped at 100%). A comparison shows both values, the change,
the percentage change for reps, form, and ROM, and which direction counts as improvement.

### 3. Attention flags with evidence

`review flags P-017 [--period …]` evaluates seven explicit rules and shows the sessions and values
behind each flag: form declining (over the last four sessions), range-of-motion regression (≥ 10°
below the best of the previous three), range-of-motion plateau (< 3° change while below a goal),
target reps not reached (three sessions in a row), rising partial reps (≥ 25% and ≥ 10 points above
the previous three), safety stop (any stop-severity form event), and practice gap (more than the
patient's threshold, `review settings P-017 --gap-days 7`). Rules without enough sessions are listed
as "not evaluated yet".

### 4. Session reviews

```
python interfaces/cli.py review pending P-017
python interfaces/cli.py review session 12
python interfaces/cli.py review mark 12 --next-step progress --notes "post-op week 3"
```

One review per session (edits replace it): reviewed time, free-text notes (names, dates of birth, and
record numbers are rejected), and a next step of continue, progress, regress, or hold. The session view
includes the per-session summary flags from the existing single-session analysis.

### 5. Review summary exports

`review export P-017 --period all --format all` writes a text report and a CSV named
`{patient}_review_{period}_{time}` under `exports/`, covering trends per exercise, flags with evidence,
goals with progress, and every session's review status, notes, and next step. Both are removed when the
patient is deleted.

### 6. Web app and retired code

The Review page (Trends, Flags, Compare, Session review, Goals & settings, Export) replaces the
Progress Report and PT Summary pages. The `progress` CLI command and `src/session_tracker.py` were
retired; the schema moved to version 2 (`reviews`, `goals`, `review_settings`, `review_exports`),
applied automatically on first open.

---

## Update 3 — 2026-09-14 — Unified PT Session Log

Feature spec: `specs/001-unified-session-log/` (built with GitHub Spec Kit under the project
constitution in `.specify/memory/constitution.md`).

### 1. One canonical session record (`src/ptlog/`)

Every session is now written once, by one writer, into a local SQLite file at
`data/ptassist.db` (override with the `PTASSIST_DB` environment variable). The record holds
patients, sessions, exercise sets, completed reps, partial reps, form feedback events,
exercise switches, counter resets, and downsampled angle samples. Every event is committed
as it happens, so a crash or camera loss loses at most the last second; a session left
open by an interruption is marked `interrupted` on the next start and its summary is
computed from the events that were recorded.

- `SessionStore` — schema, forward-only migrations, single writer, all reads
- `SessionRecorder` — the only engine-facing adapter; reads the tracker's public outputs and
  never touches thresholds, the state machine, or form checks
- `views` — unit-labelled rendering shared by the CLI and web app, plus the bridge that
  feeds the existing trend math in `src/session_tracker.py`
- Every metric has a unit and a plain-language definition (`METRIC_DEFINITIONS`)

### 2. Retired writers

The four legacy loggers and the per-session report writer no longer run:
`SessionLogger` (numbered text logs), `PTARawLogger` (PTA-Log pipe text),
`ObservationLogger` (observation JSON), `SessionTracker` file persistence, and
`generate_session_report`. A session run now creates **no files** in `logs/`, `pta_logs/`,
`observation_logs/`, or `sessions/`. `SessionTracker` keeps only its analysis methods.

### 3. Exports (legacy formats, byte for byte)

Any session can be exported in the four legacy layouts, each generated from the record and
verified against golden files produced by the original writers:
PTA-Log text (`.txt`), observation JSON (`.json`), CSV report (`.csv`), and the plain-text
session log (`.log`, 50-line files). Files are named `{patient_id}_{start}.{ext}` under
`exports/` and are removed when their patient is deleted.

### 4. Pseudonymous patients

```
python interfaces/cli.py patients add P-017 --label "Post-op knee"
python interfaces/cli.py patients list | edit | delete | reassign
python analyze.py video --input clip.mp4 --exercise squat --patient P-017
python analyze.py webcam --exercise squat --patient P-017
```

IDs are 1-32 letters, digits, or hyphens. IDs and labels that look like a name, a date, or
a record number are rejected. Sessions recorded without `--patient` go to the built-in
`unassigned` patient and can be reassigned later. Deleting a patient removes every session,
event, and export file tied to it.

### 5. Browsing and exporting

```
python interfaces/cli.py sessions list [--patient P-017] [--json]
python interfaces/cli.py sessions show 3 [--json]
python interfaces/cli.py export 3 --format all|pta_log|observation_json|csv_report|text_log [--out DIR]
```

Web app: new **Patients** and **Sessions** pages, a real patient selector in the sidebar,
export download buttons on the session detail, and the Dashboard, Observation Logs,
PT Summary, and Progress Report pages now read from the record. The file-based
Session Logs page was removed. The `report` and `history` CLI commands were replaced by
`sessions list` / `sessions show`.

### 6. One-time import of old files

```
python interfaces/cli.py import-legacy [--sessions-dir sessions] [--obs-dir observation_logs] [--dry-run]
```

Reads the three legacy JSON shapes (per-session report, observation log, session-tracker
record), skips CSV/text files, reports malformed files by name, and never creates
duplicates: a SHA-256 ledger makes repeat runs no-ops, and the same session saved in both
folders is imported once. Files are left in place.

### 7. Tests

`tests/test_ptlog_*.py`, `tests/test_cli_ptlog.py`, and `tests/test_app_pages.py` (headless
Streamlit) cover the record, recorder, crash recovery (including a SIGKILL test), patients,
views, exports, import, CLI, and web pages. Run `.venv/bin/python -m pytest tests`.

---

## Update 2 — 2026-02-21

### 1. Timestamped Session Log Files (`analyze.py`)

Added a `SessionLogger` class that writes structured, timestamped text logs to a `logs/` directory.

- **Auto-numbered files**: `logfile-01.log`, `logfile-02.log`, etc. Each new session always gets the next available number.
- **50-line cap per file**: When a file reaches 50 lines, the logger automatically rolls over to the next numbered file and writes a continuation header.
- **Timestamps on every entry**: Each line is prefixed with `[HH:MM:SS]`. The file header records the full `YYYY-MM-DD HH:MM:SS` creation time.
- **Session lifecycle events logged**:
  - `SESSION START` — exercise name, camera ID, imgsz, frame_skip
  - `REP N` — ROM, form score, duration, angle range per completed rep
  - `FORM WARNING/POOR/STOP` — form analyzer feedback (throttled to ~every 2 s)
  - `SWITCH` — exercise transitions via `n` key
  - `RESET` — rep counter reset via `r` key
  - `SESSION END` — written automatically on quit (`q`) or app exit, with total reps, avg form, avg ROM

**Usage:**
```
logs/
  logfile-01.log
  logfile-02.log
  ...
```

**Log entry examples:**
```
# logfile created: 2026-02-21 12:34:56
[12:34:56] SESSION START | Exercise: Elbow Flexion | Camera: 0 | imgsz: 320 | skip: 1
[12:35:02] REP 1 | ROM: 79.3° | Form: 88% | Duration: 2.1s | Angle: 91°-170°
[12:35:15] FORM WARNING | Keep your back straight against the chair
[12:35:30] SESSION END | Total Reps: 5 | Avg Form: 85% | Avg ROM: 76.4°
```

---

### 2. Camera FPS Improvement (`analyze.py`)

- **`imgsz` parameter** (default `320`): YOLO inference image size. Reduced from 640 → 320 gives ~4× throughput improvement with minimal accuracy loss for PT tracking distances.
- **`frame_skip` parameter** (default `1`): Run YOLO every Nth frame. On skipped frames the raw camera image is shown with the last known pose/angle overlaid. Motion stays smooth; YOLO skeleton updates at the reduced rate.
- **CLI flags added:**
  ```
  python analyze.py webcam --exercise elbow_flexion --camera 0 --imgsz 320 --skip-frames 2
  ```

---

### 3. Annotated Video Download — Web App (`interfaces/app.py`)

The **🎬 Video Analysis** page now runs real YOLO pose analysis instead of a fake progress simulation:

- Calls `analyze_video()` (the `main()` function from `analyze.py`) with `show_video=False`
- Annotated output video is saved to a temp file, displayed inline with `st.video()`, and available for download
- Results (reps, form score, ROM, per-rep table) come from the real `ExerciseSession` object
- Report JSON download reflects actual analysis data

---

### 4. Session Log Analysis Page — Web App (`interfaces/app.py`)

New **📋 Session Logs** page added to the sidebar:

- Dropdown to select any saved session JSON from `sessions/`
- Summary metrics: reps completed, avg form score, avg ROM, tempo consistency σ
- Charts: ROM per rep (bar), form score per rep (line), angle range per rep (area)
- Rep details table
- Recommendations from session analysis
- **Raw Logs viewer**: browse `logfile-XX.log` files from the `logs/` directory, view content inline, download individual log files

---

### 5. Idle/Mid-Movement Phase Detection (`analyze.py`)

Added a fourth exercise phase state to the `ExerciseTracker` state machine:

| State | Condition | Panel Color |
|-------|-----------|-------------|
| `UP` | Angle reached the up threshold ± tolerance | Green |
| `DOWN` | Angle reached the down threshold ± tolerance | Yellow |
| `IDLE` | Angle is between both thresholds (mid-movement) | Orange |
| `NEUTRAL` | Initial state, no movement detected yet | White |

- Rep counting uses a `last_peak_state` tracker so idle frames do not interfere with rep detection — a rep still counts when transitioning `UP → (IDLE) → DOWN` or `DOWN → (IDLE) → UP`
- The panel "Phase:" indicator displays `IDLE` in orange for easy identification

---

### 6. FormAnalyzer Wired into Webcam + Improved Panel (`analyze.py`)

- `FormAnalyzer` (from `src/form_assessment.py`) now runs on every inference frame in `analyze_webcam()`
- Right panel additions:
  - **Status** line: `EXCELLENT` / `GOOD` / `WARNING` / `POOR` / `STOP` with matching color
  - **Feedback messages**: up to 2 exercise-specific cues (trunk lean, hip hike, shoulder shrug, knee valgus, etc.)
- `r` key resets the FormAnalyzer alongside the tracker
- `n` key reinitializes FormAnalyzer for the new exercise type

---

## Update 1 — Initial Build

- YOLO11 pose estimation with `yolo11m-pose.pt`
- Rep counting state machine (UP / DOWN)
- Per-rep form scoring: ROM achievement (40%), smoothness (30%), phase symmetry (30%)
- Exercise configs in `config.yaml` (knee extension, shoulder flexion, squat, hip abduction, elbow flexion, push-up, trunk flexion, hip abduction, seated hip flexion)
- CLI: `python analyze.py webcam / video / image / aigym`
- Streamlit web app: Dashboard, Live Session (WebRTC), Video Analysis, Progress Report, How It Works
- Session export: JSON + CSV to `sessions/`
- `FormAnalyzer` in `src/form_assessment.py`: alignment, compensation detection, symmetry, fatigue tracking, exercise-specific checks
