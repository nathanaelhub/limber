# Feature Specification: Multi-Patient PT Tracker

**Feature Branch**: `003-pt-tracker`

**Created**: 2026-09-19

**Status**: Draft

**Input**: User description: "Multi-patient PT tracker: a physical therapist (PT) or PT student
manages a caseload of patients in one place, on top of the canonical session record and the
review-over-time feature. Everything reads from the record; nothing here records new engine
data. A roster shows every active patient at a glance: pseudonymous ID and label, assigned
program, days since the last session, sessions in the last 7 and 30 days, adherence to the
assigned program over the last 4 weeks as a percentage, the number of sessions pending review,
the number of open attention flags, and the next step from the most recent review; the roster
can be sorted so patients who need attention come first (open flags, then pending reviews, then
lowest adherence, then longest since last session) and filtered by program or to show only those
needing attention. A PT assigns a program to a patient from the pre-built programs already
defined in the exercise configuration (each is a named list of exercises, such as knee
rehabilitation or shoulder mobility) or a custom list of exercises, with a planned number of
sessions per week (default 3), a start date, and an optional end date; a patient has at most one
active assignment, assigning a new program ends the previous one and the history of assignments
is kept. Adherence compares what was recorded with what was planned: for each week since the
start date (up to the last 4 weeks) the number of sessions recorded against the planned sessions
per week, and whether each assigned exercise was performed at least once that week; adherence
percentage is recorded sessions divided by planned sessions over the window, capped at 100;
weeks with no sessions are listed as missed; a patient without an assignment shows no adherence.
A cross-patient review queue lists everything that needs the PT's action, oldest first within
each kind: sessions pending review, open attention flags (from the existing rules, per patient
over the last 30 days), adherence below a threshold (default 60%) for patients with an
assignment, and patients past their practice-gap threshold; each item names the patient and
links to the session or view where the action is taken; the queue shrinks as sessions are
reviewed and patterns resolve, with no separate acknowledgement state. A PT can discharge a
patient (mark inactive with a discharge date and an optional free-text reason, no identifying
information), which removes them from the active roster and queue while keeping all data, and
can reactivate them later; discharged patients are visible in a separate list. The roster can be
exported as CSV for the clinic's caseload record, named without identifying information. The
tracker is available on the command line and as a Tracker page in the web app; the existing
Patients page gains the program assignment and discharge controls. Data stays local and patients
remain pseudonymous."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See the Caseload at a Glance (Priority: P1)

A PT opens the roster and sees every active patient in one table: pseudonymous ID and label,
assigned program (or none), days since the last session, sessions in the last 7 and 30 days,
adherence over the last 4 weeks (or "no program"), sessions pending review, open attention
flags, and the next step from the most recent review. Patients who need attention sort to the
top, and the PT can filter by program or to only those needing attention.

**Why this priority**: The roster is the tracker. Every other story adds a column or an action
to it.

**Independent Test**: Register three patients with different histories (one with pending
reviews and a flag, one with nothing recent, one discharged), open the roster, and confirm each
column matches the underlying sessions and reviews, the discharged patient is absent, and the
patient with the flag sorts first.

**Acceptance Scenarios**:

1. **Given** patients A (two sessions this week, one pending review, one open flag), B (last
   session 20 days ago, all reviewed), and C (discharged), **When** the PT opens the roster,
   **Then** A and B are listed, C is not, and A's row shows 2 sessions in the last 7 days, 1
   pending review, 1 open flag, while B's shows 20 days since the last session and 0 pending.
2. **Given** the same patients, **When** the roster is sorted by attention, **Then** A comes
   before B; **and given** a patient D with 0 flags, 0 pending, and adherence 40% versus B with
   no program, **Then** D sorts above B.
3. **Given** patients on two programs, **When** the PT filters by "Knee Rehabilitation",
   **Then** only patients whose active assignment is that program are shown.
4. **Given** the PT filters to "needs attention", **When** the roster renders, **Then** only
   patients with at least one open flag, a pending review, adherence below the threshold, or a
   practice gap are shown.
5. **Given** a patient with no sessions, **When** the roster renders, **Then** the row shows
   "no sessions yet" for days since last session and zeros elsewhere.
6. **Given** the built-in "Unassigned" patient holds sessions, **When** the roster renders,
   **Then** it appears with its counts, marked as built-in, and shows no program or adherence.

---

### User Story 2 - Assign a Program (Priority: P2)

A PT assigns a program to a patient: one of the pre-built programs from the exercise
configuration (a named list of exercises) or a custom list of exercises, with planned sessions
per week (default 3), a start date (default today), and an optional end date. A patient has at
most one active assignment; assigning a new one ends the previous one the day before the new
start, and the history of assignments stays visible.

