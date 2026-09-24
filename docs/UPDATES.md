# PT Assist — Project Updates

---

## Update 15 — 2026-09-24 — Questionnaires: an Engine, Not a Form

Feature spec: `specs/013-questionnaires/`. Schema moved to version 12 (`instrument_assignments`);
nothing was rebuilt, because `entries.kind` has allowed `questionnaire` since version 9.

- **An instrument is a file, not code.** Each questionnaire is one YAML file in `instruments/` beside
  `config.yaml`: its name, what its score means, the unit, whether higher is better or worse, the items
  with their choices and values, which items are reversed, the subscales, `sum` or `mean`, and the rule
  for missing answers. Adding one needs no code change and no restart. A file with a mistake in it is
  named in the therapist's view with the problem and skipped; the other instruments still work, and so
  does the app with no instruments at all. Definitions are parsed safely and never executed, and an
  instrument may not ask for a name, a date of birth, or a record number.
- **Therapist**: assign an instrument to a patient once, weekly, fortnightly, or monthly; see the next
  due date; end an assignment (the answers stay). Review → From the patient shows each instrument's
  scores over time with its unit, direction, meaning, and subscale scores, the change from first to
  latest, and the item answers of any one questionnaire, marking a reversed question as such. More than
  a week past due reaches the work queue and marks the roster.
- **Patient**: what is due appears on Today. The questions are answered on one page, each with its own
  words rather than bare numbers; a half-finished questionnaire is kept on the phone, so an interruption
  costs nothing; and a finished one goes through the same offline queue as a check-in. On sending, the
  patient sees their total, its unit, and which direction is better.
- **A stored score never moves.** Each answer set is stored with a snapshot of the values, ranges,
  reversals, subscales, and rules that produced its total, so any score can be reproduced years later
  even if the file has since been edited or deleted. When the installed definition differs, the
  therapist is told which version each score came from rather than being shown a new number.
- **Scoring is arithmetic, not judgement.** No attention flag or threshold is derived from a
  questionnaire score, and the sentence saying what a score means comes from the file.
- **The one shipped instrument is a demonstration.** "Demo Knee Function" (ten questions, two reversed,
  two subscales) was written for this project and says so wherever its score appears. Real instruments
  and their licences are the owner's to source; each is then one more file.
- Verified on an emulated iPhone in Chrome against the demo record, and in the therapist app. Not
  verified: a real phone, a real instrument, and how long a twenty-item questionnaire feels to answer.

---

## Update 14 — 2026-09-24 — Exercise Logged Without the Camera, Medication and Sleep

Feature spec: `specs/012-diary-logs/`. Schema moved to version 11: the `sessions` table was rebuilt so
its source may be `diary`, `exercise_sets` gained reported reps, sets, and effort, and
`patient_settings` holds the per-patient switch and medication list. A test upgrades a realistic
version 10 record and compares every table's row count; only `schema_version` grows.

- **A third capture origin.** Sessions are now recorded in the clinic, at home, or **self-reported**.
  Self-reported sessions count everywhere "did they practise" is the question — done today, sessions
  this week, the streak, adherence, the practice gap, the roster, the patient's history — and are
  excluded everywhere a measurement is compared: trends, first-to-latest change, goal progress,
  session comparison, and every attention rule. They carry no angles, so they have no range of motion,
  no form score, and no duration. A trend with nothing to show now says how many sessions were logged
  rather than that nothing happened.
- **Patient**: "I did this without the camera" on Today. Exercise (their program first, then the rest
  of the configuration), reps 1-200, sets 1-20, effort 1-5 with words at both ends, an optional note
  through the privacy warning, and when they did it — up to seven days back, refused rather than
  quietly moved if the time is in the future or older.
- **Medication and sleep**: the therapist writes the medication list; the patient only ticks from it
  and can never type a medicine name. Sleep is hours 0-14 in halves and quality 1-5, one row per
  night, where logging the same night again replaces the earlier entry in the therapist's view and
  both stay in the record. Both go through the offline queue, so they survive a lost connection.
- **Therapist**: Patients gains the switch and the medication list (with the privacy check on what the
  therapist types); Review → From the patient gains a logged-session table stating plainly that it
  counts for practice but enters no trend, a medication table, and a sleep table and chart.
- **Two bugs the browser run found**: the per-patient controls shared one widget key, so switching
  patients showed — and would have saved — the previous patient's medication list; and an entry saved
  to the phone while offline did not raise the offline banner. Both fixed, both now covered by a test.
