# Feature Specification: Therapist Extras (Exercise Details, Proposed Times, Progress Report, Admin History)

**Feature Branch**: `021-therapist-extras`

**Created**: 2026-11-13

**Status**: Approved 13 November 2026, with the owner's decisions D1 to D3 below. Depends on 017 (plans of
care and visits), 019 (the clinic app, cut over in #93), and 020 (the hosted demo).

**Input**: When planning the rest of the therapist side (12 November 2026), the owner chose four additions for after
the cutover:
- per-exercise details;
- the patient proposes a time when asking to reschedule;
- a progress report that prints to PDF;
- a history view for admins.

Today the record keeps a program as only a list of exercise keys and visits a week. A reschedule request is only a
yes or no plus a note. The Review page has text and CSV exports but nothing to hand to a patient or a referrer. And
admins can't see who did what.

## Constitution Check (v1.5.2)

| Rule | This feature |
|------|--------------|
| I. Engine is a dependency | No engine change. The live session's target reps come from the prescription (N1), passed in through `LiveSession`'s existing `target_reps`. |
| II. One canonical record | One schema migration, **v19**, for N1, N2 and N4 together, so the hosted demo is reset once. `SessionStore` stays the only writer, and the migration is the same on SQLite and libSQL. |
| III. Privacy | Patients stay pseudonymous. A patient's note to the therapist still goes through the existing privacy check. The progress report shows the patient code and clinical labels only, never a name. Nothing new crosses the network. The report is built on the server and printed by the browser. |
| V. Simplicity | No new dependency. The report is an HTML page with a print stylesheet; the browser's "Save as PDF" makes the file, so it works on Vercel with nothing installed. Every number on the report keeps its unit and plain-language definition (`views.METRIC_DEFINITIONS`). `docs/UPDATES.md` gets one entry per story. |
| User interface | Clinic app and patient portal only, each in its own app. There is no new top-bar item: the report lives under Review, and History under People. |
| Logic in `src/` | Rules in `src/clinic/` and `src/portal/`; browser JavaScript holds none. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Patient Knows Exactly What to Do (N1, Priority: P1)

The therapist opens a patient's Exercises tab. For each exercise in the program they set:
- sets, reps and hold;
- how often (every day, or N days a week);
- a short note to the patient, such as "Keep your knee soft at the top".

They can add an exercise, remove one, or change a number without re-assigning the whole program. The patient's
Today page and exercise list then read "3 sets of 10 · 5-second hold · Every day", with the note underneath. When the
patient starts that exercise in a live session, the target is the prescribed reps.

**Why this priority**: it is the clinical heart of a home program, and the patient side can't follow a dose it is
never told.

**Independent Test**: set details on one exercise as a therapist, sign in as that patient, and read them on Today.
Start a live session and see the target.

**Acceptance Scenarios**:

1. **Given** an active program with Squat and Leg extension, **When** the therapist sets Squat to 3 × 10 with no hold,
   every day, with a note, **Then** the patient's Today shows "3 sets of 10 · Every day" and the note, and Leg
   extension still shows its default target.
2. **Given** those details, **When** the patient starts a Squat live session, **Then** the target is 10 reps per set.
   A set completes at 10.
3. **Given** the therapist changes Squat from 10 to 12 reps, **Then** the current program is changed in place (the
   adherence history is unchanged), and the patient sees 12 on their next page load.
4. **Given** the therapist adds Bridge or removes Leg extension, **Then** a new assignment starts today with the
   details carried over for the exercises in both, and past weeks keep the list they had (D2).
5. **Given** a note that looks like it identifies someone (the existing privacy check), **Then** the therapist is
   warned and can edit it or send it anyway, as with replies.
6. **Given** reps outside 1–100, sets outside 1–10, hold outside 0–120 seconds, or a note over 200 characters,
   **Then** the change is refused with a plain message.
7. **Given** the AI draft or summary for that patient, **Then** its extract includes the prescription, so a draft
   doesn't contradict it.

### User Story 2 - The Patient Proposes a New Time (N2, Priority: P1)

When a patient asks to move a visit, they can also pick a day and time that suits them (optional, future only). The
therapist sees "Asks for Fri 6 Nov, 09:00" on the request, with three actions:
- **Accept**: one click, which moves the visit to that time;
- **Offer another time**: the existing move, with a note;
- **Keep the time**: the existing decline, with a note.

This shows on the Inbox, the Schedule and the Dashboard. The patient's Visits page shows the answer.

**Why this priority**: today a request is a back-and-forth by message. A proposed time makes most requests one click.

**Independent Test**: as the patient, ask to move a visit to a time 3 days out. As the therapist, Accept it from the
Dashboard. As the patient, see the new time.

**Acceptance Scenarios**:

1. **Given** an upcoming visit, **When** the patient asks to move it with a time 3 days out and a note, **Then** the
   request stores both, and the therapist's Needs you count goes up by one.
2. **Given** that request, **When** the therapist clicks Accept, **Then** the visit starts at the proposed time (same
   length), the request clears, and the patient's Visits shows the new time with "Moved at your request".
3. **Given** the proposed time has passed by the time the therapist looks, **Then** Accept isn't offered. The
   request reads "The time they asked for has passed", and Offer another time and Keep still work.
4. **Given** the patient proposes a time in the past, more than 90 days away, or not on a 5-minute step, **Then** the
   portal refuses it with a plain message.
5. **Given** a request without a proposed time, **Then** everything works exactly as today.
6. **Given** the proposed time overlaps another visit of the same therapist, **Then** Accept still works, but first
   says "This overlaps P-0xx's visit at 09:00" and asks for confirmation.
7. **Given** a second request on the same visit, **Then** it replaces the first one's time and note.

### User Story 3 - A Progress Report to Print or Save as PDF (N3, Priority: P2)

From a patient's Review page, the therapist opens "Progress report", chooses a period (the last 4 weeks, the last 12
weeks, this plan of care, or everything) and presses "Print or save as PDF". The report shows:
- the patient code;
- the plan of care and its dates;
- the period;
- trends with their tables (range of motion and form by exercise, pain);
- goals and progress toward them;
- adherence by week;
- questionnaire scores with the change from first to latest;
- the prescription (N1, once it exists);
- saved notes, with AI-drafted ones labelled as such.

