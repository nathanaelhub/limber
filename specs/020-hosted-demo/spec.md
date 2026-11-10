# Feature Specification: A Hosted Demo on Vercel

**Feature Branch**: `020-hosted-demo`

**Created**: 2026-11-10

**Status**: Draft, revised with the owner's decisions of 10 November 2026; awaiting approval. Depends on 009 (hosting), 016 (accounts), 018 (AI). Needs
constitution amendment 1.5.0 (below). The therapist side on Vercel depends on 019 (gate G3).

**Input**: The owner wants a link they can send to their professor: Limber running on Vercel. A first try
(`limber-demo.vercel.app`, 10 November 2026) deployed the existing container with Vercel's Container runtime.
Pages loaded, but every few clicks signed the user out. Vercel's container runtime (beta) serves about one
request per instance at a time, so a page load's parallel requests start new instances. Each instance had its own
copy of the record on its temporary disk: 9 of 10 parallel signed-in requests reached an instance that didn't
know the session. Vercel reports this as known beta behaviour, with no setting to change it. To run on Vercel,
every piece of shared state has to live outside the container, so that any instance can serve any request.

**Owner's decisions (10 November 2026)**: the record goes to **Turso** (libSQL); files go to a **Cloudflare R2**
bucket on the owner's Cloudflare account; the therapist side on Vercel is the **019 clinic app**, not Streamlit;
and video analysis on the hosted demo finds body points **in the therapist's browser**, as the patient portal
already does, so the server needs no torch or YOLO. With no heavy model on the server, Limber runs as ordinary
Vercel Python functions (the portal and the clinic app are Starlette apps), which serve many requests per
instance, rather than on the container beta.

## Constitution Check (v1.4.0)

| Rule | This feature |
|------|--------------|
| I. Engine is a dependency | No engine change. |
| II. One canonical record | Kept. `SessionStore` stays the only writer; only where its file lives changes. The schema and its migrations are the same on both backends. |
| III. Local-first and privacy | **Needs amendment 1.5.0.** A hosted demo stores the record with a database service and uploads with a file store, both third parties. The amendment allows that only for a record of simulated data, enforced by a guard (FR-009). Local storage stays the default and the only option for any real record. |
| V. Simplicity | New dependencies: `libsql` (FR-001) and an S3 client for R2 (`boto3`, or a small request signer over `httpx`, chosen in the plan), justified in Complexity Tracking. The hosted install needs neither torch nor YOLO. |
| Canonical store constraint | "MUST persist to a single local file" gains an exception for the hosted demo (amendment 1.5.0). |

### Proposed amendment 1.5.0 (MINOR)

Add to Principle III, after its first bullet:

> - A **hosted demo** MAY keep its record in a hosted SQLite-compatible database and its uploaded files in a
>   hosted file store, only if: the record holds simulated data only and carries the simulated-data marker that
>   `scripts/seed_demo.py` writes; the installation refuses to start on a hosted record without that marker; it
>   is never used for real patients or consented study participants; and it is protected or clearly labelled as
>   a demo. Every other installation stores its record and files locally.

And in Technical Constraints, "Canonical store": *"…MUST persist to a single local file, except for a hosted
demo under Principle III."*

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A Demo Link That Behaves Like the Real App (Priority: P1)

The owner sends `https://limber-demo.vercel.app` to their professor. The professor signs in as the demo patient,
logs a check-in, sends a message, opens Progress and Visits, and stays signed in the whole time, however Vercel
spreads the requests across instances.

**Why this priority**: it is the goal of the feature. Today the link signs people out every few clicks.

**Independent Test**: sign in once, then send 50 parallel requests with that sign-in to the hosted demo.

**Acceptance Scenarios**:

1. **Given** a patient signed in through one instance, **When** a request lands on another instance, **Then**
   the patient is still signed in.
2. **Given** a message sent through one instance, **When** the next page load lands on another instance, **Then**
   the message is there.
