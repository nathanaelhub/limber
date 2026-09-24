# Feature Specification: Voice Notes, with a Transcript for the Therapist

**Feature Branch**: `014-voice-notes`

**Created**: 2026-09-24

**Status**: Approved by the owner's plan approval on 2026-09-23

**Input**: Owner's plan: the patient records a short spoken note in Limber and sends it; it arrives
attached to a message in the therapist's inbox, so unread counts and the conversation work unchanged;
the therapist plays it, reads an automatic transcript marked as possibly containing errors, marks it
reviewed, and can delete it. Audio reuses the feature 011 media pipeline. Transcription runs on the
Limber host only, never a third party: a queue in the record with one worker, model files fetched by a
pinned, hash-checked script, the transcript privacy-checked and therapist-only. The transcription half
is a separate slice the app works without.

## Constitution Check (Principle III, v1.2.0)

| Requirement | This feature |
|-------------|--------------|
| Deliberate upload after a plain notice | The voice-note page states before recording: the recording is stored on the Limber host, heard by the therapist, written out automatically on the host, kept 90 days after review (180 unreviewed), and can be deleted by the patient. |
| What crosses the network | The audio file the patient chose to send, and nothing else. No audio is ever captured or sent during a guided session. |
| What never does | Anything of another patient; no audio or transcript goes to any third party, and no browser speech service is used. |
| Who may use it | Demo and consented study participants only. |
| Only the patient's own data | A patient hears and deletes only their own notes; no request names a patient. |
| Retention and deletion | 90 days after review, 180 unreviewed; a patient delete leaves a marker; deleting the patient removes every file and transcript. |
| Processed only on the host | Transcription runs on the Limber host with locally installed model files fetched by a pinned, hash-checked script. A voice is more identifying than a body point, so nothing leaves the host. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Patient Sends a Spoken Note (Priority: P1)

Something is wrong and typing it out is too much trouble: the patient opens Limber, taps "Send a voice
note", reads the notice, records up to about two minutes, listens back, re-records if they want, and
sends. It appears in their conversation with the therapist as their own message with a player. They can
delete a note they sent.

**Why this priority**: Speaking is the point — a patient who will not type will still talk, and this is
the slice that delivers that with no new dependency.

**Independent Test**: A patient records and sends a 30-second note on a phone; it appears in their
conversation and in the therapist's inbox with a working player, and the therapist's unread count rises
by one.

**Acceptance Scenarios**:

1. **Given** the voice-note page, **Then** the notice is shown before the microphone is opened.
2. **Given** a 30-second recording, **When** sent, **Then** it uploads in parts with progress, appears
   in the patient's conversation with a player, and raises the therapist's unread count by one.
3. **Given** a recording over the limits (about three minutes, 10 MB), a file with no audio, or a file
   that carries video, **Then** it is refused with a plain reason and nothing is stored.
4. **Given** the connection drops mid-upload, **When** it returns, **Then** the upload resumes from the
   last part.
5. **Given** the patient deletes a voice note they sent, **Then** the file is removed, the message stays
   with a "removed" marker, and the transcript (if any) goes with it.
6. **Given** the patient's phone has no microphone permission, **Then** the page says so plainly and
   offers nothing that cannot work.
7. **Given** messaging is turned off for this patient, **Then** voice notes are not offered.

---

### User Story 2 - The Therapist Listens in the Inbox (Priority: P1)

The therapist opens the inbox, sees the patient's message with a player, listens, and replies as
usual. Voice notes awaiting review appear in the work queue and mark the patient on the roster, as
clips do. The therapist can mark one reviewed and delete one.

**Why this priority**: A note nobody hears is worse than no note; the inbox is where the therapist
already works.

**Acceptance Scenarios**:

1. **Given** a sent voice note, **Then** the inbox thread shows it with its length and time, plays it,
   and the reply box works as before.
2. **Given** an unreviewed voice note, **Then** the queue lists it for that patient and the roster marks
   them; marking it reviewed clears both.
3. **Given** the therapist deletes a voice note, **Then** the file and transcript go and a marker stays.
4. **Given** a voice note and a clip from the same patient, **Then** each is counted and listed as its
   own kind, and the queue says which is which.

---

### User Story 3 - An Automatic Transcript, on the Host (Priority: P2)

So the therapist can skim rather than listen to everything, the host writes out each voice note by
itself. The transcript appears under the player marked "written out automatically; it may contain
mistakes", and is never shown to the patient. Writing out is queued: a note is playable at once and its
transcript appears when it is ready. If no speech model is installed, everything above still works and
the transcript line says it is not available.

**Why this priority**: It is the half that needs a new dependency and model files, so it must be
separable: the feature is useful without it, and the app must run identically with no model installed.

**Acceptance Scenarios**:

1. **Given** a new voice note and an installed model, **Then** a transcription job is queued, the note
   plays immediately, and the transcript appears when the job finishes, marked as automatic.
2. **Given** no model installed, **Then** no job is queued, nothing fails, and the transcript line says
   writing out is not available on this installation.
3. **Given** a transcript that looks like it contains identifying details, **Then** it carries the
   privacy marker and the therapist can remove it; the patient never sees a transcript.
4. **Given** a transcription that fails or takes too long, **Then** the job is marked failed with a
   reason word, the note still plays, and the failure is visible to the therapist rather than silent.
5. **Given** the model files are fetched, **Then** the script checks them against pinned hashes and
   refuses anything that does not match; no model file is ever committed to the repository.
