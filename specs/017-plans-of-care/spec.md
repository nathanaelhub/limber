# Feature Specification: Plans of Care, Appointments, and Photo and Document Attachments

**Feature Branch**: `017-plans-of-care`

**Created**: 2026-10-29

**Status**: Approved by the owner on 2026-10-30. Depends on 016.

**Input**: The students' Limber requirements 7–10 (see `specs/CROSSWALK-limber-requirements.md`): an
episode of care with a diagnosis and a status, messages grouped by episode, an archived episode kept
read-only, lightweight appointments with a reschedule request, and photos and documents attached to
messages. Built on our existing programs (003), messages (008), and media pipeline (011).

## Constitution Check (Principle III, v1.2.0)

| Requirement | This feature |
|-------------|--------------|
| Deliberate upload after a plain notice | Photos and documents reuse the 011 notice: stored on the Limber host, seen by the therapist, kept for the stated period, deletable by the patient. |
| What crosses the network | The file the patient or therapist chose to attach. |
| Retention | Photos and documents: kept while the plan is active and 1 year after it is archived, then deleted. |
| Processed only on the host | Photos are re-encoded on the host to strip location and camera metadata. Nothing goes to a third party. |
| Diagnosis | Free text written by the therapist, therapist-only by default; the therapist can choose to show it to the patient. Never in filenames or logs. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Therapist Opens a Plan of Care (Priority: P1)

The therapist starts a plan for a patient: a title ("Right knee, post-op"), a diagnosis, a start date,
and the exercise program. A patient can have several plans over time, one or more active. Everything
new — program, logs, diary, questionnaires, messages, clips, voice notes — belongs to a plan. The
therapist can mark a plan completed, and archive a completed one.

**Acceptance Scenarios**:

1. **Given** an upgrade from v14, **Then** each patient gets one active plan titled "Plan of care" and all
   their existing records belong to it.
2. **Given** an archived plan, **Then** both sides can read everything in it but nothing can be added,
   edited, or deleted (409), except a patient deleting their own upload, which retention rules still allow.
3. **Given** a patient with two active plans, **Then** their home shows both, each with its own program
   and conversation.

### User Story 2 - Conversations Stay with Their Episode (Priority: P1)

The inbox groups each patient's conversation by plan. Unread counts are per plan and roll up to the
patient. A message is sent into one plan.

**Acceptance Scenarios**:

1. **Given** a message in the shoulder plan, **Then** it does not appear in the knee plan's conversation.
2. **Given** existing messages after migration, **Then** they appear in the one migrated plan, in order,
   with read state kept.

### User Story 3 - Photos and Documents in Messages (Priority: P2)

Either side can attach up to 4 photos (JPEG, PNG, HEIC; 15 MB each) or a PDF (20 MB) to a message. On a
phone the patient can take a photo directly. Photos show as thumbnails and open full size.

**Acceptance Scenarios**:

1. **Given** a photo with GPS metadata, **When** it is stored, **Then** the stored copy has none.
2. **Given** a file whose content does not match its stated type, **Then** it is refused with a plain
   message.
3. **Given** the patient is deleted, **Then** every attachment file is gone from disk.

### User Story 4 - Appointments and a Reschedule Request (Priority: P2)

The therapist adds appointments to a plan: date, time, length, and a short note. The patient sees
upcoming appointments on their home and in a month view. A patient can tap **Ask to reschedule** and
write a note; the therapist sees the request flagged in their own calendar and inbox, changes the time or
declines with a note. No approval workflow beyond that.

**Acceptance Scenarios**:

1. **Given** an appointment tomorrow at 9:00 in the clinic's time zone, **Then** the patient sees 9:00
   whatever time zone their device is in. The clinic time zone is a setting.
2. **Given** a reschedule request, **Then** the therapist's calendar marks it and the request note is
   shown; when the time changes, the flag clears and the patient sees the new time.
3. **Given** a cancelled appointment, **Then** it stays visible, struck through, to both.

### Edge Cases

- A plan with no program yet: patient sees "Your therapist hasn't added exercises yet."
- An appointment in the past that was never marked: shown as "past", not counted as missed.
- HEIC on a desktop browser: the host converts it for display.

## Requirements *(mandatory)*

- **FR-001**: Plan of care: title, diagnosis, diagnosis visible to patient (default no), start, end,
  status `active | completed | archived`.
- **FR-002**: Every plan-scoped write checks the plan is not archived, in the data layer.
- **FR-003**: Attachments reuse the 011 storage layout under the pseudonymous ID, with type sniffing and
  size limits on the host.
- **FR-004**: Appointment: plan, start (stored UTC, shown in clinic time zone), minutes, note, status
  `scheduled | cancelled`, reschedule requested (yes/no), request note.
- **FR-005**: Schema v15 migrates v14 as in Story 1, scenario 1, and Story 2, scenario 2.

## Success Criteria

- **SC-001**: A therapist can open a second plan for an existing patient and send a message in it within
  1 minute.
- **SC-002**: Existing tests pass after migration; new tests prove archived plans refuse every write route.

## Assumptions

- No calendar sync (iCal, Google); a later networked feature could add it.
- No video in messages beyond what 011 already provides.

## Deviations recorded while building (2026-10-30)

- **HEIC**: Pillow cannot read HEIC on its own, and a photo that cannot be read cannot have its metadata
  removed. HEIC is accepted and converted to JPEG only when the optional `pillow-heif` plug-in is installed
  on the host. Without it, HEIC is refused with a plain message that says how to send a compatible photo.
  No new required dependency was added (Principle V). iPhone Safari usually converts HEIC to JPEG on upload
  anyway.
- **PDFs** are checked by type and size and stored as sent. They are not rewritten, because rewriting a PDF
  safely needs a PDF library. This matches the Constitution Check, which only asks that photos be re-encoded.
- **Where writes land**: a write that names no plan goes to the patient's newest active plan, or to the
  newest completed one if no plan is active. If every plan is archived, the write is refused with 409.
- **Attachments** have their own table (not `media`), because `media.kind` is a CHECK constraint that would
  need a table rebuild. The files still follow the 011 layout under the pseudonymous ID, in an
  `attachments/` subfolder.
- **`plan_id`** columns added to existing tables have no foreign key, because SQLite cannot add one without a
  rebuild. Plans are removed with the patient.
- **Default clinic time zone** is America/Chicago (the demo clinic). It is a setting.