**Why this priority**: Adherence and part of the queue depend on knowing what was planned.

**Independent Test**: Assign a pre-built program, confirm it shows on the roster and the
patient's detail; assign a custom list, confirm the first assignment is ended and both appear
in the history.

**Acceptance Scenarios**:

1. **Given** the configuration defines "Knee Rehabilitation" with five exercises, **When** the
   PT assigns it to P-017 with 3 sessions per week starting today, **Then** the assignment is
   stored with the five exercises, the plan, and the dates, and the roster shows the program.
2. **Given** P-017 has an active assignment, **When** the PT assigns "Hip Strengthening" starting
   next Monday, **Then** the first assignment's end date becomes the day before that start,
   only the new one is active, and the history lists both with their dates.
3. **Given** the PT assigns a custom list, **When** they name exercises that are not in the
   configuration, **Then** the assignment is rejected naming the unknown exercises.
4. **Given** the PT enters sessions per week outside 1 to 14, or an end date before the start
   date, **When** they save, **Then** the assignment is rejected with the reason.
5. **Given** an assignment with an end date in the past, **When** the roster renders, **Then**
   the program shows as "completed" and no adherence is computed after the end date.
6. **Given** the built-in "Unassigned" patient, **When** the PT tries to assign a program,
   **Then** it is refused.

---

### User Story 3 - See Adherence to the Plan (Priority: P3)

For a patient with an active assignment, the PT sees week by week (assignment weeks of seven
days from the start date, up to the last four completed weeks plus the current week in
progress) how many sessions were recorded against the plan and which assigned exercises were
performed at least once; the adherence percentage is recorded sessions divided by planned
sessions over the completed weeks in the window, capped at 100. Weeks with no sessions are
listed as missed.

**Why this priority**: Adherence is the number that makes the roster and the queue useful for
a caseload, but it needs assignments first.

**Independent Test**: Assign a plan of 3 sessions per week starting 3 weeks ago, record 3, 1,
and 0 sessions in the three completed weeks and 2 so far this week, and confirm the weekly
table, the missed week, and an adherence of 44%.

**Acceptance Scenarios**:

1. **Given** a plan of 3 per week started 21 days ago and sessions counted 3, 1, 0 in the three
   completed weeks, **When** adherence is shown, **Then** the weekly rows read 3/3, 1/3, 0/3
   (missed), the current week shows its count as "in progress", and the percentage is 44%.
2. **Given** 5 sessions in a 3-per-week week, **When** adherence is computed, **Then** that week
   contributes 3 of 3 (capped) and the percentage never exceeds 100.
3. **Given** the assigned exercises are knee extension and partial squat, **When** a week has
   sessions with only knee extension reps, **Then** the week lists knee extension as performed
   and partial squat as not performed.
4. **Given** a session with zero counted reps, **When** adherence is computed, **Then** that
   session does not count toward the plan.
5. **Given** the assignment started 3 days ago, **When** adherence is shown, **Then** the view
   says the first week is in progress and shows no percentage yet.
6. **Given** a patient with no assignment, **When** adherence is requested, **Then** the view
   says no program is assigned.

---

### User Story 4 - Work Through a Cross-Patient Queue (Priority: P4)

The PT opens one queue of everything needing action across active patients, grouped by kind
and oldest first within each: sessions pending review, open attention flags (the existing rules
over the last 30 days, other than practice gaps), practice gaps, and low adherence (below the
threshold, default 60%) for patients with an active assignment. Each item names the patient and
says where the action is taken (the session to review, the patient's flags, or the patient's
adherence). There is no separate acknowledgement: reviewing a session or a pattern resolving
removes the item.

**Why this priority**: The queue turns the roster into a work list; it depends on reviews,
flags, and adherence being available.

**Independent Test**: Build three patients with one item of each kind, open the queue, confirm
every item appears once under the right kind with the right patient, review the pending session,
and confirm it disappears.

**Acceptance Scenarios**:

1. **Given** P-017 has two pending sessions (from 5 and 2 days ago) and P-018 has one (from 9
   days ago), **When** the queue renders, **Then** the pending kind lists P-018's session first,
   then P-017's older one, then the newer one, each with the session id and date.
2. **Given** P-017 has a form-declining flag and P-018 a practice gap, **When** the queue
   renders, **Then** the flag appears under attention flags with its message and P-018 appears
   under practice gaps with the number of days.
3. **Given** P-019 has an assignment with adherence 40%, **When** the queue renders, **Then**
   P-019 appears under low adherence with 40% against the 60% threshold; **and given** the
   threshold is changed to 30%, **Then** the item is gone.
4. **Given** the PT reviews a pending session, **When** the queue is reopened, **Then** that
   item is gone and the totals per kind are updated.
5. **Given** a discharged patient with pending sessions, **When** the queue renders, **Then**
   none of that patient's items appear.