3. **Given** five wrong passwords spread across instances, **Then** the sign-in limiter counts all five.
4. **Given** the demo has scaled to zero, **When** the professor opens the link, **Then** the first page loads
   within 15 seconds with yesterday's demo data (nothing is re-seeded at start-up).

---

### User Story 2 - Uploads Work on the Hosted Demo (Priority: P1)

The demo patient sends a photo, a voice note, or a short clip. It is stored once, plays back from any instance,
and is deleted with the patient, as it is locally.

**Why this priority**: uploads are a large part of what Limber does between visits, and today they are written
to a disk that disappears.

**Independent Test**: upload a voice note in parts that land on different instances, then play it back.

**Acceptance Scenarios**:

1. **Given** an upload sent in parts, **When** the parts land on different instances, **Then** the finished file
   is whole and passes the media probe.
2. **Given** a stored photo, **When** the therapist or the patient opens it, **Then** it is served through
   Limber's signed-in routes. The file store's own address is never sent to a browser.
3. **Given** a patient is deleted, **Then** their files are deleted from the file store.
4. **Given** a clip or voice note over the platform's 4.5 MB request limit, **Then** it still uploads, because it
   is sent in 4 MB parts.
5. **Given** a message with photos or a PDF larger than 4 MB in total, **Then** it still sends (FR-006).

---

### User Story 3 - Local and Self-Hosted Installs Don't Change (Priority: P1)

A therapist running Limber on the clinic machine, or on the 009 container, notices nothing: same file, same
folders, same commands, no new setting needed.

**Why this priority**: the hosted demo must not put the real setup at risk.

**Independent Test**: the full test suite passes with no hosted settings present, as today.

**Acceptance Scenarios**:

1. **Given** no hosted settings, **Then** the record is `data/ptassist.db` (or `PTASSIST_DB`) and files are under
   `data/media/`, exactly as now.
2. **Given** the hosted settings are present but the record lacks the simulated-data marker, **Then** Limber
   refuses to start and says why.

---

### User Story 4 - Resetting the Demo (Priority: P2)

After showing the demo, the owner resets it to a fresh simulated clinic with one command.

**Acceptance Scenarios**:

1. **Given** the hosted settings on the owner's machine, **When** they run the reset command, **Then** the hosted
   record and files are replaced by a fresh seed, and the new access codes are printed once.
2. **Given** a real (unmarked) record, **Then** the reset command refuses to touch it.

---

### User Story 5 - The Therapist Side Online (Priority: P2, delivered by 019)

The professor also signs in as the therapist and sees the inbox, a patient's page, an AI draft, and video
analysis.

**Why it comes through 019**: Streamlit keeps each therapist's session in one server process and sends file
uploads over a separate request. On Vercel that upload can reach a different instance from the one holding the
session, and every connection is cut at the function's time limit. The owner chose the 019 clinic app, which is
stateless, as the therapist side on Vercel. Each clinic slice goes online as it is merged; Streamlit is never
deployed to Vercel and stays the local therapist app until 019's cutover.

**Acceptance Scenarios**:

1. **Given** the hosted demo, **When** the therapist door is used before the clinic app has the page needed,
   **Then** it says plainly which pages are online so far, and that the full therapist app runs locally.
2. **Given** a clinic slice is merged, **Then** its pages work on the hosted demo with the same tests as locally.

---

### User Story 6 - Video Analysis Without Uploading the Video (Priority: P2)

On the hosted demo, the therapist picks a video file. Their browser finds the body points frame by frame and
sends only those to Limber, which counts reps, measures range of motion, and scores form with the engine's own
rules. The result shows the same numbers and a skeleton drawn over the video in the browser.

**Why this priority**: it removes the only reason Limber needed a heavy server, and the video never leaves the
therapist's computer.

**Acceptance Scenarios**:

1. **Given** the Squats demo clip, **When** it is analysed in the browser, **Then** the rep count, range of motion,
   and form score are within the tolerances agreed at gate G5, compared with YOLO on the same clip.
2. **Given** a video of any length, **Then** nothing but body points and the result is sent to Limber.
3. **Given** the local install, **Then** YOLO video analysis is unchanged.

### Edge Cases

- Two instances write at the same moment: the database orders the writes; no write is lost.
- The database or the file store can't be reached: `/api/health` answers 503 with which one, pages show a plain
  error, and nothing is written halfway.
- An instance is stopped during an upload: the upload resumes from the last stored part.
- A temporary file needed for probing or transcription is created under `/tmp` and removed when the request ends.
- The AI cap is shared: the daily count is in the record, so instances can't each grant their own.

## Requirements *(mandatory)*

- **FR-001**: The record backend is chosen by settings. With `LIMBER_DB_URL` (a `libsql://` address) and
  `LIMBER_DB_TOKEN`, `SessionStore` opens the hosted database. Without them it opens the local file, as today.
- **FR-002**: `SessionStore` remains the only code that opens the record. Every connection comes from one
  function, which also gives rows that are read by column name on both backends (the libSQL client returns plain
  tuples).
- **FR-003**: The schema and migrations are the same on both backends. A migration that needs a SQLite feature the
  hosted database lacks is a test failure, not a silent difference.
- **FR-004**: Files go through one storage interface in `src/media/` (put, get, delete, delete everything under
  a patient ID). It writes to `data/media/` by default and to the Cloudflare R2 bucket when the `LIMBER_R2_*`
  settings (account, bucket, access key, secret) are set. Nothing else writes uploaded files. The R2 key is scoped
  to that one bucket.
- **FR-005**: Limber decides who may read or write a file, as today. A browser gets only a short-lived signed R2
  link for one file (minutes, not hours), issued after the same checks as the existing routes. The bucket is never
  public, and signed links are never logged or stored in the record.
- **FR-006**: Upload parts are kept in the storage interface, not on an instance's disk, so consecutive parts may
  land on different instances. Clips and voice notes already go in 4 MB parts. Message attachments (up to four
  15 MB photos or one 20 MB PDF) are sent today in one request, over Vercel's 4.5 MB limit. On the hosted demo
  every upload goes from the browser straight to R2 with a signed link (FR-005), and Limber then checks the
  stored file (size, type, the media probe) before accepting it.
- **FR-007**: The sign-in limiter's counts are kept in the record, not in memory.
- **FR-008**: On a hosted install the server key comes from `PTASSIST_PORTAL_KEY`. A hosted install without it
  refuses to start.
- **FR-009**: The demo guard: hosted settings work only with `LIMBER_DEMO=1` and a record carrying the
  simulated-data marker, which only `scripts/seed_demo.py` writes. `deploy preflight` reports which backend is in
  use and whether the guard passed.
- **FR-010**: Nothing is seeded at instance start-up on a hosted install. Seeding and resetting are done by a
  command run by the owner (`deploy demo-reset`).
- **FR-011**: `/api/health` checks that the record and the file store can be reached.
- **FR-012**: The AI daily cap (018) already counts calls in the record (`assist_calls`), so with a shared record
  it holds across instances. The hosted demo's cap is 10 calls per account per day.
- **FR-013**: The test suite runs on the local backend as today. A store contract suite also runs against libSQL
  in its local-file mode in CI, with no network. A live check against the hosted database runs only on the owner's
  machine, never in CI.
- **FR-014**: The deploy groundwork from the first attempt is kept: `.dockerignore` and `.vercelignore` keep
  `.env` and records out of images and uploads; Caddy on one port; the port opens only when both apps answer.
- **FR-015**: On Vercel, the patient portal and the clinic app run as Python functions (ASGI), with their static
  files served by Vercel. The hosted install doesn't install torch, YOLO, OpenCV, or Streamlit.
