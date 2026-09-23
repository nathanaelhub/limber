# Feature Specification: Installable App and Pain Check-ins

**Feature Branch**: `010-installable-app-checkins`

**Created**: 2026-09-23

**Status**: Approved by the owner's plan approval on 2026-09-23

**Input**: Owner's plan (2026-09-23): patients use Limber on their phones outside therapy as an
installable web app, and log pain and symptom check-ins that the PT sees. This is the first of five
features (010 to 014) in that plan; video clips, diary and logs, questionnaires, and voice notes follow.

## Constitution Check (Principle III, networked feature, v1.2.0)

| Requirement | This feature |
|-------------|--------------|
| What crosses the network | Check-in answers (pain 0-10, location from a fixed list, stiffness and swelling levels, an optional short note), when they were recorded, and the patient's own pain history back to them. |
| What never does | Anything of another patient; therapist notes, reviews, flags, thresholds; video or audio (none in this feature). |
| Who may use it | Demo and consented study participants only. |
| Off until turned on | Check-ins are part of the patient view a therapist already gave access to by issuing a code; no extra switch. |
| Only the patient's own data | Identity from the sign-in alone; no request names a patient. |
| Device sign-in | The installed app may stay signed in on the device for 30 days, at most three devices, revocable at once by the therapist. |
| Free text | The optional note goes through the same warn-and-allow privacy check as messages. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Install Limber on the Phone (Priority: P1)

A patient opens the Limber address on their phone, is offered "Add Limber to your home screen"
(with plain steps on iPhone, where the browser offers no prompt), and from then on opens Limber
like an app: full screen, its own icon, and still signed in the next morning.

**Independent Test**: With phone emulation, the page offers install, the app manifest and icon are
served by Limber itself, the shell loads with the network off, and a sign-in made on the device is
still valid after 20 days but not after 31, and not after the therapist revokes the code.

**Acceptance Scenarios**:

1. **Given** a signed-in patient on a phone, **Then** the page shows an install hint with the steps
   for that phone, once, and can be dismissed.
2. **Given** the installed app is opened with no connection, **Then** Today's plan as last seen is
   shown with a "not connected" notice; sessions and progress say they need a connection.
3. **Given** a sign-in made on the phone, **When** the app is opened 20 days later, **Then** the
   patient is still signed in; after 30 days, or after the therapist revokes or reissues the code,
   they are asked for the code.
4. **Given** the patient signs out, **Then** nothing of theirs remains readable on the device.

### User Story 2 - Pain and Symptom Check-in (Priority: P1)

Before and after a guided session, and any time from Today, the patient answers a 30-second check-in:
pain now (0-10), where (a fixed list of body areas), stiffness (none, mild, moderate, severe),
swelling (same), and an optional note. Offline check-ins are saved on the phone and sent when the
connection returns.

**Independent Test**: Record check-ins over several days; the patient's progress page shows the pain
trend; a check-in made offline appears for the PT after reconnecting, once, at its recorded time.

**Acceptance Scenarios**:

1. **Given** a session is about to start, **Then** the patient is asked the check-in first; on finish,
   the "after" check-in; both are linked to that session. Either can be skipped.
2. **Given** Today, **Then** "How are you feeling?" opens a standalone check-in.
3. **Given** a note that looks like it contains a name, date, record number, phone number, or email,
   **Then** the patient is warned and may edit or send anyway; the choice is recorded.
4. **Given** the phone is offline, **When** a check-in is saved, **Then** it is queued with its
   recorded time and sent when a connection returns; sending twice never creates two entries.
5. **Given** the progress page, **Then** pain over time is shown with its meaning, alongside the
   exercise trends.

### User Story 3 - The PT Sees Check-ins and Is Told When Pain Rises (Priority: P1)

The therapist sees each patient's check-ins beside their sessions: a pain trend, before-and-after
pairs per session, and notes. A "pain rising" attention flag fires when the latest pain score is well
above the patient's recent average, or is high in itself; both thresholds are configurable like the
existing ones. Patients with a pain flag appear in the work queue.

**Acceptance Scenarios**:

1. **Given** check-ins for P-017, **Then** the Review page has a "From the patient" tab with the pain
   trend, a table of check-ins (time, before or after which session, scores, note), and definitions.
