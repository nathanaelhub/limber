# Feature Specification: Unified PT Session Log

**Feature Branch**: `001-unified-session-log`

**Created**: 2026-09-14

**Status**: Draft

**Input**: User description: "Unified PT session log: a single canonical record of
physical-therapy sessions that every other feature reads from. A physical therapist or PT
student registers a patient under a pseudonymous ID with an optional short label and free-text
notes (no names, dates of birth, or medical record numbers). They then run a session for that
patient against the existing exercise engine, from a webcam or an uploaded video, exactly as
they do today. Every session captures: the patient, start and end time, the source (webcam or
video), and each exercise set performed (exercise name, side, target reps). Within a set it
captures every completed rep with its metrics (rep number, minimum and maximum joint angle,
range of motion in degrees, duration in seconds, form score 0-100, timestamp), every partial
rep with its reason, every form feedback event (severity, message, timestamp), exercise
switches, counter resets, and a session-end summary (total reps, average form score, average
range of motion, duration). The PT can open any session and read its full event log, browse a
patient's session history newest first, and export any session in three formats generated from
the same record: the existing PTA-Log pipe-delimited text format, the existing observation JSON
format, and CSV. The four existing loggers (numbered text log files, PTA raw text logger,
observation JSON logger, session tracker JSON/CSV) are retired and replaced by this single
writer, and each legacy format is reproduced as an export so nothing downstream breaks.
Existing saved sessions in sessions/ and observation_logs/ can be imported into the canonical
record once so prior history is not lost. All data stays on the local machine. Deleting a
patient removes every session and export tied to that patient. A session interrupted by a
crash or camera loss keeps every event recorded up to that point."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Record a Session into One Canonical Record (Priority: P1)

A physical therapist (PT) or PT student starts an exercise session for a patient, from a
webcam or from an uploaded video, exactly as they do today. While the session runs, every
completed rep, partial rep, form feedback message, exercise switch, and counter reset is
recorded as a timestamped event in a single session record. When the session ends, a summary
is attached to the same record. If the session is interrupted (application crash, camera
unplugged, power loss), every event recorded up to that moment is still present when the
record is opened later.

**Why this priority**: This is the foundation. Without one trustworthy record of what happened
in a session, nothing can be reviewed, compared over time, or exported. Today the same
information is scattered across four writers with three different layouts.

**Independent Test**: Run a short webcam or video session, then open the session record and
confirm it lists the same reps, in the same order, with the same numbers that were shown on
screen during the session. Kill the application mid-session and confirm the partial record is
still readable and complete up to the last event.

**Acceptance Scenarios**:

1. **Given** a patient exists and no session is running, **When** the PT starts a webcam session
   for that patient with an exercise selected, **Then** a new session record exists with the
   patient, start time, source "webcam", and an initial exercise set with the exercise name,
   side, and target reps.
2. **Given** a session is running, **When** the engine completes a rep, **Then** the record gains
   a completed-rep event with rep number, minimum angle, maximum angle, range of motion in
   degrees, duration in seconds, form score from 0 to 100, and a timestamp, and the event is
   durable within one second of occurring.
3. **Given** a session is running, **When** the patient reverses early or does not reach the
   required range, **Then** the record gains a partial-rep event carrying the reason and the
   partial range achieved, and the rep count does not change.
4. **Given** a session is running, **When** the form analyzer emits feedback, **Then** the record
   gains a form event with severity, message, and timestamp, throttled so that an identical
   message repeating every frame is not stored more than once per two seconds.
5. **Given** a session is running, **When** the PT switches exercise or resets the counter,
   **Then** the record gains a switch or reset event, and a switch closes the current exercise
   set and opens a new one.
6. **Given** a session is running, **When** the PT ends the session normally, **Then** the record
   gains an end time and a summary with total reps, average form score, average range of
   motion, and duration, and the summary values equal those computed from the stored events.
