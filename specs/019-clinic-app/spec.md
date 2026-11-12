# Feature Specification: The Clinic App (New Therapist and Admin Interface)

**Feature Branch**: `019-clinic-app`

**Created**: 2026-11-05

**Status**: Approved; revised 11 November 2026 for the hosted demo (020) and the owner's decisions below. Depends on
016, 017, 018, and 020.

**Input**: The owner finds the therapist side cluttered and too close to the old PTA site: 13 sidebar links,
stacked dropdowns, and tables used as menus. Much of that comes from Streamlit. The owner chose a new web app
with every current page rebuilt, a slim top bar with a split view, and a look from a new Claude Design prompt
(`specs/design/claude-design-clinic-prompt.md`).

**Owner's decisions (11 November 2026)**: the clinic app runs on the hosted demo too, mounted at `/therapist` beside
the patient portal on Vercel (020); therapists sign in at the portal's Therapist door **and** on an in-app sign-in
screen, with no first-run setup on the web; video analysis on the hosted demo finds body points in the browser
(020 FR-016); the first showing is "daily work online" (Inbox, Patients, Schedule).

## Constitution Check (v1.4.0)

| Rule | This feature |
|------|--------------|
| I. Engine is a dependency | No engine change. Live session and Video analysis use the existing public outputs through `LiveSession` and `analyze.py`. |
| III. Privacy | Patients stay pseudonymous. Nothing new crosses the network. The one AI processor and its guarantees are unchanged (018). Live session sends body points to the host; video stays in the browser, as in 007. |
| V. Simplicity | No new dependency. Starlette is already used by the portal. Streamlit and `streamlit-webrtc` are removed at cutover. Every metric keeps its unit and plain-language definition. |
| User interface | Amendment 1.4.0: the clinic app becomes a therapist surface, separate from the patient portal. Amendment 1.5.1 (wording): on a hosted demo both apps may be mounted at different path prefixes of one entry point. Until cutover both therapist apps exist. |
| Logic in `src/` | Rules still in `interfaces/app.py` move to `src/clinic/`. Browser JavaScript holds no clinical logic. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One Clear Place to Start (Priority: P1)

A therapist signs in and sees one calm screen: a slim top bar and a list of what needs them. Daily work takes
three links. The tools are one menu away, and nothing else competes for attention.

**Acceptance Scenarios**:

1. **Given** a therapist, **Then** the top bar shows Inbox, Patients, Schedule, patient search, Tools, and Me,
   and no other navigation.
2. **Given** an admin-only account, **Then** it sees People and My settings and no clinical page or route (403).
3. **Given** a therapist signed in, **When** they reload or open a saved page URL, **Then** they stay signed in
   and land on that page, until the 8-hour sign-in ends.
4. **Given** no staff password is set, **Then** the app shows a setup message and no clinical data.

### User Story 2 - The Inbox Reads Like an Email App (Priority: P1)

The left side is one "Needs you" list: unread messages by plan, reschedule requests, and red flags. The right
side is the open item. There are no row, conversation, and plan pickers.

**Acceptance Scenarios**:

1. **Given** an item is selected, **Then** the right side shows its thread, attachments, voice notes, and reply
   box, and the URL names that item.
2. **Given** the Inbox opens, **Then** nothing is marked read until the therapist opens a conversation.
3. **Given** a reply that looks like it holds a phone number or name, **Then** the warning and Send anyway work as
   they do today.
4. **Given** **Draft a reply**, **Then** the draft lands in the reply box labelled as AI and is never sent on its
   own. **Given** a red-flag message since the last reply, **Then** the draft is withheld and the notice quotes
   the patient's words.

### User Story 3 - A Patient on One Page (Priority: P1)

The Patients page lists patients on the left and the chosen patient on the right, with sections for Overview,
Exercises, Messages, Session notes, AI settings, and Details. Everything the current page does still works.

**Acceptance Scenarios**:

1. **Given** the current page's actions (register, program, plans and visits, questionnaires, what the patient
   can log, home access codes, discharge, delete, weekly summary, AI switches, coach log), **Then** each works in
   the new page with the same rules.