6. **Given** the transcription worker is running, **Then** it takes one job at a time and the service
   answers requests throughout.

---

### Edge Cases

- A patient records in a language the model was not set up for: the transcript may be nonsense, which is
  why it is always marked automatic and the audio is always kept and playable.
- Silence, or a recording of nothing but noise: accepted if it is valid audio; the transcript may be empty,
  and an empty transcript says "nothing recognisable" rather than looking like a failure.
- A very long pause before sending: the open upload expires after an hour, as clips do.
- Two voice notes sent quickly: both are kept, each with its own message.
- A voice note from a discharged patient: not offered, refused if attempted.
- The model files are half-downloaded or corrupt: the worker refuses to start and says so; notes still arrive.
- A phone that records in a container the host cannot read: refused with a plain reason and nothing stored.
- Deleting a patient removes their audio and transcripts and cancels any queued jobs.

## Requirements *(mandatory)*

### The voice note itself (User Stories 1 and 2)

- **FR-001**: A signed-in patient MUST be able to record and send audio of up to 180 seconds and 10 MB
  (the limits feature 011 already set for the `voice` kind), in parts, with progress and resumption, and
  to listen to it before sending. The page MUST suggest about two minutes rather than the hard limit.
- **FR-002**: The service MUST decide a file's type by inspecting it, never by its name or declared
  type; it MUST accept common phone audio (M4A/AAC, MP3, Ogg/Opus, WAV, and WebM/Opus) with at least one
  audio stream and no video stream, and refuse everything else, including files that fail to decode.
  Inspection MUST run isolated so a malformed file cannot take the service down.
- **FR-003**: A sent voice note MUST appear as a message from the patient in their conversation with the
  therapist, so that unread counts, the inbox, and message removal work exactly as they already do.
- **FR-004**: A patient MUST hear and delete only their own voice notes; deletion MUST remove the file
  and any transcript and leave a marker in the conversation.
- **FR-005**: The therapist app MUST play a voice note in the inbox thread with its length and time, and
  offer "Mark reviewed" and "Delete"; unreviewed voice notes MUST appear in the work queue as their own
  kind and mark the patient on the roster.
- **FR-006**: Retention, backup, restore, reconciliation, and deletion with the patient MUST apply to
  audio exactly as they apply to clips, and a transcript MUST never outlive its audio.
- **FR-007**: Voice notes MUST NOT be offered when messaging is off for the patient or the patient is
  discharged.
- **FR-008**: Every upload, refusal, review, and deletion MUST be recorded in the access history with a
  reason word only, never a transcript or a filename.

### The transcript (User Story 3, separable)

- **FR-009**: With no speech model installed, every requirement above MUST hold unchanged, no
  transcription job MUST be created, and the therapist MUST see one plain line saying writing out is not
  available on this installation.
- **FR-010**: With a model installed, each new voice note MUST create one queued transcription job;
  jobs MUST be taken one at a time by a single worker, MUST have a time limit, and MUST record their
  state (queued, running, done, failed) with a reason word on failure.
- **FR-011**: Transcription MUST run on the Limber host from locally installed model files. No audio and
  no transcript MUST leave the host, and no browser or third-party speech service MUST be used.
- **FR-012**: Model files MUST be fetched by a script that checks them against pinned hashes, refuses a
  mismatch, and stores them outside the repository; no model file MUST ever be committed.
- **FR-013**: A transcript MUST be shown only to the therapist, MUST be marked as written out
  automatically and possibly wrong, MUST go through the privacy check with a marker when it trips it, and
  MUST be removable by the therapist.
- **FR-014**: The new dependency MUST be justified in the plan under constitution V, MUST appear in the
  installation's preflight and health checks as optional, and MUST NOT be required for the suite, which
  MUST contain no model weights and make no network call.

## Key Entities

- **Voice note**: a media row of kind `voice`, with its container, codec, length, size, hash, times,
  reviewed and deleted marks, and the message it belongs to.
- **Transcription job**: which voice note, its state, attempts, when it ran, how long it took, the
  reason word if it failed, and the model that produced it.
- **Transcript**: the text, the model and its version, whether the privacy check tripped, and whether the
  therapist removed it.

## Success Criteria

- **SC-001**: A 30-second voice note recorded on a phone is sent and appears in the inbox within 30
  seconds on a home connection.
- **SC-002**: 100% of non-audio, video-bearing, and over-limit files are refused with nothing stored.
- **SC-003**: 0 responses contain another patient's audio, transcript, or id; 0 transcripts reach a
  patient.
- **SC-004**: With no model installed, every feature-013 result and every voice-note result above is
  unchanged, and the suite passes with no model weights present.
- **SC-005**: A two-minute note is written out within five minutes on the reference host, and the
  service keeps answering requests while it runs.
- **SC-006**: A restore drill brings back every voice note and its transcript.

## Assumptions

- The patient records in the browser; a phone that cannot record in the browser can still attach an audio
  file it has. Which container a phone produces is not ours to choose, which is why several are accepted.
- Two minutes is long enough for a spoken note and short enough to transcribe on a small host; the
  service allows up to three minutes, which is what feature 011 already set for audio.
- One worker thread, not a process pool: the reference host is small, and a queue in the record is
  simpler to reason about than a job service.
- The speech model is small and runs on the processor, not a graphics card; the owner installs it with the
  provided script, and the installation may run without it.
- The transcript is an aid to the therapist, not a record of what was said: the audio remains the record.
- No spoken answers during exercises (that was feature 015, and it stays out of scope here).