**Why this priority**: it gives the therapist something to hand to the patient or send to a referrer. It needs no
schema change, so it can ship first if wanted.

**Independent Test**: open the report for P-017 on the hosted demo, print to PDF from the browser, and check that
every chart has its table and every number has its unit.

**Acceptance Scenarios**:

1. **Given** P-017 with sessions, goals and questionnaires, **When** the therapist opens the report for 12 weeks,
   **Then** each section above renders, and a section with no data says so in one line rather than disappearing.
2. **Given** the browser's print preview, **Then** the top bar, menus and buttons are hidden. The page is A4/Letter
   portrait with page breaks between sections, and each chart sits with its table.
3. **Given** a therapist who can't see the patient (another caseload), **Then** the report answers 404, like every
   other patient page.
4. **Given** a saved AI summary in the period, **Then** it shows with its "AI-drafted" label, the date, and who saved
   it.
5. **Given** the report, **Then** it never shows a patient's message text, a voice-note transcript, or free-text
   notes from the patient.

### User Story 4 - Admins See Who Did What (N4, Priority: P3)

An admin opens People → History and sees, newest first:
- account changes: created, invited, invite used or revoked, disabled or enabled, patient reassigned, settings
  changed;
- staff sign-ins and failed attempts.

The actor and subject are shown as names. The admin can filter by kind and load 200 at a time.

**Why this priority**: accountability for a multi-therapist installation. It matters less for a demo, so it comes
last.

**Independent Test**: as admin, reassign a patient and sign in as rivera. Then History shows both, with names.

**Acceptance Scenarios**:

1. **Given** account events in the record, **When** an admin opens History, **Then** each row shows the time (clinic
   time), what happened, who did it, and to whom or what. A patient appears only by code.
2. **Given** staff sign-ins after v19, **Then** each shows which account signed in. Sign-ins from before v19 show
   "account not recorded".
3. **Given** a failed sign-in for a username that doesn't exist, **Then** the row says "unknown username". The typed
   name isn't stored, because it could be a mistyped password.
4. **Given** a therapist who isn't an admin, **Then** History answers 403, like the rest of People.
5. **Given** more than 200 rows, **Then** "Show older" loads the next 200.
6. **Given** History, **Then** it shows no clinical fields: no session data, messages, notes or patient access
   history. Patient access history stays on the patient's page.

### Edge Cases

- A program with details is replaced by a new program. The details don't carry over, except for exercises in both
  programs (D2).
- A patient asks to move a visit, and the therapist then cancels it. The request clears, as today.
- The clinic's time zone changes between the request and the answer. The proposed time is stored in UTC and shown in
  clinic time.
- A patient has no sessions in the report period. The report still prints, with the program, goals and "No sessions
  in this period".