7. **Given** a session is running with five reps recorded, **When** the application is killed
   without ending the session, **Then** reopening the application shows the session with all
   five reps, no end time, and a status of "interrupted".
8. **Given** a video file is analyzed instead of a webcam, **When** analysis completes, **Then**
   a session record exists with source "video", the file's name recorded as the source
   reference, and the same event types as a webcam session.

---

### User Story 2 - Register and Manage Pseudonymous Patients (Priority: P2)

A PT registers a patient under a pseudonymous ID (for example "P-017"), optionally adds a short
label and free-text notes, and later edits the label or notes, or deletes the patient. Deleting
a patient removes every session and export tied to that patient after confirmation. Sessions
recorded without a chosen patient land under a built-in "Unassigned" patient and can be
reassigned to a real patient later.

**Why this priority**: Every session needs a patient to be reviewable over time and to be
tracked in later features. Pseudonymous IDs are what keep the tool safe to use with real
patients.

**Independent Test**: Create a patient, run a session against it, reassign an unassigned
session to it, then delete the patient and confirm no trace of its sessions or exports remains.

**Acceptance Scenarios**:

1. **Given** no patient with ID "P-017" exists, **When** the PT registers "P-017" with label
   "Post-op knee" and notes, **Then** the patient appears in the patient list with a creation
   date and zero sessions.
2. **Given** a patient "P-017" exists, **When** the PT tries to register another patient with ID
   "P-017", **Then** the system refuses and explains that the ID is already in use.
3. **Given** a session was recorded under "Unassigned", **When** the PT reassigns it to "P-017",
   **Then** it appears in "P-017"'s history and no longer under "Unassigned".
4. **Given** a patient with three sessions and two exports, **When** the PT deletes the patient
   and confirms, **Then** the patient, all three sessions, all their events, and both export
   files are gone, and the session count for other patients is unchanged.
5. **Given** the PT enters text containing what looks like a full name or date of birth in the
   ID field, **When** they save, **Then** the system warns that identifying information must not
   be stored in the ID and requires a different ID.

---

### User Story 3 - Browse History and Read a Session Log (Priority: P3)

A PT selects a patient and sees that patient's sessions listed newest first, each with date,
source, exercises performed, total reps, and average form score. Opening a session shows its
full event log in time order with every rep, partial rep, form message, switch, and reset, plus
the summary. The existing session-viewing pages in the web app show this same information from
the canonical record instead of reading legacy files.

**Why this priority**: Recording is only useful if a clinician can read what was recorded.
This is also the reading path that review-over-time and tracker features will build on.

**Independent Test**: Record three sessions for one patient on different days, open the
patient's history, confirm the order is newest first, open the middle session, and confirm the
event log matches what happened.

**Acceptance Scenarios**:

1. **Given** a patient has three sessions, **When** the PT opens the patient's history, **Then**
   the sessions are listed newest first with date, source, exercises, total reps, and average
   form score.
2. **Given** a session with 40 events, **When** the PT opens it, **Then** all 40 events are shown
   in chronological order with their type, timestamp, and every stored metric, each metric
   labelled with its unit.
3. **Given** an interrupted session, **When** the PT opens it, **Then** it is clearly marked as
   interrupted, shows every recorded event, and shows a summary computed from those events.
4. **Given** the web app's session, observation-log, and PT-summary pages, **When** the PT uses
   them after this feature ships, **Then** they display sessions from the canonical record and
   no longer depend on files in the legacy folders.

---

### User Story 4 - Export a Session in Legacy Formats (Priority: P4)

A PT exports any session in the PTA-Log pipe-delimited text format, the observation JSON
format, the CSV report format, or the plain-text session log format. Each export is generated
from the canonical record and matches the layout the retired loggers produced, so anyone who
consumed those files (course graders, spreadsheets, downstream scripts) keeps working.

**Why this priority**: The legacy formats have external consumers. Reproducing them as exports
lets the four writers be retired without breaking anyone.