2. **Given** an archived plan, **Then** nothing can be added to it (409), as in 017.
3. **Given** a patient, **Then** Review and Sessions for that patient are one link away.

### User Story 4 - Schedule and Administration (Priority: P2)

Schedule shows reschedule requests first, then upcoming and past visits. People handles invites, disabling an
account, and reassigning patients. My settings holds Larger text, Higher contrast, and Less motion.

**Acceptance Scenarios**:

1. **Given** the same data, **Then** the Schedule order and contents match the current page.
2. **Given** a non-admin, **Then** People and its routes are refused.
3. **Given** a preference is saved, **Then** it applies on first render of every page.

### User Story 5 - The Tools Still Work (Priority: P2)

Dashboard, Sessions, Review, Tracker, Observation logs, Video analysis, Live session, and How it works are
rebuilt and reached from the Tools menu.

**Acceptance Scenarios**:

1. **Given** the Dashboard, **Then** every figure and row comes from the record. The hard-coded sample "Recent
   Sessions" are gone.
2. **Given** Review, Sessions, Tracker, or Observation logs, **Then** the same charts, tables, and exports are
   available, and exported files match the current ones byte for byte for the same data.
3. **Given** a video upload, **Then** analysis runs as a background job with progress, and the annotated video
   and report can be downloaded.
4. **Given** Live session, **Then** the therapist sees the camera, reps, and form feedback, and a stored session
   appears in Sessions. Body points are sent; video is not.

### Edge Cases

- Sign-in ends during a reply: the typed text stays in the box until the therapist signs in again.
- Two tabs open: a reply sent in one appears in the other on its next refresh.
- The AI key is missing: AI controls explain that the assistant isn't available, and everything else works.
- A patient is outside the therapist's caseload: every route answers 404, the same as a patient who doesn't exist.

## Requirements *(mandatory)*

- **FR-001**: The clinic app is its own app (`interfaces/clinic.py`, Starlette), with its pages in
  `interfaces/clinic_static/`, served under the path `/therapist` everywhere: its own local launch (port 8502
  while it is built, 8501 at cutover, behind the existing Caddy route) and, on the hosted demo, mounted at
  `/therapist` beside the portal in the same Vercel function, with its own routes, cookie, static folder and
  content security policy. It contains no patient pages, and the portal contains no therapist pages.
- **FR-002**: The portal's Therapist door hands over a single-use pass (`src/portal/admin.py`) that the clinic app
  redeems, then removes from the address. The clinic app also has its own sign-in screen (username and
  password, `admin.sign_in`), with the same lockouts as the portal (`RecordLoginLimiter` on the hosted demo), for
  when a sign-in ends during work. The sign-in is held in an HttpOnly, SameSite=Strict cookie, `Path=/therapist`,
  Secure over HTTPS, and lasts 8 hours, as today. There is no first-run setup on the web: with no staff password
  set, the app shows the command that sets one (`portal admin set-password`), because a web form would let
  anyone who reaches the address create the admin.
- **FR-003**: Every clinic request opens the store through `ptaccounts.restrict` in one shared function. No route
  opens the store another way.
- **FR-004**: Every state-changing route requires an exact Origin match and a JSON or upload content type, and
  answers 403 or 415 otherwise, as `check_post` does in the portal.
- **FR-005**: Pages load scripts, styles, and fonts only from the clinic app itself, under the portal's strict
  content security policy. There is no inline script and no `style=` attribute: the export's 300 inline styles
  become utility classes in `limber.css`, and sizes that change at run time are set from script (`el.style`),
  which the policy allows. `limber.css` gains `[hidden]{display:none!important}`. Sora is self-hosted.
- **FR-006**: Roles match today: therapists see the clinic pages and tools; admins also see People; admin-only
  accounts see only People and My settings. Roles are enforced on routes, not just hidden in menus.
- **FR-007**: Reading a thread marks it read only when a therapist explicitly opens it.
- **FR-008**: Every behaviour listed in Story 2 scenarios 3 and 4 and in 018 (labels on AI text, nothing sent
  automatically, red-flag screening before any draft) is kept and tested through the clinic app.