6. **Given** nothing needs action, **When** the queue renders, **Then** it says the caseload is
   up to date.

---

### User Story 5 - Discharge and Reactivate (Priority: P5)

A PT discharges a patient with a discharge date (default today) and an optional reason in free
text (no identifying information), which removes the patient from the active roster and the
queue while keeping every session, review, goal, and assignment. Discharged patients appear in
a separate list and can be reactivated.

**Why this priority**: A caseload changes; without discharge the roster fills with finished
courses of care.

**Independent Test**: Discharge a patient, confirm they leave the roster and queue and appear
in the discharged list with the reason, reactivate, confirm they are back with all data.

**Acceptance Scenarios**:

1. **Given** an active patient with sessions and a pending review, **When** the PT discharges
   them with reason "goals met", **Then** the roster and queue no longer show them, the
   discharged list shows the ID, discharge date, and reason, and every session and review is
   still readable.
2. **Given** a discharge reason containing a name-like phrase, a numeric date, or a long digit
   run, **When** the PT saves, **Then** the discharge is rejected with the rule violated.
3. **Given** a discharged patient, **When** the PT reactivates them, **Then** they return to
   the roster with their history and their assignment history intact (an assignment that had
   ended stays ended).
4. **Given** the built-in "Unassigned" patient, **When** the PT tries to discharge it, **Then**
   it is refused.
5. **Given** a discharged patient, **When** a session is recorded for them anyway, **Then** the
   session is stored and the patient stays discharged.

---

### User Story 6 - Export the Roster (Priority: P6)

The PT exports the active roster as CSV for the clinic's caseload record. The file carries the
roster columns and is named with only the generation time.

**Why this priority**: Useful for the chart, depends on everything above.

**Independent Test**: Export with three patients and confirm one row each with values equal to
the roster.

**Acceptance Scenarios**:

1. **Given** three active patients, **When** the PT exports the roster, **Then** the CSV has a
   header naming each column with its unit and one row per active patient with the same values
   the roster shows, and the file name contains only "roster" and the generation time.
2. **Given** the roster is filtered, **When** the PT exports, **Then** the export contains all
   active patients regardless of the filter.

---

### Edge Cases

- A patient with an assignment but no sessions at all: adherence 0% once the first week has
  completed, every week listed as missed.
- Assignment start date in the future: the roster shows the program as "starts on <date>" and
  no adherence is computed until then.
- Two assignments in the history that overlap because of a back-dated start: the newer
  assignment wins and the older one's end date is set to the day before the newer start, even if
  that ends it before it started (shown as "superseded").
- A session recorded on the assignment start day counts in week 1.
- Exercises removed from the configuration after assignment: the assignment keeps its exercise
  keys and shows them by key when no display name exists.
- The adherence threshold is set to a value outside 1 to 100: rejected.
- Clock and week boundaries: a session at 23:59 on the last day of a week belongs to that week.
- Roster with many patients (50 or more): still renders within the performance target.

## Requirements *(mandatory)*

### Functional Requirements

**Roster**

- **FR-001**: The roster MUST list every active patient (not discharged) with: pseudonymous ID,
  label, active program name or "none", days since the last session or "no sessions yet",
  sessions in the last 7 days, sessions in the last 30 days, adherence percentage over the last
  4 completed assignment weeks or "no program" / "first week in progress", pending reviews
  count, open attention flags count (rules from the review feature over the last 30 days), and
  the next step from the most recent review or "none".
- **FR-002**: The roster MUST support an attention sort: patients with more open flags first,
  then more pending reviews, then lower adherence (patients without a program after those with
  one), then more days since the last session.
- **FR-003**: The roster MUST support filtering by program and filtering to patients that need
  attention (open flag, pending review, adherence below the threshold, or practice gap).
- **FR-004**: The built-in "Unassigned" patient MUST appear on the roster when it holds sessions,
  marked as built-in, and MUST NOT accept a program or a discharge.

**Programs and assignments**

- **FR-005**: The system MUST offer the pre-built programs defined in the exercise configuration
  (identifier, name, description, ordered exercise keys) and a custom program built from
  exercise keys that exist in the configuration; unknown keys MUST be rejected by name.
- **FR-006**: Users MUST be able to assign a program to a patient with sessions per week (1 to
  14, default 3), a start date (default today), and an optional end date not before the start
  date.
- **FR-007**: A patient MUST have at most one active assignment; assigning a new program MUST set
  the previous assignment's end date to the day before the new start and keep it in the history.
- **FR-008**: Users MUST be able to view a patient's assignment history with program, exercises,
  plan, start and end dates, and status (active, completed, superseded, or scheduled).

**Adherence**

