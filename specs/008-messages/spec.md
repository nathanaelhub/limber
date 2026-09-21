# Feature Specification: Messages (Therapist Inbox and Patient Conversation)

**Feature Branch**: `008-messages`

**Created**: 2026-09-21

**Status**: Draft (not approved; nothing is built)

**Input**: User description: "For the doctor side have it like an inbox for a direct communication
channel." A therapist gets an inbox in the therapist app; each patient gets a conversation with
their therapist in the Limber patient view.

## Constitution Check (Principle III, networked feature)

| Requirement (constitution 1.1.0) | This feature |
|----------------------------------|--------------|
| Explicit, separately specified, opt-in | This spec. Messaging is off for a patient until the therapist turns it on for that patient. |
| What crosses the network | The text of messages between one patient and the therapist, their times, and read marks. |
| What never crosses the network | Other patients' messages or IDs; attachments, images, audio, or video (none are supported); therapist notes, reviews, flags, thresholds. |
| Who may use it | Demo users and consented study participants only, as in feature 007. |
| Only the patient's own data | A patient sees only their own conversation; identity comes from the sign-in alone. |
| Pseudonymous IDs, deletion | Deleting a patient removes their conversation. |

**The risk this feature adds**: free text. Everything stored so far is numbers and fixed
vocabularies under a pseudonymous ID. A patient can type their name, phone number, or a medical
detail into a message. See FR-008 to FR-010 and the open questions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Therapist's Inbox (Priority: P1)

The therapist opens Inbox in the therapist app and sees one row per patient conversation, newest
activity first, with the patient's ID, the latest message's first line, when it arrived, and an
unread count. Unread conversations stand out. Opening one shows the thread and a reply box. The
sidebar shows the total unread count on every page.

**Independent Test**: Two patients each send a message; the inbox lists both with unread counts,
opening one marks it read, and a reply appears in that patient's view only.

**Acceptance Scenarios**:

1. **Given** unread messages from P-017 and P-021, **Then** the inbox lists both, newest first, each
   with its unread count, and the sidebar shows the total.
2. **Given** the therapist opens P-017's thread, **Then** its messages are marked read and the
   counts update; P-021's stay unread.
3. **Given** the therapist sends a reply, **Then** it is stored with its time and appears in
   P-017's conversation, and nowhere else.
4. **Given** a patient with messaging off, **Then** the therapist can turn it on from the thread or
   the Patients page, and can turn it off again; off hides the conversation from the patient and
   refuses new messages, and keeps what was written.
5. **Given** the roster and the work queue, **Then** patients with unread messages are marked, and
   the queue has an "Unread messages" section.

### User Story 2 - The Patient's Conversation (Priority: P1)

A signed-in patient opens Messages, sees the conversation with their therapist, and can write.
A notice says this is not for emergencies and not monitored around the clock.

**Acceptance Scenarios**:

1. **Given** messaging is on, **Then** the patient sees the thread oldest to newest, an unread
   marker on Today when the therapist has written, and a box to write in.
2. **Given** the patient sends a message, **Then** it appears in the thread at once and in the
   therapist's inbox as unread.
3. **Given** messaging is off for the patient, **Then** no Messages entry is shown and sending is refused.
4. **Given** the Messages page, **Then** it always shows: "Not for emergencies. Your therapist reads
   messages during working hours. If this is urgent, call your clinic or emergency services."

### User Story 3 - Context in the Thread (Priority: P2)

Next to a thread the therapist sees the patient's last session summary and open flags, and can
start a message from a session ("About your session on 19 Sep ..."), so a conversation has context
without searching.

### User Story 4 - Safety Rails (Priority: P2)

Messages have a length limit, a per-patient rate limit, and a check that warns the writer when the
text looks like it contains a name, phone number, email address, or date of birth, before sending.

### Edge Cases

- The patient's access code is revoked mid-conversation: the thread stays for the therapist; the
  patient cannot read or send.
- A patient is discharged: the thread becomes read-only for both sides.
- Two therapist tabs open the same thread: read marks and replies do not duplicate.
- Very long or pasted text, emoji, right-to-left text, and line breaks are stored and shown exactly,
  and never interpreted as markup.

## Requirements *(mandatory)*

- **FR-001**: The therapist app MUST have an Inbox listing one conversation per patient with latest
  activity, first line, and unread count, newest first, and a total unread count in the sidebar.
- **FR-002**: Opening a thread MUST mark the other side's messages read; read state MUST be per side.
- **FR-003**: Therapist and patient MUST each be able to send plain-text messages of 1 to 2,000
  characters; text MUST be stored and displayed as plain text only.
- **FR-004**: Messaging MUST be off by default and turned on or off per patient by the therapist.
- **FR-005**: A patient MUST see and send only in their own conversation; no request may name a
  patient; the patient view's no-leak test MUST cover the message routes.
- **FR-006**: The patient Messages page MUST always show the not-for-emergencies notice.
- **FR-007**: Unread messages MUST appear on the roster and in the work queue.
- **FR-008**: Before sending, both sides MUST be warned when the text matches the existing privacy
  patterns (names, dates of birth, six-digit record numbers) or looks like a phone number or email
  address, and MUST be able to edit or send anyway; the choice to send anyway MUST be recorded.
- **FR-009**: Sending MUST be rate-limited per patient (20 messages an hour) and refused for
  discharged patients and revoked access.
- **FR-010**: Deleting a patient MUST delete their conversation; the therapist MUST be able to
  delete a single message (for example one containing identifying details), leaving a "message
  removed" marker.
- **FR-011**: Message events (sent, read, deleted, messaging on or off) MUST be recorded in the
  access history without the message text.
- **FR-012**: No attachments, links made clickable, images, or voice in this version.

### Key Entities

- **Conversation**: one per patient; messaging on or off; last activity.
- **Message**: conversation, sender side (therapist or patient), text, sent time, read time,
  removed marker, sent-despite-warning marker.

## Success Criteria

- **SC-001**: 0 responses to a patient contain another patient's message or ID.
- **SC-002**: A reply sent by the therapist is visible to the patient within 5 seconds of their next
  page load or poll.
- **SC-003**: 100% of message text is rendered as plain text (no markup execution).
- **SC-004**: The therapist can see who is waiting for a reply from any page (sidebar count).

## Open questions for the owner (max 3)

1. **[NEEDS CLARIFICATION: free text and privacy]** Free-text messages are the first place a
   patient can type identifying or clinical details. For study use, is warn-and-allow (FR-008)
   acceptable, or should messages that match a privacy pattern be blocked outright?
2. **[NEEDS CLARIFICATION: who is "the doctor"]** Today there is one therapist password per
   installation, so every message is from "your therapist". Do you need named therapists (several
   accounts, each with their own inbox and patients) now, or is one shared inbox enough for v1?
3. **[NEEDS CLARIFICATION: notifications]** Should the therapist be notified outside the app (for
   example by email) when a patient writes? That would send data to an email provider and store an
   email address, which the constitution currently forbids.

## Assumptions

- Polling on page load and every 30 seconds while a thread is open; no push notifications.
- One shared therapist inbox until named accounts exist.
- Depends on feature 007 (patient sign-in, therapist sign-in, access history).
