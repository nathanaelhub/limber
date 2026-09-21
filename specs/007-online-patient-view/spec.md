# Feature Specification: Online Patient View

**Feature Branch**: `007-online-patient-view`

**Created**: 2026-09-21

**Status**: Draft

**Input**: User description: "Everything so far is the therapist's view. Patients should be able
to use PT Assist at home over the internet, from their own device: see today's assigned program,
do a guided camera session with rep count and form feedback that is recorded under their ID, see
their progress over time, and see their adherence streak. First version is for demo and consented
study participants, not real clinic patients. Body-pose detection runs in the patient's browser
so video never leaves the home. It is built now to run on one machine, reachable on localhost or
through a temporary tunnel; permanent hosting is decided later. The patient signs in with an
access code the therapist generates and can revoke; no email, name, or password is stored. It is
a separate launch from the therapist app and contains no therapist pages."

## Constitution Check (Principle III, networked feature)

| Requirement of Principle III (v1.1.0) | This feature |
|----------------------------------------|--------------|
| Explicit, separately specified, opt-in | This spec. The patient service does not run unless the therapist starts it, and a patient cannot sign in until the therapist issues that patient a code. |
| What crosses the network | From the patient's device: the access code at sign-in; during a session, 17 body-point positions with confidence values per frame, the frame size, and start, next, and stop requests. To the patient's device: the patient's own program for today, rep count, phase, angle, form status and feedback messages, the patient's own progress and adherence summaries. |
| What never crosses the network | Camera video or images; names, labels, notes, contact details; therapist reviews and notes; attention flags; thresholds; any other patient's data or ID. |
| Who may use it | Demo users and consented study participants only. Use with real clinic patients is out of scope until a compliance review approves it; the sign-in page and the documentation say so. |
| Off until turned on for a specific patient | A code is issued per patient, by the therapist, and can be revoked at any time. |
| Only the patient's own data | The patient's identity comes from the sign-in alone; no request names a patient. |
| Video stays on the device | Pose detection runs in the browser. |
| Pseudonymous IDs, deletion | No identifying detail is collected; deleting a patient removes their codes, sign-ins, and access history. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Get Access and See Today's Program (Priority: P1)

The therapist issues an access code for a patient and gives it to them with the link. At home the
patient opens the link, reads a short notice of what is and is not sent, enters the code, and sees
today's program: the assigned exercises in order, the target reps for each, and which are already
done today. The therapist can revoke the code at any time.

**Why this priority**: Nothing else is reachable without safe access, and "what do I do today"
is the first thing a patient needs.

**Independent Test**: Issue a code for a patient with an assigned program, sign in with it, and
see that patient's exercises and targets; a wrong, expired, or revoked code is refused; nothing on
any page or response mentions another patient.

**Acceptance Scenarios**:

1. **Given** P-017 has the Knee Rehabilitation program assigned, **When** the therapist issues a
   code, **Then** the code is shown once in the form `XXXX-XXXX-XXXX`, and only a non-reversible
   form of it is stored.