- The hosted demo is reset for v19. New access codes are issued and given out (020's reset).

## Requirements *(mandatory)*

### N1, exercise details

- **FR-001**: The current program MUST store, per exercise, optional `sets` (1–10), `reps` (1–100), `hold_seconds`
  (0–120), `frequency` (`daily` or `per_week` with `days` 1–7), and `note` (up to 200 characters). Missing values
  fall back to today's behaviour.
- **FR-002**: Changing a detail MUST edit the current assignment in place and MUST NOT change adherence history.
- **FR-003**: Adding or removing an exercise MUST start a new assignment from today, carrying the details over for
  exercises in both (D2).
- **FR-004**: The patient's Today page, exercise list and live session MUST show the details in one plain sentence,
  with the note. The live session's target MUST be the prescribed reps, else the
  goal's target reps, else the exercise's default (D1).
- **FR-005**: The AI extracts (018) MUST include the prescription. A draft prompt MUST say not to contradict it.

### N2, proposed time

- **FR-006**: A reschedule request MAY carry `requested_starts_at`: the future, within 90 days, on a 5-minute step,
  stored in UTC.
- **FR-007**: Accept MUST move the visit to the proposed time with its current length, clear the request, record
  "moved at the patient's request" in `response_note`, and refuse when the time has passed.
- **FR-008**: Accept MUST warn, and ask for confirmation, when the time overlaps another scheduled visit of the
  patient's therapist.
- **FR-009**: The Inbox, Schedule and Dashboard MUST show the proposed time with Accept, Offer another time and Keep.
  The portal's Visits MUST show the proposed time while the request is open, and the answer once there is one.

### N3, progress report

- **FR-010**: `/therapist/review/{patient}/report?period=` MUST render the sections of Story 3 from existing rules
  (`src/ptlog/review`, `adherence`, `questionnaires`, `clinic.review`) and add no new calculation.
- **FR-011**: The report MUST print cleanly with a print stylesheet, MUST use no inline style or script, and MUST
  put a table with every chart.
- **FR-012**: The report MUST exclude patient-written free text, messages and transcripts.

### N4, admin history

- **FR-013**: v19 MUST add `account_id` to staff sign-in events. Sign-in, failure (with a known username), lock-out
  and sign-out MUST record it from then on.
- **FR-014**: People → History MUST merge account events and staff sign-in events, newest first, with names
  resolved, a kind filter, and 200 rows a page. It is admin-only (403 otherwise).

### Shared

- **FR-015**: One migration, v19, MUST add `assignments.exercise_details` (JSON, default `{}`),
  `appointments.requested_starts_at` (nullable), and `admin_audit.account_id` (nullable). It MUST run on SQLite and
  libSQL, and the store tests MUST pass on both.
- **FR-016**: `scripts/seed_demo.py` MUST fill details for the demo programs, one open request with a proposed time,
  and some history.
- **FR-017**: Every new route MUST be registered through `clinic_route` with its role, and checked by the route walk:
  404 for another caseload, 403 for a non-admin on History.

## Decision Gates (owner)

- **D1, which target wins in a live session?** The prescribed reps (N1), the patient's goal target, or the exercise's
  default. **Owner's decision (13 Nov):** prescription, then goal, then default. The prescription is today's dose; a goal is where
  the patient is heading.
- **D2, adding or removing an exercise.** Either (a) the current program changes in place, which is simplest but
  makes past weeks' adherence count against the new list, or (b) a new assignment starts today with the details
  carried over for exercises in both, so past weeks keep the list they had. **Owner's decision (13 Nov):** (b). It reuses
  `assign_program` and keeps adherence honest.
- **D3, the order of the four stories.** **Owner's decision (13 Nov):** N3 first (no schema change), then the v19 migration with N1,
  then N2, then N4. That is one demo reset, after N1.

## Success Criteria

- **SC-001**: A therapist sets the details for a 3-exercise program in under a minute, and the patient sees them on
  their next page load.
- **SC-002**: A reschedule request with a proposed time is answered in one click from the Dashboard.
- **SC-003**: The report for a patient with 12 weeks of data prints to PDF from Chrome and Safari with no clipped
  chart and no navigation, and opens on the hosted demo in under 1 second warm.
- **SC-004**: An admin can tell who reassigned a patient, and who signed in, without reading the database.
- **SC-005**: The full suite and the libSQL subset pass, and the hosted demo works after one reset.

## Assumptions

- One therapist per patient (016). "The patient's therapist" in FR-008 means the caseload owner.
- A frequency is advice to the patient. Adherence still counts sessions per week from the program, as today.
- The browser's own print to PDF is good enough. No server-side PDF is made.
- Admins already have People. History adds a section, not a top-bar item.

## Out of Scope

- A calendar the patient picks free slots from, or availability rules for therapists.
- Changes to clinic-wide threshold history in History. That already shows under Tracker → Settings.
- Emailing the report, or a server-made PDF file.
- Exercise videos or pictures for the patient.