**Independent Test**: Record a session, export it in all four formats, and compare each export
against a file produced by the corresponding legacy logger for an identical sequence of
events: same line and field structure, same headers, same values.

**Acceptance Scenarios**:

1. **Given** a completed session, **When** the PT exports it as PTA-Log text, **Then** the file
   has the PTA header block, one pipe-delimited line per event in the legacy field order, the
   session-summary line, and the halt line.
2. **Given** a completed session, **When** the PT exports it as observation JSON, **Then** the
   document has the session fields, the event list with the legacy event types and field
   names, and the summary block, and it can be opened by the existing observation-log viewer.
3. **Given** a completed session, **When** the PT exports it as CSV, **Then** the file has the
   report header rows, one row per exercise set with reps, target, form score, range of motion
   minimum, maximum, and range, and average rep time, with units in the values as before.
4. **Given** the same session exported twice, **When** the two files are compared, **Then** they
   are identical except for the export timestamp, if the format carries one.
5. **Given** an interrupted session, **When** it is exported, **Then** the export contains every
   recorded event and a summary computed from them, and it is marked as interrupted where the
   format allows.

---

### User Story 5 - Import Legacy Session Files Once (Priority: P5)

A PT runs a one-time import that reads the session files already saved in the legacy session
and observation-log folders and creates canonical session records from them under the
"Unassigned" patient, so history recorded before this feature is not lost. Running the import
again does not create duplicates.

**Why this priority**: Prior history has value for the review-over-time feature, but the
amount is small and the files remain readable on disk, so this can ship last.

**Independent Test**: Point the import at the legacy folders, confirm one canonical session per
legacy session file with matching reps and metrics, run it again, and confirm the count does
not change.

**Acceptance Scenarios**:

1. **Given** legacy folders containing five session files, **When** the PT runs the import,
   **Then** five canonical sessions exist under "Unassigned", each with source, start and end
   time, exercise set, per-rep metrics, and summary equal to the legacy file's values.
2. **Given** the import has already run, **When** it runs again on the same folders, **Then** no
   new sessions are created and the PT is told how many were skipped as already imported.
3. **Given** a legacy file that is malformed, **When** the import runs, **Then** that file is
   skipped with a message naming it and the remaining files are still imported.
4. **Given** a legacy file exists in both the session folder and the observation-log folder
   for the same session, **When** the import runs, **Then** one canonical session is created,
   not two.

---

### Edge Cases

- A session is started while another session is still open (for example after a crash): the
  open session is marked interrupted and closed before the new one begins.
- The engine reports no keypoints for an extended period: no rep or form events are stored,
  and the session still ends and summarizes normally.
- A session ends with zero reps: the record is kept, the summary shows zero reps, and averages
  are shown as "not available" rather than zero.
- A rep arrives with an out-of-range value (negative duration, form score above 100, range of
  motion above 180 degrees): the event is stored as received, flagged as out of range, and
  excluded from averages.
- The PT switches exercises with zero reps in the current set: the empty set is still recorded
  so the switch is visible in the log.
- Two sessions for the same patient start in the same second: both are kept with distinct
  identities.
- The storage location is read-only or the disk is full: the session continues on screen, the
  PT is warned immediately, and the failure is recorded in the application log without
  crashing the session.
- The patient list is empty when a session starts: the session is recorded under "Unassigned".
- Export is requested for a session whose patient was deleted meanwhile: the request fails with
  a clear message.

## Requirements *(mandatory)*

### Functional Requirements

**Canonical record**

- **FR-001**: System MUST maintain exactly one canonical record of sessions, and every feature
  that reads session data MUST read from it rather than from any legacy file.
- **FR-002**: System MUST write session data through exactly one writer; no other component
  MAY write session, rep, or form data to any location.
- **FR-003**: Each session record MUST include the patient, start time, end time (absent while
  running or interrupted), source (webcam or video), a source reference (camera index or file
  name), status (running, completed, interrupted), and a schema version.
