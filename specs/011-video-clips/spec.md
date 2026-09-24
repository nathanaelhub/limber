# Feature Specification: Video Clips and PT Review

**Feature Branch**: `011-video-clips`

**Created**: 2026-09-24

**Status**: Approved by the owner's plan approval on 2026-09-23

**Input**: Owner's plan: a patient records a short clip (about 60 s) on purpose, for example to show
pain or a movement problem, and uploads it; the PT watches it in the therapist app, marks it
reviewed, and can delete it. Guided sessions keep sending body points only.

## Constitution Check (Principle III, v1.2.0)

| Requirement | This feature |
|-------------|--------------|
| Deliberate upload after a plain notice | The clip page states before recording: the clip is stored on the Limber host, seen by the therapist, kept 90 days after review (180 unreviewed), and can be deleted by the patient. |
| What crosses the network | The clip file, its caption (optional, privacy-checked), and its metadata. |
| What never does | Anything of another patient; therapist notes, flags, thresholds. The clip goes nowhere but the Limber host. |
| Who may use it | Demo and consented study participants only. |
| Only the patient's own data | A patient sees, plays, and deletes only their own clips; no request names a patient. |
| Retention and deletion | 90 days after review, 180 days unreviewed; patient delete leaves a marker; deleting the patient removes every file. |
| Processed only on the host | Validation and playback on the host; no third-party service. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Record and Send a Clip (Priority: P1)

From Today, the patient taps "Send a video to my therapist", reads the notice, records with the
phone camera (or picks a video), adds an optional caption, and sends. Upload progress is shown; a
lost connection can be resumed. The patient sees their own clips and can delete one.

**Acceptance Scenarios**:

1. **Given** the clip page, **Then** the notice is shown before the camera opens.
2. **Given** a 40 s clip from the phone camera, **When** sent, **Then** it uploads in parts with
   progress, is accepted, and appears in the patient's list within seconds.
3. **Given** a clip over the limits (about 65 s, 80 MB) or a file that is not a video, **Then** it is
   refused with a plain reason and nothing is stored.
4. **Given** the connection drops mid-upload, **When** it returns, **Then** the upload resumes from the
   last part rather than starting over.
5. **Given** a caption that looks identifying, **Then** the privacy warning applies (edit or send anyway).
6. **Given** the patient deletes a clip, **Then** its file is removed and a "removed" marker stays in the list.

### User Story 2 - The PT Watches and Reviews (Priority: P1)

The therapist sees new clips on the roster and in the queue, opens the patient's "From the patient"
tab, watches the clip with its caption and date, marks it reviewed, or deletes it.

**Acceptance Scenarios**:

1. **Given** a new clip, **Then** the queue lists "1 clip awaiting review" for that patient and the
   roster marks the patient as needing attention.
2. **Given** the tab, **Then** the clip plays in the therapist app with caption, recorded time, and
   length; "Mark reviewed" records the time; "Delete" removes the file and leaves a marker.
3. **Given** a caption sent after a privacy warning, **Then** it carries the marker and can be removed.

### User Story 3 - Kept Safely, Then Gone (Priority: P2)

Clips live on the host's volume under the pseudonymous ID, are backed up with the record, and are
deleted by retention.

**Acceptance Scenarios**:

1. **Given** a nightly backup, **Then** clips not yet backed up are copied encrypted, and a restore
   brings them back with the record.
2. **Given** the retention run, **Then** clips reviewed more than 90 days ago, or unreviewed for more
   than 180, are deleted and their markers kept.
3. **Given** a patient is deleted, **Then** every file of theirs is gone.

### Edge Cases

- An upload never finished: its parts are removed after an hour.
- A file that is valid but has no video stream (audio only) is refused here (voice notes are feature 014).
- A clip that crashes the media library while being checked must not take the service down: it is refused.
- Two uploads at once from the same patient are allowed, up to three open; 10 clips or 250 MB a day.
- The PT's browser cannot play a format (for example a WebM clip in Safari): the page says so and
  offers the file to download; converting formats is out of scope.

## Requirements *(mandatory)*

- **FR-001**: A signed-in patient MUST be able to upload a video clip of up to 65 s and 80 MB in
  parts, with progress and resumption, and an optional caption of up to 200 characters that passes the
  privacy check.
- **FR-002**: The service MUST decide the file's type by inspecting it, never by the name or declared
  type; it MUST accept MP4, MOV, and WebM containers with one video stream (H.264, HEVC, VP8, VP9, or
  AV1) and refuse everything else, including files that fail to decode; inspection MUST run isolated so
  a malformed file cannot crash the service.
- **FR-003**: Clips MUST be stored under `data/media/<patient id>/<random id>.<ext>` with private
  permissions and a metadata row in the record (kind, size, duration, dimensions, codec, container,
  hash, caption, times, reviewed, deleted); the original filename MUST NOT be stored.
- **FR-004**: Per patient: at most 3 open uploads, 10 clips and 250 MB per rolling 24 hours; open
  uploads MUST expire after 1 hour.
- **FR-005**: A patient MUST see, play, and delete only their own clips; any other id MUST answer as
  not found; deletion MUST remove the file and keep a marker.
- **FR-006**: The therapist app MUST list a patient's clips with playback, caption, times, and length,
  and offer "Mark reviewed" and "Delete"; unreviewed clips MUST appear in the queue ("new_uploads") and
  mark the patient on the roster.
- **FR-007**: Retention MUST delete files 90 days after review or 180 days unreviewed, keeping the row
  as a marker; a command MUST run it and report what it removed.
- **FR-008**: Backups MUST include clips not yet backed up, encrypted; restore MUST bring them back;
  a reconciliation command MUST remove files without rows and mark rows without files.
- **FR-009**: Every upload, refusal, view by the PT, review, and deletion MUST be recorded in the
  access history with the reason word only, never the caption or a filename.
- **FR-010**: Deleting a patient MUST delete their files; the no-leak test MUST cover the media routes.
- **FR-011**: The therapist app's playback MUST sit behind the therapist sign-in; the residual risk that
  the app's own media handling serves bytes to anyone holding that app session is accepted for study use.

### Key Entities

- **Media**: id, patient, kind (`clip`), container, codec, bytes, duration, width, height, hash,
  caption, warned, created, reviewed, deleted.
- **Upload**: an open, chunked transfer with expiry.

## Success Criteria

- **SC-001**: A 40 s phone clip uploads and is listed within 30 s on a home connection.
- **SC-002**: 100% of non-video and over-limit files are refused with nothing stored.
- **SC-003**: 0 responses contain another patient's clip or id.
- **SC-004**: A restore drill brings back every clip that had a row.
- **SC-005**: With no clips, every existing result is unchanged.

## Assumptions

- Encryption at rest relies on the host's volume encryption and file permissions; backups are
  encrypted. Per-file encryption would prevent seeking during playback and adds little while the record
  itself is plaintext; the compliance review may revisit this.
- No format conversion in this version.