- Verified on an emulated iPhone in Chrome against the demo record: the notice, the exercise list with
  the program first, the privacy warning and edit, "Logged: Squat, 3 × 15 reps, felt hard.
  Self-reported.", the week count rising from 1 to 2 and the exercise turning green when the session
  is logged for today, a session logged for yesterday counting in that week instead, medication and
  sleep saved and corrected, a sleep entry queued offline and sent on reconnecting, the therapist
  seeing all three tables, and turning the switch off making the option disappear from the phone.
  Not verified: a real phone, and a real person logging what they actually did.

---

## Update 13 — 2026-09-24 — Video Clips from the Phone, Reviewed by the PT

Feature spec: `specs/011-video-clips/`. Schema moved to version 10 (`media`, `media_uploads`; the
access-history table rebuilt again for the media events).

- **Patient**: "Send a video" on Today. A notice comes first (stored on the Limber host, seen by the
  therapist, kept 90 days after review or 180 unreviewed, deletable). The clip is recorded with the
  phone camera or picked from the phone, uploaded in parts with progress, and resumed after a dropped
  connection. About 65 s and 80 MB at most; 10 clips a day. The caption goes through the privacy
  warning. Patients see, play, and delete their own clips; a marker stays.
- **The file decides what it is.** The service inspects every upload with the media library in a
  separate process with a timeout, never trusting the name or the declared type: MP4, MOV, and WebM
  with one video stream are accepted; images, audio-only, damaged, over-long, and unreadable files are
  refused with a reason, and nothing is stored. A file that crashes the library cannot take the
  service down.
- **Therapist**: Review → From the patient plays the clip with its caption and length, "Mark
  reviewed", "Delete". Clips awaiting review appear on the roster and in a new "New uploads" section
  of the work queue, without captions.
- **Kept safely**: files live under `data/media/<patient id>/` with private permissions and no original
  filename; deleting a patient removes them; `media retention` deletes files past their period (rows
  stay as markers); `media reconcile` removes expired uploads and files without rows. Backups now copy
  each clip once, encrypted, and `deploy restore` brings them back with the record.
- Verified on an emulated iPhone in Chrome: notice, preview, caption warning and edit, upload in
  parts, the patient's list, the therapist playing and reviewing the clip, and the patient seeing
  "seen by your therapist". Not verified: a real phone's camera capture and Safari playback of WebM.

---

## Update 12 — 2026-09-23 — Limber on the Phone: Installable App and Pain Check-ins

Feature spec: `specs/010-installable-app-checkins/`; the first of the phone features planned on
2026-09-23 (video clips, diary and logs, questionnaires, voice notes follow). Constitution 1.2.0. Schema
moved to version 9 (`entries`; the access-history table was rebuilt for new events, and a test
upgrades a real v8 record without losing a row).

- **Installable**: Limber offers "Add to Home Screen" (with iPhone steps, where the browser has no
  prompt), serves its own manifest and icons, and its shell opens without a connection. The API is
  never cached; Today's plan is kept as a per-patient snapshot on the phone, wiped on sign-out.
- **Stays signed in**: a sign-in from the installed app lasts 30 days on that device (three devices at
  most), and ends at once when the therapist revokes or reissues the code. Browser sign-ins keep the
  30-minute idle and 12-hour limits.
- **Check-ins**: pain 0-10, body area, stiffness, swelling, optional note; offered before and after a
  guided session and from Today. Made offline, they are queued on the phone and sent once, at their
  recorded time, when the connection returns. Notes go through the messages privacy warning.
- **For the PT**: Review has a "From the patient" tab (pain trend, check-in table, definitions, note
  removal). Two whole-patient thresholds, `pain_rise` (3 points over the mean of the previous three) and
  `pain_high` (7), drive `pain_rising` and `pain_high` flags in flags, the queue, and the roster.
- **Patient progress** shows pain over time beside the exercise trends.
- Verified on an emulated iPhone in Chrome: install hint, service worker, online check-in, offline
  shell with a queued check-in replayed exactly once, sign-out wiping local storage.

---

## Update 11 — 2026-09-21 — Ready to Host (nothing has been hosted yet)

Feature spec: `specs/009-cloud-deployment/`; runbook: `docs/DEPLOYMENT.md`. Limber can now be run on one
host behind HTTPS, provider-neutral: one application container (patient service plus the therapist app
under `/therapist`), a Caddy proxy that obtains the certificate and is the only thing exposed, and one
volume for the record, the server key, exports, and backups. **No cloud resource was created**, and the
container image has not been built yet because Docker is not installed on the development machine.