- **FR-009**: Adherence MUST be computed over assignment weeks (7-day periods from the start
  date): for each of the last 4 completed weeks and the current week, the number of sessions
  with at least one counted rep against the planned sessions, and for each assigned exercise
  whether at least one counted rep of it was recorded that week.
- **FR-010**: The adherence percentage MUST be the sum over completed weeks in the window of
  min(recorded, planned) divided by the sum of planned, as a whole-number percentage; it MUST be
  absent when no week has completed or no program is assigned.
- **FR-011**: A week with no counting sessions MUST be marked missed; a session on the start day
  MUST count in week 1; a session at any time on a week's last day MUST count in that week.
- **FR-012**: Adherence MUST NOT be computed after an assignment's end date or before its start.

**Queue**

- **FR-013**: The queue MUST list, for active patients only: pending reviews (per session,
  oldest session first), attention flags (every rule except practice gap, over the last 30 days,
  oldest triggering session first), practice gaps (per patient, longest gap first), and low
  adherence (per patient with an active assignment and a computed percentage below the
  threshold, lowest first), each item with the patient ID and the target session or view.
- **FR-014**: Users MUST be able to set the adherence threshold (1 to 100, default 60) for the
  installation.
- **FR-015**: The queue MUST have no acknowledgement state; items disappear when the underlying
  condition is gone.

**Discharge**

- **FR-016**: Users MUST be able to discharge an active patient with a discharge date (default
  today) and an optional reason validated with the same identifying-text rules as notes, and to
  reactivate a discharged patient; discharge MUST keep all of the patient's data.
- **FR-017**: Discharged patients MUST be excluded from the roster and queue and listed
  separately with ID, label, discharge date, and reason.

**Export**

- **FR-018**: Users MUST be able to export the active roster as CSV with a header row naming each
  column and its unit, one row per active patient, values equal to the roster, named
  `roster_<generation time>` with no patient identifiers in the name.

**Scope and privacy**

- **FR-019**: The tracker MUST read only from the canonical record and the review feature and
  MUST NOT change how sessions are recorded.
- **FR-020**: All tracker data MUST be stored locally with the record and identify patients only
  by pseudonymous ID.
- **FR-021**: Deleting a patient MUST remove their assignments and discharge record.

### Key Entities

- **Program**: a named, ordered list of exercise keys; pre-built ones come from the
  configuration, custom ones are defined at assignment time.
- **Assignment**: a program for a patient with sessions per week, start date, optional end date;
  status derived from dates and supersession; a patient has at most one active.
- **Adherence Week**: a derived 7-day period of an assignment with recorded and planned session
  counts, the set of exercises performed, and a missed flag.
- **Roster Row**: derived per active patient; the columns of FR-001.
- **Queue Item**: derived; kind (pending_review, attention_flag, practice_gap, low_adherence),
  patient ID, target (session id or view), age, and a one-sentence description.
- **Discharge**: per patient; discharge date and optional reason; absent when active.
- **Tracker Settings**: adherence threshold (default 60).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every roster column equals the value recomputed from the patient's sessions,
  reviews, flags, and assignment, for 100% of patients in a seeded caseload.
- **SC-002**: A caseload of 50 active patients with 20 sessions each renders the roster and the
  queue in under 3 seconds each.
- **SC-003**: Adherence for a constructed history equals the hand-computed weekly counts and
  percentage, including the capped and missed cases.
- **SC-004**: Every queue item names a patient and a target, appears exactly once, and
  disappears after the action that resolves it.
- **SC-005**: A discharged patient contributes zero roster rows and zero queue items while all
  their sessions and reviews remain readable.
- **SC-006**: The roster CSV contains no patient identifier other than the pseudonymous ID and
  label, and its file name contains no patient identifier.
- **SC-007**: A PT can assign a program, read adherence, and clear one queue item in under three
  minutes on first use.

## Assumptions

- **Weeks are assignment weeks**, seven days from the start date, not calendar weeks; this
  keeps adherence independent of which weekday a program starts.
- **The current week is shown but not scored**; the percentage uses completed weeks only, so a
  patient is not penalised on Monday for a plan of three sessions.
- **A session counts once**, regardless of how many assigned exercises it contains, and only if
  it has at least one counted rep.
- **Exercise matching is by configuration key**, which recorded sets already carry; left and
  right variants are distinct keys.
- **The adherence threshold is one value per installation**, not per patient; the practice-gap
  threshold stays per patient as in the review feature.
- **Flags on the queue use the review feature's rules unchanged** over a fixed 30-day window.
- **Assignment history is kept but not editable**; a mistake is fixed by assigning again.
- **Discharge does not block recording**; a session recorded for a discharged patient is kept
  and the patient stays discharged (the PT may reactivate).
- **Programs from the configuration are read-only**; editing them is a configuration change,
  not a tracker feature.