2. **Given** a valid code, **When** the patient signs in, **Then** they see the program's
   exercises by display name with target reps (their goal's target when one is set, otherwise the
   exercise's default) and a done-today mark for each exercise with at least one counted rep today.
3. **Given** a wrong code, **When** sign-in is attempted, **Then** it is refused with a message
   that does not say whether the code exists, and after five failures in fifteen minutes further
   attempts from that client are refused for a growing period.
4. **Given** the therapist revokes a code or issues a new one, **When** the patient next loads a
   page or sends a frame, **Then** they are signed out and any running session is ended as
   interrupted.
5. **Given** a patient with no assigned program, **When** they sign in, **Then** they see a plain
   message that their therapist has not assigned a program yet.
6. **Given** a discharged patient or the built-in unassigned patient, **When** the therapist tries
   to issue a code, **Then** it is refused; a discharged patient with an old code cannot sign in.

---

### User Story 2 - Guided Session at Home (Priority: P1)

The patient starts today's session. Their browser asks for the camera, finds their body points on
the device, and shows their skeleton over the mirrored video. The service counts reps and gives
form feedback with the same engine the clinic uses, moves through the program's exercises, and
records the session under their ID as it happens. Stopping ends the session; a lost connection
leaves an interrupted session with everything recorded so far.

**Why this priority**: This is the reason for a home view: supervised-quality practice between
visits, visible to the therapist.

**Independent Test**: Feed a recorded series of body points for three reps of two exercises
through the session connection; the stored session has two sets with three reps each, a switch
between them, the patient's ID, and a marker that it was recorded at home.

**Acceptance Scenarios**:

1. **Given** the patient is signed in with a program, **When** they start a session, **Then** a
   running session is created for them starting at the first exercise not yet done today, with
   source "webcam" and an origin marker "portal", and the screen shows exercise, target, rep
   count, phase, form status, and up to two feedback messages.
2. **Given** a session is running, **When** the engine counts a rep, **Then** the rep is recorded
   within one second and the patient's count updates.
3. **Given** the target is reached or the patient presses next, **When** the next exercise starts,
   **Then** the current set closes, a switch is recorded, and the next exercise begins with its
   own target; after the last exercise the session can only be stopped.
4. **Given** the patient presses stop, **Then** the session ends as completed and a summary
   (exercises done, reps, average form score out of 100) is shown.
5. **Given** the connection drops or the tab closes, **Then** the session is marked interrupted
   with every rep recorded before the drop.
6. **Given** the patient already has a running home session on another device, **When** a second
   one is started, **Then** it is refused with a plain message.
7. **Given** another patient, or the therapist in the clinic, starts a session at the same time,
   **Then** neither session interrupts the other.
8. **Given** the device cannot keep up (fewer than 12 frames per second for five seconds),
   **Then** the patient is told their device is running slowly and the session is marked as
   low-rate for the therapist.
9. **Given** malformed or oversized frame data, **Then** it is ignored, and after ten bad messages
   the connection is closed and the event is logged.

---

### User Story 3 - Progress Over Time (Priority: P2)

The patient sees, for each of their exercises, how their range of motion and form score have
changed across sessions and how close they are to the goal their therapist set, in plain language
with units. They never see attention flags, thresholds, or therapist notes.

**Independent Test**: For a patient with six sessions and a ROM goal, the progress view lists the
sessions' average ROM and form, the change from first to latest, and the percentage of the goal
reached; it contains no flag, note, threshold, or label.

**Acceptance Scenarios**:

1. **Given** sessions exist, **Then** each exercise shows per-session average range of motion
   (degrees) and average form score (0-100), the change from first to latest, and each number's
   plain-language meaning.
2. **Given** a range-of-motion goal, **Then** progress toward it is shown as a percentage and a
   sentence such as "86° of your 95° goal".
3. **Given** fewer than two sessions of an exercise, **Then** it says more sessions are needed
   before a trend can be shown.
4. **Given** sessions recorded at home and in the clinic, **Then** each point says where it was
   recorded, because home and clinic numbers can differ slightly (see Assumptions).

---

### User Story 4 - Adherence Streak (Priority: P2)

The patient sees how many sessions they have done this week against the plan and how many weeks
in a row they met it.

**Acceptance Scenarios**:

1. **Given** a program of three sessions per week and two counted this week, **Then** the patient
   sees "2 of 3 sessions this week".
2. **Given** the last three complete weeks met the plan and the one before did not, **Then** the
   streak is three weeks; the week in progress extends the streak only once it meets the plan and
   never breaks it.
3. **Given** no program, **Then** no streak is shown.

---

### User Story 5 - Therapist Control and Safe Operation (Priority: P3)

The therapist starts and stops the patient service, sees which patients have access and when they
last used it, and can review the access history. The documentation explains how to reach the
service from a phone securely.

**Acceptance Scenarios**:

1. **Given** the Patients page, **Then** each patient shows home access status (none, active until
   a date, expired, revoked) and last use, with issue and revoke controls.
2. **Given** the access history, **Then** it lists code issued and revoked, sign-ins and failures,
   lock-outs, and sessions started and ended, with time and patient, and never the code or the
   visitor's address.
3. **Given** the service is started on an address other than this machine without a secure
   connection, **Then** it refuses unless the therapist explicitly overrides, and warns that
   cameras will not work.

---

### User Story 6 - One Entry Page with Two Doors (Priority: P1, added 2026-09-21 at the owner's request)

Limber has one front page. It shows the brand and two choices: "I'm a patient" (enter the access
code) and "Therapist sign-in" (enter the therapist password). A patient lands on today's plan; a
therapist lands in the therapist app. Until now the therapist app had no sign-in at all, which is
acceptable on a private machine and not acceptable once anything is reachable from outside.

**Why this priority**: One address to hand out, and the therapist app must not be open to anyone
who finds its address once the platform leaves the local machine.

**Independent Test**: With a therapist password set, the front page offers both doors; the right
password opens the therapist app, a wrong one is refused like a wrong code; opening the therapist
app's address directly shows a sign-in instead of patient data.

**Acceptance Scenarios**:

1. **Given** the front page, **Then** it shows both doors, and the patient notice of what is sent.
2. **Given** a therapist password has been set from the command line, **When** the therapist enters
   it on the front page, **Then** they are taken to the therapist app, already signed in, through a
   single-use pass that is valid for one minute.
3. **Given** a wrong password, **Then** it is refused with a generic message, counted by the same
   attempt limits as patient codes, and recorded in the therapist access history.
4. **Given** a therapist password is set, **When** anyone opens the therapist app directly without a
   valid pass or sign-in, **Then** no page, patient ID, or number is shown, only the sign-in.
5. **Given** no therapist password has been set (a private machine), **Then** the therapist app
   opens as it always has, and the front page's therapist door says a password has not been set up.
6. **Given** a signed-in therapist, **When** they sign out or eight hours pass, **Then** the
   therapist app asks for sign-in again.

### Edge Cases

- The therapist's machine is off or the service is not running: the patient sees that the service
  is unavailable; nothing is lost.
- The pose model files are not installed: the service says how to install them; sign-in, program,
  and progress still work; the session page says setup is incomplete.
- A patient's exercise is removed from the configuration: it is skipped with a note.
- No person in view, or poor lighting: the screen says it cannot see the patient; nothing is
  recorded for those frames.
- The clock on the patient's device is wrong: the service's clock is used for every stored time.
- A patient is deleted while signed in: they are signed out and their access data is removed.
- Two patients at home at once, or home and clinic at once: sessions do not affect each other.
  This changes feature 004's rule "one running session per installation" to "one running session
  per patient".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A therapist MUST be able to issue, list, and revoke one access code per patient from
  the command line and the Patients page. Codes MUST be 12 characters from an unambiguous
  alphabet shown as three groups of four, expire after 90 days by default, be shown once, and be
  stored only in a non-reversible form. Issuing a new code MUST revoke the previous one. Codes
  MUST NOT be issued to the built-in or to discharged patients.
- **FR-021**: The front page MUST offer a patient door (access code) and a therapist door (password).
  The therapist password MUST be set only from the command line on the machine itself, MUST be at
  least 12 characters, and MUST be stored only as a salted slow hash. Therapist sign-in MUST use the
  same attempt limits as patient codes and a generic refusal message.
- **FR-022**: When a therapist password is set, the therapist app MUST show nothing but a sign-in
  until the visitor presents a valid single-use pass from the front page (valid one minute) or the
  password itself; a therapist sign-in MUST end on sign-out or after eight hours. When no password
  is set, the therapist app MUST behave as before. Therapist sign-ins, failures, and lock-outs
  MUST be recorded in a therapist access history without addresses or passwords.
- **FR-002**: The patient service MUST be a separate launch containing no therapist pages (the
  front page's therapist door only checks the password and hands over to the therapist app), and
  MUST listen only on this machine unless the therapist chooses otherwise; listening elsewhere
  without a secure connection MUST require an explicit override.
- **FR-003**: Sign-in MUST use the access code alone, MUST NOT reveal whether a code exists, MUST
  limit failed attempts (five per fifteen minutes per client, then a growing lock-out, plus a
  global limit), and MUST refuse expired, revoked, and discharged-patient codes.
- **FR-004**: After sign-in every page, response, and message MUST contain only the signed-in
  patient's own data. No request MAY name a patient. Labels, notes, reviews, flags, thresholds,
  and other patients' IDs MUST never be sent.
- **FR-005**: The patient MUST see today's program: exercises in assignment order by display name,
  target reps (goal target, else the exercise default), done-today status, and a plain message
  when no program is assigned.
- **FR-006**: A guided session MUST run the same exercise engine as the clinic on body points
  detected in the patient's browser, record reps, partial reps, form events, and exercise
  switches through the existing recording path under the patient's ID with source "webcam" and
  origin "portal", and show exercise, target, rep count, phase, angle, form status, and up to two
  feedback messages.
- **FR-007**: The session MUST move through the program's exercises in order, starting at the
  first not done today, on target reached or on the patient's request; the patient MUST NOT be
  able to choose exercises outside their program.
- **FR-008**: Stop MUST end the session as completed and show a summary; a lost connection,
  revoked code, sixty seconds without frames, or sixty minutes of session MUST end it
  (interrupted for lost connection and revocation) with every recorded event kept.
- **FR-009**: Camera video and images MUST NOT leave the patient's device. Body points MUST be
  sent at a steady nominal 15 frames per second; the service MUST use its own frame count and
  clock for everything it stores, MUST validate every message (17 points of three finite numbers,
  sensible frame size, size limit), and MUST cap the accepted rate.
- **FR-010**: Body points MUST be scaled uniformly to the frame height the form checks were
  calibrated on before they reach the engine, without changing angles or swapping left and right.
- **FR-011**: Home sessions MUST record how they were captured (nominal and observed frame rate,
  dropped frames, pose model and version) and MUST be marked low-rate when the observed rate
  stays under 12 frames per second for five seconds.
- **FR-012**: A patient MUST have at most one running home session; starting a session MUST
  supersede only that same patient's running sessions, never another patient's.
- **FR-013**: The patient MUST see progress per exercise: per-session average range of motion and
  form score with units and plain-language meanings, change from first to latest, progress toward
  a range-of-motion goal, where each session was recorded, and a plain message when there are too
  few sessions.
- **FR-014**: The patient MUST see sessions done this week against the plan and the number of
  consecutive complete weeks that met the plan.
- **FR-015**: An access history MUST record code issued and revoked, sign-in success and failure,
  lock-out, sign-out, and session start, end, and refusal, with time and patient, and MUST NOT
  store the code or the visitor's network address in readable form. The therapist MUST be able to
  list it.
- **FR-016**: Deleting a patient MUST remove their codes, sign-ins, and access history; changing a
  patient's ID MUST carry them along.
- **FR-017**: The sign-in page MUST state in plain language what is sent and what is not, and
  that this version is for demo and study use.
- **FR-018**: The pose model files MUST be served by the patient service itself, not fetched from
  third parties by the patient's browser.
- **FR-020**: Home and clinic sessions MUST NOT be mixed when numbers are compared across
  sessions. Trends, first-to-latest changes, goal progress, session comparison, and every attention
  rule that compares sessions MUST be evaluated separately for sessions recorded in the clinic and
  sessions recorded at home, each needing its own minimum number of sessions, in the therapist's
  views and the patient's. Every place that lists sessions MUST show where each was recorded.
  Counts that do not compare measurements (sessions per week, adherence, done today, pending
  reviews, practice gap) use all sessions.
- **FR-019**: With the patient service not in use, every existing therapist feature MUST behave as
  before, except the change in FR-012.

### Key Entities

- **Access Code**: belongs to one patient; non-reversible stored form; issued, expiry, revoked,
  and last-used times.
- **Patient Sign-in**: an open sign-in of one patient on one device, with idle and absolute limits.
- **Access History Entry**: time, patient (when known), event, and a non-reversible client marker.
- **Home Session**: an ordinary session with origin "portal" and capture details.
- **Today's Program, Progress, Streak**: views derived from existing assignments, sessions, goals,
  and adherence; nothing new is stored for them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a recorded series of body points, the home session stores 100% of the reps,
  partial reps, and form events the clinic path stores for the same series at the same rate.
- **SC-002**: 0 responses or messages contain another patient's ID or a forbidden field, checked
  across every route for a seeded caseload.
- **SC-003**: 100% of wrong, expired, revoked, and discharged-patient codes are refused, and the
  sixth failed attempt within fifteen minutes is refused without checking the code.
- **SC-004**: 0 sessions of other patients change status when a patient starts or loses a home
  session.
- **SC-005**: After a dropped connection, every rep recorded more than one second earlier is
  present and the session is marked interrupted.
- **SC-006**: A first-time patient can sign in and start today's session in under two minutes.
- **SC-007**: Every number shown to a patient has a unit and a plain-language meaning.
- **SC-008**: On the two sample clips, the browser pose model yields the same rep counts as the
  clinic model, and the measured differences in range of motion and form score are documented.
  (Measured 2026-09-21: rep counts identical; see Assumptions. An earlier draft required range of
  motion within 5 degrees; the measurement showed that is not achievable, which led to FR-020.)
- **SC-009**: 0 attention flags and 0 trend changes are computed across a mix of home and clinic
  sessions.

## Assumptions

- **Study use only** in this version; real clinic patients need a compliance review first.
- **Home range-of-motion numbers are not comparable with clinic numbers.** The browser's pose
  model (MoveNet) was run on every frame of the two sample clips and its body points replayed
  through the engine next to the clinic model's (2026-09-21). Rep counts were identical (4 and 4)
  at 30 and 15 frames per second, average form score differed by 0.6 to 2.1 points, and rep
  duration by 0.0 s. Average range of motion differed by model: squat 117.3° (clinic) against
  111.9° (Lightning) and 114.7° (Thunder); push-up 84.9° against 98.0° and 108.9°. The joint angle
  differed frame by frame by 5° to 9° on average (95th percentile 12° to 19°). There is no ground
  truth in these clips, so this says the models disagree, not which one is right. Because the
  range-of-motion regression rule fires at 10°, FR-020 keeps home and clinic sessions apart.
  Lightning is the default model (closer on push-ups, lighter on phones).
- **The lower home frame rate has a smaller effect.** Measured on the two sample clips
  (2026-09-21) by replaying the clinic model's body points through the engine at lower rates: at
  15 frames per second rep counts were identical, average range of motion moved by at most 2.3°,
  average form score fell by 1.3 to 1.9 points, and rep duration rose by 0.04 s. At 10 frames per
  second squat range of motion read 6.9° low, which is why 12 is the floor. The sample is small
  (two clips, fast reps). The difference caused by the browser's pose model is described
  above. Progress therefore says where each session was recorded.
- **One machine**: the patient service and the therapist app share one record on one machine;
  permanent hosting is a later decision.
- **Reaching it from a phone** needs a secure connection; the recommended path is a temporary
  tunnel, and the tunnel's operator can see the body-point numbers in transit.
- **One therapist password per installation** in this version; named therapist accounts are a later
  feature. A forgotten password is replaced from the command line.
- **No accounts, no recovery**: a lost code is replaced by the therapist.
- **A second device is refused** rather than taking over a running session.
- **The patient sees their pseudonymous ID** on screen, so they can quote it to their therapist.
- **No reset control for patients**; resetting the counter stays a therapist action.
