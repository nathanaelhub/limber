# Feature Specification: A Hosted Demo on Vercel

**Feature Branch**: `020-hosted-demo`

**Created**: 2026-11-10

**Status**: Draft, awaiting the owner's approval. Depends on 009 (hosting), 016 (accounts), 018 (AI). Needs
constitution amendment 1.5.0 (below). The therapist side on Vercel depends on 019 (gate G3).

**Input**: The owner wants a link they can send to their professor: Limber running on Vercel. A first try
(`limber-demo.vercel.app`, 10 November 2026) deployed the existing container with Vercel's Container runtime.
Pages loaded, but every few clicks signed the user out. Vercel's container runtime (beta) serves about one
request per instance at a time, so a page load's parallel requests start new instances. Each instance had its own
copy of the record on its temporary disk: 9 of 10 parallel signed-in requests reached an instance that didn't
know the session. Vercel reports this as known beta behaviour, with no setting to change it. To run on Vercel,
every piece of shared state has to live outside the container, so that any instance can serve any request.

## Constitution Check (v1.4.0)

| Rule | This feature |
|------|--------------|
| I. Engine is a dependency | No engine change. |
| II. One canonical record | Kept. `SessionStore` stays the only writer; only where its file lives changes. The schema and its migrations are the same on both backends. |
| III. Local-first and privacy | **Needs amendment 1.5.0.** A hosted demo stores the record with a database service and uploads with a file store, both third parties. The amendment allows that only for a record of simulated data, enforced by a guard (FR-009). Local storage stays the default and the only option for any real record. |
| V. Simplicity | One new dependency, `libsql` (FR-001), justified in Complexity Tracking. Vercel Blob is called over HTTPS with `httpx`, which the `anthropic` SDK already installs. |
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

### User Story 5 - The Therapist Side Online (Priority: P2, see gate G3)

The professor also signs in as the therapist and sees the inbox, a patient's page, an AI draft, and video
analysis.

**Why this priority and the gate**: Streamlit keeps each therapist's session in one server process and sends
file uploads over a separate request. On Vercel that upload can reach a different instance from the one holding
the session, so uploads (video analysis, photos in a reply) fail, and every connection is cut at the function's
time limit (5 minutes on Hobby). The 019 clinic app has none of these problems. Gate G3 decides what the
therapist door does on Vercel until 019 ships.

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
  a patient ID). It writes to `data/media/` by default and to Vercel Blob when `BLOB_READ_WRITE_TOKEN` is set.
  Nothing else writes uploaded files.
- **FR-005**: Files are only ever served through Limber's existing signed-in routes. A file store address never
  reaches a browser, a log, or the record.
- **FR-006**: Upload parts are kept in the storage interface, not on an instance's disk, so consecutive parts may
  land on different instances. Clips and voice notes already go in 4 MB parts. Message attachments (up to four
  15 MB photos or one 20 MB PDF) are sent today in one request, over Vercel's 4.5 MB limit, so they move to the
  same parted upload path.
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

## Decision Gates (owner)

- **G1, spike**: before building, a short spike on a branch proves the libSQL client against a hosted database:
  the store's tests run through it, a write through one connection is read through a second one immediately, and
  the client handles the store's transactions. The client is at version 0.1.11 (pre-1.0), so this is the main risk.
  If it fails, the fallback is Postgres (Neon, also on the Vercel Marketplace), which means translating about 250
  SQL statements written for SQLite. That would be its own spec.
- **G2, amendment**: the owner approves constitution amendment 1.5.0.
- **G3, therapist side on Vercel until 019**: either (a) deploy Streamlit anyway, with a notice that video
  analysis and photo attachments don't work online; or (b) the Therapist door on the hosted demo says the
  therapist app is shown locally, until the 019 clinic app replaces Streamlit.
- **G4, accounts**: the owner adds Turso (libSQL) and Blob to the Vercel project from the Marketplace. Both have
  free tiers that cover a demo; the owner confirms before anything is billed.

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
- Video analysis (about 40 seconds for the demo clip) fits in one request and 2 GB of memory.
- The patient-side screens don't change.

## Complexity Tracking

| Addition | Why | Simpler alternative rejected because |
|----------|-----|--------------------------------------|
| `libsql` dependency and a second backend | Vercel instances share nothing; the record must live outside them | Keeping SQLite on the container disk: each instance has its own copy (measured: 9 of 10 parallel requests signed out) |
| A storage interface for files | Uploads must survive instances and scale-to-zero | Writing to `/tmp`: lost when the instance stops, and invisible to other instances |
| A demo guard | Principle III: third-party storage only for simulated data | Trusting the operator to remember: one wrong setting would put real patients in a third-party database |
| Hosting on a single long-lived server instead (Railway, Fly, Render) | Would need none of this: the 009 container runs there as built | The owner chose Vercel. The single-server route stays documented in `docs/DEPLOYMENT.md` |
