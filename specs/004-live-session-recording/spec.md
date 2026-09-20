# Feature Specification: Live Web Session Recording

**Feature Branch**: `004-live-session-recording`

**Created**: 2026-09-20

**Status**: Draft

**Input**: User description: "Live web session recording: the web app's live-session page records
a session into the canonical record the same way the command-line webcam session does, using
the same exercise engine. Today the page runs its own simplified rep counter with no smoothing,
no form assessment, and no recording, and its Save Session button only shows a notice. A PT or
PT student selects the patient in the sidebar, chooses the exercise, target reps, and camera on
the page, and starts the stream; from that moment every completed rep, partial rep, form
feedback event, exercise switch, and counter reset is recorded as it happens under that
patient, exactly as a command-line webcam session would be, and the on-screen panel shows the
same rep count, current angle, phase, form status, and feedback messages that the command-line
webcam view shows, produced by the real engine rather than the page's own counter. While the
stream runs the PT can switch to another exercise (recorded as a switch that closes the current
set and opens a new one) and reset the rep counter (recorded as a reset). Stopping the stream
ends the session normally and the page shows the session summary (reps, average form score,
average range of motion, duration) with a link to open the session on the Sessions page; the
new session then appears everywhere sessions appear (history, reviews, trends, flags, tracker
roster). If the browser tab is closed or the page reloads while streaming, the session is
recovered as interrupted on the next start with every event recorded up to that point, as the
record already does for interrupted sessions. Starting a stream while a previous session is
still open ends the previous one as interrupted first. The Save Screenshot button saves the
current annotated frame as an image file named only with the pseudonymous ID and time under
the export location, and the placeholder Save Session button is removed. Sessions recorded from
the page carry the source "webcam" and the camera choice as the source reference. Recording
must not visibly slow the stream: the per-frame cost of recording stays within the engine's
existing per-frame budget. All data stays local and patients remain pseudonymous."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Record a Live Session with the Real Engine (Priority: P1)

A PT selects the patient in the sidebar, chooses an exercise, a target rep count, and a camera
on the live-session page, and starts the stream. From that moment the page shows the engine's
own numbers: rep count, current angle, phase (up, down, idle, neutral), form status, and up to
two feedback messages. Every completed rep, partial rep, and form event is recorded under the
selected patient as it happens. Stopping the stream ends the session and the page shows the
summary with a link to the session.

**Why this priority**: Without this the page is a demo that loses every session it shows. It is
also the last place in the product that runs a second, simplified copy of the engine.

**Independent Test**: Drive the page's frame processing with a recorded clip (no camera), then
open the session: the reps recorded equal the reps the command-line webcam run of the same
clip produces, in the same order with the same values, and the summary shown on stop equals
the stored summary.

**Acceptance Scenarios**:

1. **Given** patient P-017 is selected and "Knee Extension" with target 10 is chosen, **When**
   the PT starts the stream, **Then** a session with source "webcam" and the camera choice as
   its source reference exists for P-017 within one second, with one set for Knee Extension
   and target 10.
2. **Given** the stream is running, **When** the engine counts a rep, **Then** the rep is
   recorded with its number, angles, range of motion, duration, form score, and timestamp
   within one second, and the on-screen rep count matches the recorded count.
3. **Given** the stream is running, **When** the engine reports a partial rep or a form
   warning, stop, or poor-form message, **Then** the event is recorded with the same values
   and throttling as the command-line webcam session, and the panel shows the status and
   message.
4. **Given** the stream is running, **When** the PT stops it, **Then** the session is ended
   normally, the page shows total reps, average form score, average range of motion, and
   duration equal to the stored summary, and a link opens the session on the Sessions page.
5. **Given** a session was recorded from the page, **When** the PT opens history, trends,
   flags, or the tracker roster, **Then** the session appears exactly like one recorded from
   the command line.
6. **Given** no person is in view, **When** frames arrive, **Then** nothing is recorded and the
   panel shows no keypoints detected, as the command-line view does.

---

### User Story 2 - Switch Exercise and Reset Mid-Stream (Priority: P2)

While the stream runs the PT changes the exercise on the page; the current set is closed, a
switch is recorded, and a new set opens for the new exercise with its own counter and form
checks. The PT can also reset the rep counter, which is recorded as a reset without closing the
set.

**Why this priority**: A live session with several exercises is the normal case in clinic; it
must be recorded the way the command-line keys record it.

**Independent Test**: Start a stream, switch the exercise, complete reps, reset, complete more
reps, stop; the session log shows the switch and reset events in order with the reps under the
right sets.

**Acceptance Scenarios**:

1. **Given** the stream is running on Knee Extension with 3 reps recorded, **When** the PT
   selects Squat, **Then** a switch event from Knee Extension to Squat is recorded, the Knee
   Extension set is closed, a Squat set opens, the counter shows 0, and any movement in
   progress is recorded as an interrupted partial rep.
2. **Given** the stream is running with 2 reps in the current set, **When** the PT presses
   reset, **Then** a reset event with count 2 is recorded, the counter shows 0, and the set
   stays open.
3. **Given** the PT changes the target rep count while streaming, **When** the next set opens
   (at the next switch) or the stream is restarted, **Then** the new target applies; the
   current set keeps its target.

---

### User Story 3 - Interruptions and One Open Session (Priority: P3)

If the tab closes, the page reloads, or the camera drops while streaming, the session is kept
with every event recorded up to that point and is marked interrupted on the next start. Starting
a stream while an earlier session is still open ends that one as interrupted first, so there is
never more than one running session.

**Why this priority**: This is what makes the page trustworthy for real patients; the record
already provides the recovery, the page must simply never bypass it.