- **FR-009**: Rules now in `interfaces/app.py` move to `src/clinic/` and are tested without a server: send-anyway
  state, the draft guard, default conversation choice, plan summary, and the Schedule visit list.
- **FR-010**: Charts are drawn by a small SVG helper in the clinic app, with no outside library. Every chart has
  a text or table equivalent.
- **FR-011**: Every metric shows its unit and plain-language definition (Principle V).
- **FR-012**: Pages meet WCAG 2.2 AA at 1280px and 1024px, and work with Larger text, Higher contrast (AAA), and
  Less motion: the account's preferences map to the export's classes `lt`, `hc` and `lm` on first render, and
  chart text scales with Larger text. Colour alone never carries meaning.
- **FR-013**: Live session reuses the browser pose path of 007 (`src/portal/live.py`, `session.js`) for therapist
  use, with the session recorded under the chosen patient and the pose model named on the record. It uses the
  transport and session lease that 020 slice F settles for the hosted demo.
- **FR-014**: Video analysis finds body points in the therapist's browser (MoveNet) and sends them in one request;
  the server counts reps and scores form with the engine's own rules and records the session as a video with the
  pose model named (020 FR-016, FR-017). The video itself is never uploaded. Form events are recorded on this path
  (the YOLO path records none). Whether local installs keep YOLO video analysis is decided at G2.
- **FR-015**: At cutover the clinic app takes port 8501, and `interfaces/app.py`, `interfaces/app_theme.py`,
  `.streamlit/`, `streamlit`, `streamlit-webrtc`, `pyarrow`, and (once nothing else uses it) `pandas` are removed.
  `deploy/*` and the docs are updated.
- **FR-016**: The patient portal's service worker never handles `/therapist` addresses, so no therapist page or
  data is ever kept in a browser cache.

## Decision Gates (owner)

- **G1, design**: the owner runs the Claude Design prompt and approves the export in
  `design/limber-clinic-export/` before Foundation starts. **Done 10 November 2026**: the owner ran the prompt and supplied the
  export (30 screens and states at 1280px, `limber.css`, self-hosted Sora, and the on-screen copy). It has no
  scripts and no outside links, but its 300 inline `style=` attributes would be blocked by the content security
  policy, so they become classes when the screens are built (FR-005). (Corrected 11 November 2026.)
- **G2, live session and video** (the same gate as 020 G5): before cutover, MoveNet and YOLO11 are compared on the
  same recorded clips (rep count, range of motion, form score; the three Ultralytics clips, including those behind
  issues #23 and #24). The owner decides from those numbers whether browser pose is good enough, and whether local
  video analysis keeps YOLO.
- **G3, cutover**: the 16 user cases pass against the clinic app before anything is removed.

## Success Criteria

- **SC-001**: The top bar has no more than seven items, down from 13 sidebar links: Dashboard, Inbox, Patients,
  Schedule, Find a patient, Tools and Me. (Amended 12 November 2026 by the owner: the Dashboard became the home
  page and a top-bar item, and the design's patient search stays in the top bar.)
- **SC-002**: From sign-in, a therapist can open an unread conversation and send a reply in 3 clicks or fewer,
  plus typing.
- **SC-003**: Every Streamlit page has a clinic equivalent, and every behaviour pinned by the current UI tests has
  a clinic test before those tests are removed, except these, retired on purpose: the app opening with no staff
  password (now a setup message), the live screenshot saved to the export folder (now a browser download), and the
  placeholder images and made-up form-score formula on How it works.
- **SC-004**: `rivera` cannot reach another therapist's patient through any clinic route (automated test over the
  route table).

## Assumptions

- A therapist uses a laptop or desktop browser. No phone layout in this feature; below 1024px the app stays usable
  but isn't designed for it.
- The existing record and schema stay as they are. A migration is added only if a slice proves it necessary.
- Patient-side screens don't change.
- Sign-in is unchanged for patients and for the invite flow, apart from where the staff redirect lands.

## Complexity Tracking

Moving off Streamlit is a larger change than a restyle. The simpler alternative, restyling Streamlit, was rejected
by the owner because the framework's layout and widgets are the cause of the look. The net dependency count falls.