- **FR-004**: Each session MUST contain one or more exercise sets, each with exercise name,
  side (left, right, or both), target reps, and the time it started and ended.
- **FR-005**: System MUST record completed reps with rep number within the set, minimum
  angle, maximum angle, range of motion in degrees, duration in seconds, form score from 0 to
  100, and timestamp.
- **FR-006**: System MUST record partial reps with the reason, the range achieved, and the
  timestamp, without changing the rep count.
- **FR-007**: System MUST record form feedback events with severity (suggestion, warning, or
  stop), message text, and timestamp, storing an identical message at most once per two
  seconds.
- **FR-008**: System MUST record exercise switches (from, to, timestamp) and counter resets
  (exercise, rep count at reset, timestamp).
- **FR-009**: System MUST attach a session summary on normal end containing total reps,
  average form score, average range of motion, and duration in seconds, and the summary MUST
  equal the values computed from the stored events.
- **FR-010**: System MUST make each event durable within one second of the engine reporting
  it, so that an interruption loses at most the last second of events.
- **FR-011**: System MUST detect a session left open by an interruption on next start, mark it
  interrupted, and compute its summary from the stored events.
- **FR-012**: Every stored metric MUST carry a defined unit and a plain-language definition
  available wherever it is displayed.

**Patients**

- **FR-013**: Users MUST be able to register a patient with a pseudonymous ID (unique, 1 to 32
  characters, letters, digits, and hyphens), an optional label up to 60 characters, and
  optional free-text notes.
- **FR-014**: System MUST reject a patient ID that is already in use, and MUST reject an ID
  or label that contains two or more consecutive capitalized words, a date in any common
  numeric layout (such as 01/02/1990 or 1990-01-02), or a run of six or more digits, with a
  warning that identifying information must not be stored.
- **FR-015**: System MUST provide a built-in "Unassigned" patient that cannot be deleted and
  MUST record sessions there when no patient is chosen.
- **FR-016**: Users MUST be able to reassign a session from one patient to another.
- **FR-017**: Users MUST be able to delete a patient after confirmation, and deletion MUST
  remove every session, event, and export file tied to that patient.

**Browsing and reading**

- **FR-018**: Users MUST be able to list a patient's sessions newest first with date, source,
  exercises performed, total reps, and average form score.
- **FR-019**: Users MUST be able to open a session and read every event in chronological order
  with its type, timestamp, and metrics, plus the summary and the session status.
- **FR-020**: The existing web-app pages that show session data MUST show it from the
  canonical record.

**Exports**

- **FR-021**: Users MUST be able to export any session in the PTA-Log pipe-delimited text
  format, the observation JSON format, the CSV report format, and the plain-text session log
  format, each generated only from the canonical record.
- **FR-022**: Each export MUST match the structure of the file the corresponding retired
  logger produced for the same events: same header block, same line or field order, same
  field names, same value formatting and units.
- **FR-023**: Exports MUST be written to a user-chosen location that defaults to a folder
  excluded from version control, and export files MUST be named with the pseudonymous ID and
  session start time only.

**Retirement and import**

- **FR-024**: The four legacy writers (numbered text log files, PTA raw text logger,
  observation JSON logger, session tracker JSON and CSV) MUST no longer write files during a
  session once this feature ships.
- **FR-025**: Users MUST be able to run a one-time import of legacy session and observation-log
  files that creates one canonical session per legacy session, under "Unassigned", with
  values equal to the file's contents.
- **FR-026**: The import MUST be repeatable without creating duplicates and MUST skip
  malformed files with a message naming each one.

**Privacy and locality**

- **FR-027**: All session, patient, and export data MUST be stored on the local machine, and
  the feature MUST NOT transmit any of it over a network.
- **FR-028**: No file name, log line, or on-screen error produced by the feature MAY contain
  anything other than the pseudonymous ID to identify a patient.