- `deploy preflight`: refuses to start without a therapist password, a server key, a writable record,
  the pose files, and an https public address, and says what to fix.
- `deploy init`: first boot; creates the server key and sets the therapist password from a secret file.
- `deploy backup` / `deploy restore`: online backup of the live record, authenticated encryption,
  verification, fourteen kept; a wrong key or damaged file is refused before anything changes.
- `/api/health` now proves the record can be read and written (503 otherwise).
- `cryptography` (already installed through aiortc) is now a direct, pinned dependency for backups.
- The clinic's camera features stay on the clinic machine; the hosted therapist app is for review,
  tracker, inbox, and home access. Exactly one instance may run against the record.

---

## Update 10 — 2026-09-21 — Messages: the Therapist's Inbox and the Patient's Conversation

Feature spec: `specs/008-messages/`. Schema moved to version 8 (`conversations`, `messages`,
`message_events`), applied automatically. For demo and study use, like the patient view.

- **Therapist**: a new **Inbox** page lists one conversation per patient, newest first, with the first
  line and an unread count; the sidebar shows the total unread on every page. Opening a thread marks
  the patient's messages read. Beside the thread: the latest session and open flags. Replies are plain
  text; a message can be removed (a marker stays). Patients waiting for a reply also appear on the
  roster and in a new "Unread messages" section of the work queue, without any message text.
- **Patient**: a **Messages** page in Limber, shown only when the therapist has turned messaging on
  for that patient. It always states that it is not for emergencies.
- **Privacy**: messaging is off by default per patient. Free text is the first place someone can type
  identifying details, so text that looks like a name, date, record number, phone number, or email
  address triggers a warning before sending; the writer can edit or send anyway, and that choice is
  recorded. Message text is never written to logs or to the event history, and is always displayed as
  plain text, never as markup. One shared therapist inbox; no notifications outside the app.
- **Limits**: 1 to 2,000 characters; 20 messages an hour per patient; closed for discharged patients.
- **Command line**: `messages inbox | show <patient> | send <patient> "text" [--confirm] | on | off | remove <id>`.
- **Found by testing in a browser and fixed**: styles that set `display` overrode the HTML `hidden`
  attribute on the patient pages, so an empty unread badge still showed; one global rule now keeps
  hidden elements hidden.

---

## Update 9 — 2026-09-21 — Limber for Patients (home use) and One Front Page

Feature spec: `specs/007-online-patient-view/`. For demo and consented study participants only; not
for real clinic patients until a compliance review approves it. The constitution moved to 1.1.0 for
this (what a networked feature must guarantee; the patient portal as the one patient-facing
interface). Schema moved to version 7, applied automatically.

### 1. What a patient gets

One address. On the front page they choose "I'm a patient" and enter the access code their therapist
gave them. They see **Today's plan** (assigned exercises, target reps, what is done today, sessions
this week, weekly streak), run a **guided session** with their own camera (rep count, form status,
feedback, next exercise, summary), and see **Your progress** (range of motion and form per session,
change since the first session, progress toward the goal, all with units and plain meanings).

### 2. Privacy by construction

The camera video never leaves the patient's device. Their browser finds 17 body points (MoveNet,
served by Limber itself after `python scripts/fetch_portal_assets.py`, which checks every file's
SHA-256) and sends only those numbers, fifteen times a second. The service runs the clinic's own
engine on them through the existing `LiveSession` adapter and records through the existing
recorder, so no rep or form logic was written twice. A patient only ever receives their own data:
no request names a patient, and tests search every response for other patients' IDs, labels, notes,
reviews, flags, and thresholds. Access codes are stored as keyed hashes, shown once, expire after 90
days, and can be revoked at once. Failed sign-ins are limited and every refusal reads the same.

### 3. Home and clinic numbers are kept apart

Measured on the sample clips, the browser's pose model and the clinic's agree on rep counts and form
scores but differ on range of motion by 3° to 24° (details in `research.md`). Every session now has a
capture origin, `clinic` or `home`, and trends, changes, goal progress, session comparison, and every
attention rule that compares sessions run within one origin only, for therapist and patient alike.
Session lists, trend tables, the review report, and the review CSV (new last column `recorded`) say
where each session was recorded. Adherence, pending reviews, and practice gaps count all sessions.

### 4. One front page, therapist sign-in

The front page also has a **Therapist sign-in** door. Set the password on the machine itself:

```bash
python interfaces/cli.py portal admin set-password      # asked for; 12 characters or more
python interfaces/cli.py portal code create P-017        # prints the patient's code once
python interfaces/cli.py portal serve                    # http://127.0.0.1:8600
streamlit run interfaces/app.py                          # the therapist app the door hands over to
```

With a password set, the therapist app shows nothing but a sign-in until it receives a single-use,
one-minute pass from the front page or the password itself; sign-ins last eight hours. With no
password set (a private machine) it opens as before. The Patients page has a **Home access** block
(issue a code, shown once; revoke; access history), and `portal audit` lists the history without
codes or addresses.

### 5. Other changes

- Two people can now exercise at once: starting a session supersedes only the same patient's running
  session (feature 004's rule was one per installation).
- `requirements.txt` pins starlette, uvicorn, websockets, and httpx, which already came with
  Streamlit and are now used directly. No new package is installed.
- Known: reaching the service from a phone needs HTTPS (browsers only allow the camera on HTTPS or
  localhost); see `specs/007-online-patient-view/quickstart.md`. The engine's message "Shoulders
  uneven by 178°" appears in side-on views, at home as in the clinic; it is an engine matter and was
  not changed here.

---

## Brand — 2026-09-21 — The app is now Limber

The product name is **Limber** ("physical therapy, between visits"). The brand sheets supplied by
the owner spell the wordmark "Limbr"; the owner confirmed the name is Limber, so the wordmark here
uses that spelling in the sheets' style. The sheets set the palette (teal `#0E6B64`, coral `#F2684A`, ink `#16302C`, warm off-white `#FAF8F4`)
and the mark: a bending limb with a coral joint on a rounded teal square.

- `interfaces/assets/`: the mark and lockup as SVG, and PNG icons rendered from the same geometry.
- Therapist app: Limber lockup in the sidebar, page icon, titles, and a theme in `.streamlit/config.toml`.
- Patient portal: logo header, "Today's plan" with a progress bar and check-circle exercise cards,
  after the "Inside Limber" design. Fonts fall back to the system's rounded sans, because the portal
  loads nothing from other sites.
- Code, database, environment variables (`PTASSIST_DB`), and folder names keep their existing names.

---

## Update 8 — 2026-09-21 — Per-Exercise Thresholds and Change History

Feature spec: `specs/006-threshold-refinements/`. Schema moved to version 5 (`exercise_thresholds`,
`threshold_changes`), applied automatically; existing values are kept and the history starts empty.

### 1. Thresholds for one exercise

Six thresholds (form drop, ROM regression, ROM plateau, sessions below target, partial-rep share
and rise) can be set for one exercise of one patient. The value in use is the exercise's, else
the patient's, else the installation's, else the built-in default. Practice gap and adherence
describe the whole patient and are rejected at exercise level. Flags, the roster, the queue, and
the review exports use the exercise's values; the report lists them as
`Knee Extension: ROM regression 5 degrees (exercise override)`.

### 2. Change history

Every change of a stored threshold (patient, exercise, or installation; set, reset, reset all,
restore defaults) is recorded with its time, old value, and new value. Saving an unchanged value
records nothing. A patient's history also shows installation changes, because they alter the
patient's effective values. History holds keys and whole numbers only and is removed with its
patient. There are no user accounts, so it records when and what, not who.

### 3. How to use it

```bash
python interfaces/cli.py review thresholds P-017 --exercise "Knee Extension" --set rom_regression=5
python interfaces/cli.py review thresholds P-017 --exercise "Knee Extension" --reset-all
python interfaces/cli.py review thresholds P-017 --history
python interfaces/cli.py review thresholds --installation --history
```

Web: Review → Goals & settings → Attention thresholds → "Applies to" (Whole patient or one
exercise), with "Change history" below it; Tracker → Settings shows the installation history.

---

## Update 7 — 2026-09-20 — Configurable Attention Thresholds

Feature spec: `specs/005-attention-thresholds/`. The numbers that decide when a patient needs
attention can now be tuned per patient and per installation. Schema moved to version 4
(`patient_thresholds`, `installation_thresholds`), applied automatically on first open; existing
practice-gap overrides and a changed installation adherence value are carried over.

### 1. Eight thresholds, one definition

`src/ptlog/thresholds.py` defines each threshold once, with unit, meaning, default, and range:

| Threshold | Unit | Default | Range |
|-----------|------|---------|-------|
| Practice gap | days | 7 | 1-90 |
| Form drop | points | 10 | 1-50 |
| ROM regression | degrees | 10 | 1-60 |
| ROM plateau | degrees | 3 | 1-30 |
| Sessions below target | sessions | 3 | 2-10 |
| Partial-rep share | percent | 25 | 1-100 |
| Partial-rep rise | percentage points | 10 | 1-100 |
| Adherence | percent | 60 | 1-100 |

The value in use for a patient is the patient's override, else the installation value, else the
built-in default. How many sessions a rule looks at is part of the rule and stays fixed.

### 2. Where it shows

- Every threshold-driven flag now ends with the threshold that applied, for example
  `(threshold 5 degrees)`. With no overrides the flags themselves are unchanged.
- The roster and queue use each patient's adherence and practice-gap thresholds; the adherence
  view prints `Attention threshold: 50% (patient)`.
- The review report has a `THRESHOLDS IN USE` section that marks overrides; the review CSV has a
  new last column `thresholds_in_use`.

### 3. How to change them

```bash
python interfaces/cli.py review thresholds P-017
python interfaces/cli.py review thresholds P-017 --set rom_regression=5 form_drop=8
python interfaces/cli.py review thresholds P-017 --reset rom_regression      # or --reset-all
python interfaces/cli.py review thresholds --installation --set adherence=50
python interfaces/cli.py review thresholds --installation --restore-defaults
```

Web: Review → Goals & settings → Attention thresholds (per patient); Tracker → Settings
(installation). The adherence control that sat on the Queue section moved to Tracker → Settings.
`review settings --gap-days` and `tracker settings --adherence-threshold` still work. Invalid
values are rejected with the allowed range and unit, and nothing is written.

---

## Update 6 — 2026-09-20 — Live Web Session Recording

Feature spec: `specs/004-live-session-recording/`. The web app's Live Session page now runs the
real exercise engine and records every session into the canonical record, exactly like the
command-line webcam session. No schema change.

### 1. One engine, one record

The page's private rep counter (no smoothing, no form assessment, nothing saved) is removed.
`src/live_session.py` adds `LiveSession`, a small adapter that performs the same per-frame
steps as the command-line webcam loop (pose → joint angle → `ExerciseTracker` →
`FormAnalyzer` → `SessionRecorder` → angle and panel drawing) for frames delivered by the
browser stream. `analyze.py` is not edited. `LiveVideoProcessor` in `interfaces/app.py` feeds
the stream to it. The on-video panel is the engine's own: exercise, reps against target,
angle (degrees), phase, form status, and up to two feedback messages.

Browser streams are often smaller than 720p (WebRTC lowers the resolution under load), and the
engine's panel is laid out in fixed pixels for 720p. `LiveSession` therefore draws the panel on a
720p-scaled copy of smaller frames and scales back, so the panel keeps its share of the picture
and no line is cut off. Frames of 720p or more are drawn exactly as the engine draws them.

### 2. What the PT does

Select the patient in the sidebar, choose the exercise (the list now comes from `config.yaml`),
target reps, and camera, then press START. The session is recorded under that patient from the
first processed frame, with source "webcam" and the camera choice as its reference. While
streaming: **Switch exercise** closes the set and opens a new one, **Reset reps** records a
reset, **Save Screenshot** writes `exports/<patient id>_<YYYYMMDD_HHMMSS>.png`. STOP ends the
session and the page shows the stored summary (reps, average form score 0-100, average ROM in
degrees, duration) with **Open in Sessions**. The placeholder "Save Session" button is gone;
sessions save themselves.

### 3. Interruptions

A killed app leaves the session marked interrupted with every recorded rep. A second stream
ends an earlier running session as interrupted. A session whose stream was lost (closed tab)
is marked interrupted with reason `stream_lost` when the page next finds it with no activity
for 10 seconds.

Behaviour change in the record: opening the record no longer interrupts a running session
whose recording process is still alive (the web app opens the record on every page render).
Every recorded session (web, command-line webcam, and video) stores its process id in the
session extras for this, so running `sessions list` in another terminal during a session no
longer interrupts it. Sessions from a dead process recover as before. `SessionStore` also gained `check_same_thread`, `interrupt_session()`, and
`last_activity_time()`.

### 4. Tests

Synthetic 17-keypoint poses drive the real tracker with no camera or model
(`tests/test_live_session.py`, `test_live_processor.py`, `test_live_interrupt.py`,
`test_store_live.py`, live-page tests in `test_app_pages.py`). Recording adds under 2 ms per
frame over 300 frames. Opt-in clip parity against the command-line runner:
`PTASSIST_E2E=1 .venv/bin/python -m pytest tests/test_live_parity_e2e.py`.

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