**Independent Test**: Start a stream, record reps, kill the process, reopen the app, and confirm
the session is present as interrupted with those reps; start a new stream and confirm the old
one is not reopened.

**Acceptance Scenarios**:

1. **Given** a stream with 4 recorded reps, **When** the process is killed, **Then** on the next
   start the session is marked interrupted and shows the 4 reps.
2. **Given** a session is still running from an earlier stream, **When** a new stream starts,
   **Then** the earlier session is marked interrupted before the new one begins, and only the
   new one is running.
3. **Given** the camera stops delivering frames for 30 seconds, **When** the PT stops the
   stream, **Then** the session ends normally with what was recorded.

---

### User Story 4 - Screenshot and Cleanup (Priority: P4)

The Save Screenshot button saves the current annotated frame as an image under the export
location, named only with the pseudonymous ID and time, and the page's placeholder Save
Session button is removed because sessions are now saved automatically.

**Why this priority**: Small, but the placeholder actively misleads users into thinking a
session was saved.

**Independent Test**: Press Save Screenshot during a stream and find the image file; confirm no
Save Session button exists.

**Acceptance Scenarios**:

1. **Given** the stream is running for P-017, **When** the PT presses Save Screenshot, **Then**
   a PNG of the current annotated frame is written under the export location named
   `P-017_<time>.png` and the page shows the path.
2. **Given** the stream is not running, **When** the PT presses Save Screenshot, **Then** the
   page says there is no frame to save.
3. **Given** the page renders, **Then** no Save Session control exists.

---

### Edge Cases

- The patient selected in the sidebar changes while a stream is running: the running session
  keeps its patient; the new selection applies to the next stream.
- The camera permission is denied or no camera exists: the stream does not start and no
  session is created.
- The stream is started and stopped within a second with no frames: a session is still created
  and ended with zero reps.
- Two browser tabs run the page: the second stream to start ends the first's session as
  interrupted (one running session per installation).
- The exercise list on the page and on the command line differ today; the page MUST offer the
  same exercises the configuration defines.
- The model takes several seconds to load on the first stream: the page shows a loading state
  and no session is created until the first frame is processed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The live-session page MUST process frames with the same engine the command-line
  webcam session uses (the same rep state machine with smoothing, the same form analyzer, the
  same thresholds from the configuration) and MUST NOT keep its own counter or form score.
- **FR-002**: The panel drawn on the video MUST show the exercise name, rep count against
  target, current angle, phase, form status, and up to two feedback messages from the engine.
- **FR-003**: Starting a stream MUST create a running session for the sidebar patient (or the
  built-in "Unassigned" patient when none is selected) with source "webcam", the camera choice
  as the source reference, and one set for the chosen exercise with the chosen target reps;
  any session still running MUST be marked interrupted first.
- **FR-004**: Completed reps, partial reps, form events, switches, and resets MUST be recorded
  through the same recording path the command-line session uses, with the same values,
  timestamps, throttling, and frame sampling.
- **FR-005**: Changing the exercise while streaming MUST close the current set, record a
  switch, record any movement in progress as an interrupted partial rep, and open a new set
  with a fresh counter and form checks for the new exercise.
- **FR-006**: Pressing reset while streaming MUST record a reset with the current count and
  restart the counter without closing the set.
- **FR-007**: Stopping the stream MUST end the session normally and the page MUST show total
  reps, average form score, average range of motion, and duration equal to the stored summary,
  with a way to open the session in the Sessions page.
- **FR-008**: A session interrupted by a closed tab, reload, or crash MUST be recoverable with
  every event recorded before the interruption, using the record's existing recovery.
- **FR-009**: The page MUST offer the exercises defined in the configuration, by display name.
- **FR-010**: Save Screenshot MUST write the current annotated frame as PNG under the export
  location named `<patient id>_<YYYYMMDD_HHMMSS>.png` and MUST report when there is no frame;
  the Save Session control MUST be removed.
- **FR-011**: Recording MUST add no more than 2 ms per processed frame on average, measured
  over a 300-frame clip, so the stream keeps its current frame rate.
- **FR-012**: The page MUST NOT display or store any patient identifier other than the
  pseudonymous ID.

### Key Entities

- **Live Session**: the running canonical session created at stream start; identical in shape
  to a command-line webcam session.
- **Stream Controls**: exercise, target reps, camera choice, reset; the patient comes from the
  sidebar and is fixed at stream start.
- **Screenshot**: a PNG export file tied to the patient by name only.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a recorded clip driven through the page's frame processing, 100% of reps,
  partial reps, and form events match those the command-line webcam path records for the same
  clip, in order and value.
- **SC-002**: The summary shown on stop equals the stored session summary for 100% of sessions.
- **SC-003**: After a killed process, every event recorded more than one second before the kill
  is present and the session is marked interrupted.
- **SC-004**: Recording adds at most 2 ms per frame on average over a 300-frame clip.
- **SC-005**: A PT can start a stream, complete reps, switch exercise, stop, and open the
  session in under two minutes on first use.
- **SC-006**: The page contains no second implementation of rep counting or form scoring.

## Assumptions

- **One stream at a time per installation**; a second stream supersedes the first's session.
- **The patient is captured at stream start**; changing the sidebar selection mid-stream does
  not move the running session.
- **Inference settings** match the command-line defaults (image size 320, every frame); a
  settings control is out of scope.
- **The camera choice label** ("Default", "Front camera", "Back camera") is the source
  reference, since the browser does not expose a device index.
- **Screenshots are not tracked in the record** beyond their pseudonymous file name; they are
  images, not data exports.
- **The browser stream's frame rate is what it is today**; this feature adds recording without
  changing capture.