### Key Entities

- **Patient**: a person receiving therapy, known only by a pseudonymous ID; has an optional
  label, free-text notes, creation date, and zero or more sessions. "Unassigned" is a built-in
  patient.
- **Session**: one continuous exercise period for one patient from one source; has start time,
  end time, status, source reference, schema version, one or more exercise sets, and a
  summary once ended.
- **Exercise Set**: a run of one exercise within a session; has exercise name, side, target
  reps, start and end time, and the rep, partial-rep, and form events that occurred during it.
- **Completed Rep Event**: one counted repetition with rep number, minimum and maximum angle,
  range of motion, duration, form score, and timestamp.
- **Partial Rep Event**: an attempted repetition that did not count, with reason, range
  achieved, and timestamp.
- **Form Event**: a feedback message from the form analyzer with severity, message, and
  timestamp.
- **Control Event**: an exercise switch (from, to) or a counter reset (rep count at reset),
  with timestamp.
- **Session Summary**: total reps, average form score, average range of motion, and duration,
  derived from the events.
- **Export**: a file generated from a session in one of the four legacy formats, tied to the
  session and patient so it can be removed with them.
- **Import Record**: a note of which legacy file was imported into which session, used to
  prevent duplicates.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any session, 100% of reps, partial reps, form messages, switches, and resets
  shown on screen during the session appear in the session record with identical values.
- **SC-002**: After an abrupt interruption, the session record contains every event that
  occurred more than one second before the interruption.
- **SC-003**: A PT can register a patient, run a session, and open its event log in under two
  minutes on first attempt without reading documentation.
- **SC-004**: A session with 500 events opens and displays its full log in under two seconds,
  and a patient history of 200 sessions lists in under two seconds.
- **SC-005**: Every export matches its legacy counterpart for the same event sequence, with
  zero structural differences and zero value differences beyond the export timestamp.
- **SC-006**: After this feature ships, a full session run produces zero files in the four
  legacy folders.
- **SC-007**: Importing the existing legacy files produces one canonical session per legacy
  session with zero duplicates on a second run.
- **SC-008**: An audit of every file name, log line, and screen text produced by the feature
  finds no patient identifier other than the pseudonymous ID.
- **SC-009**: Deleting a patient leaves zero sessions, events, or export files tied to that
  patient.

## Assumptions

- **Recording paths in scope** are the ones that record today: the command-line webcam
  session and video analysis from both the command line and the web app's video-analysis
  page. The web app's live-session page currently records nothing (its "Save Session" button
  only shows a notice), so wiring it into the canonical record is a separate feature.
- **Patient selection at session start** is by pseudonymous ID passed when the session is
  started; when none is given the session is recorded under "Unassigned".
- **Side** is derived from the exercise chosen (the engine's "right" variants are the right
  side, plain variants are the left or dominant side as configured, and bilateral exercises
  such as squat are "both").
- **Form severity** maps the engine's existing categories: suggestions map to "suggestion",
  warnings and poor-form messages map to "warning", and safety stops map to "stop".
- **One session at a time** runs on a machine; concurrent sessions are out of scope.
- **Deletion is permanent** with a confirmation step; there is no recycle bin.
- **The engine is unchanged**: this feature consumes the engine's existing outputs and does
  not alter thresholds, rep counting, or form checks.
- **Legacy files stay on disk** after import; the import copies, it does not move or delete.
- **A fifth writer is retired without an export.** Besides the four loggers named above, the
  engine's per-session report writer produces the per-rep JSON and CSV files currently found
  in the sessions folder. Its only consumer is the web app's session page, which moves to the
  canonical record, so those two shapes are not reproduced as exports; the one-time import
  still reads the JSON shape so that history is kept. "The existing CSV format" in this spec
  means the session-tracker report layout (one row per exercise set).
- **Review-over-time analytics** (trends, comparisons, flags across sessions) and the
  multi-patient tracker are separate features that will read this record.