2. **Given** the latest pain score is 3 or more points above the mean of the previous three, or is
   7 or more, **Then** a `pain_rising` or `pain_high` flag appears in flags, the queue, and the roster.
3. **Given** the thresholds page, **Then** `pain_rise` (points, default 3, 1-9) and `pain_high`
   (points, default 7, 1-10) are listed as whole-patient thresholds (not per exercise).
4. **Given** a note with a privacy warning, **Then** the PT sees the marker and can remove the note.

### Edge Cases

- The phone's clock is wrong: a queued check-in's recorded time is accepted only within the last
  7 days and not in the future; otherwise the receive time is used and the entry is marked.
- A shared phone: the offline snapshot and queue are keyed by patient and wiped on sign-out and on
  any refused request.
- Check-ins from a discharged patient are refused.
- Two check-ins within a minute are allowed (before and after a very short session).

## Requirements *(mandatory)*

- **FR-001**: Limber MUST be installable from the phone's browser: an app manifest and icons served by
  Limber, a full-screen standalone display, and an install hint with steps for iPhone and Android.
- **FR-002**: The app shell (pages, styles, scripts, icons) MUST work offline after the first visit;
  API responses MUST never be cached on the device beyond a per-patient snapshot of Today's plan that
  is wiped on sign-out or on any refused request.
- **FR-003**: A sign-in from the patient app MUST last 30 days of calendar time regardless of idle
  time, at most three per patient (oldest removed), and MUST end at once when the therapist revokes or
  reissues the code. The therapist app's own sign-in is unchanged.
- **FR-004**: A check-in MUST record pain (whole number 0-10), body area (fixed list), stiffness and
  swelling (none, mild, moderate, severe), an optional note of up to 500 characters, the recorded time,
  the receive time, whether it was before or after a session (and which) or standalone, and a client
  id that makes resending idempotent.
- **FR-005**: Every check-in field MUST have a unit and a plain-language meaning shown to the patient
  and the PT.
- **FR-006**: The optional note MUST pass the messages privacy check (warn, edit or send anyway,
  choice recorded); the PT MUST be able to remove a note, leaving a marker.
- **FR-007**: Check-ins recorded offline MUST be queued on the device with their recorded time and sent
  when connected; a recorded time in the future or older than 7 days MUST be replaced by the receive
  time and the entry marked.
- **FR-008**: The patient's progress page MUST show pain over time; the PT's Review page MUST show a
  "From the patient" tab with the trend, the check-in table, and definitions.
- **FR-009**: Two whole-patient thresholds MUST be added to the registry: `pain_rise` (points, default 3,
  1-9) and `pain_high` (points, default 7, 1-10); rules `pain_rising` and `pain_high` MUST evaluate the
  patient's check-ins, state the threshold in their evidence, and appear in flags, the queue, and the
  roster's needs-attention mark.
- **FR-010**: No request MAY name a patient; the no-leak test MUST cover every new route; check-in
  events MUST be recorded in the access history without note text.
- **FR-011**: Deleting a patient MUST delete their check-ins; changing an ID MUST carry them.
- **FR-012**: With no check-ins recorded, every existing result MUST be unchanged.

### Key Entities

- **Entry**: a patient's structured report; kind `checkin` here (later kinds: questionnaire,
  medication, sleep); recorded and received times; optional session link and phase; score (pain);
  payload; client id; warned and reviewed marks.
- **Device sign-in**: the existing sign-in with a 30-day lifetime and a device flag.

## Success Criteria

- **SC-001**: A patient completes a check-in in under 45 seconds on a phone.
- **SC-002**: 100% of offline check-ins arrive exactly once after reconnecting.
- **SC-003**: 0 responses contain another patient's data (no-leak test over every route).
- **SC-004**: A pain rise of 3 points over the previous three check-ins produces a flag within one page load.
- **SC-005**: With no check-ins, flags, roster, queue, and exports equal feature 009's.

## Assumptions

- Body areas: neck, shoulder, elbow, wrist or hand, back, hip, knee, ankle or foot, other.
- The "before" check-in is optional; skipping never blocks a session.
- No push notifications or reminders in this feature.