- **FR-016**: Hosted video analysis runs the pose model in the therapist's browser and sends body points only.
  The server runs the engine's own rep counting and form rules on them (the path `src/portal/live.py` already uses
  for patients), with no change to the engine (Principle I). The pose model is named on the session record.
- **FR-017**: Browser JavaScript holds no clinical logic. It finds body points and draws; counting and scoring stay
  in Python, covered by the test suite.

## Decision Gates (owner)

- **G1, spike**: before building, a short spike on a branch proves the libSQL client against a hosted database:
  the store's tests run through it, a write through one connection is read through a second one immediately, and
  the client handles the store's transactions. The client is at version 0.1.11 (pre-1.0), so this is the main risk.
  If it fails, the fallback is Postgres (Neon, also on the Vercel Marketplace), which means translating about 250
  SQL statements written for SQLite. That would be its own spec.
- **G2, amendment**: the owner approves constitution amendment 1.5.0.
- **G3, therapist side on Vercel**: decided 10 November 2026. The 019 clinic app; Streamlit is not deployed.
- **G4, accounts**: the owner adds Turso to the Vercel project from the Marketplace and creates an R2 bucket and a
  bucket-scoped API token on their Cloudflare account. Both have free tiers that cover a demo; the owner confirms
  before anything is billed.
- **G5, browser pose accuracy**: the same comparison as 019's gate G2. MoveNet in the browser and YOLO11 on the
  server are run on the same clips (the three Ultralytics demo clips, including the ones behind issues #23 and #24).
  The owner sets the tolerances and decides from the numbers.

## Success Criteria

- **SC-001**: 50 parallel signed-in requests to the hosted demo all succeed with the same sign-in (today, 1 in 10).
- **SC-002**: A message written through one instance is readable through another within 1 second.
- **SC-003**: The full test suite passes unchanged on the local backend, and the store contract suite passes on
  libSQL.
- **SC-004**: From scaled to zero, the first page arrives within 15 seconds (Vercel stops waiting for a container
  to listen at about 15 seconds).
- **SC-005**: A hosted install pointed at a record without the simulated-data marker refuses to start (automated
  test).

## Assumptions

- The hosted demo holds simulated data only. It is protected with Vercel Authentication while in development and
  opened to the professor with a share link or by turning protection off for the meeting.
- Vercel's container runtime keeps its current limits: about one request per instance, scale to zero after 5
  minutes, a 4.5 MB request body, and 5 minutes per request on Hobby.
- Vercel's container runtime is not used. Python functions get several requests per instance, 2 GB of memory,
  and 5 minutes per request on Hobby.
- The therapist's computer can run MoveNet in the browser, as patients' phones already do.
- The patient-side screens don't change.

## Complexity Tracking

| Addition | Why | Simpler alternative rejected because |
|----------|-----|--------------------------------------|
| `libsql` dependency and a second backend | Vercel instances share nothing; the record must live outside them | Keeping SQLite on the container disk: each instance has its own copy (measured: 9 of 10 parallel requests signed out) |
| A storage interface for files, with an S3 client for R2 | Uploads must survive instances and scale-to-zero, and large ones must bypass the 4.5 MB request limit | Writing to `/tmp`: lost when the instance stops, and invisible to other instances |
| Browser pose for hosted video analysis | No torch on the server, so ordinary Python functions instead of a 2 GB container beta | YOLO on Vercel's container runtime: one request per instance, slow cold starts, and every video uploaded through a 4.5 MB limit |
| A demo guard | Principle III: third-party storage only for simulated data | Trusting the operator to remember: one wrong setting would put real patients in a third-party database |
| Hosting on a single long-lived server instead (Railway, Fly, Render) | Would need none of this: the 009 container runs there as built | The owner chose Vercel. The single-server route stays documented in `docs/DEPLOYMENT.md` |
