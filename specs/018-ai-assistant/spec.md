# Feature Specification: AI Assistant for the Therapist and an Exercise Coach for the Patient

**Feature Branch**: `018-ai-assistant`

**Created**: 2026-10-29

**Status**: Approved by the owner on 2026-10-30. Requires constitution amendment v1.3.0 (below).

**Input**: Owner chose three uses for the Anthropic API key: (A) therapist assistant — weekly summary,
suggested next steps, draft replies, reviewed by the therapist before anything reaches the patient;
(B) patient exercise coach — questions answered from the patient's own program, with "ask your therapist"
limits; (C) transcribe voice notes through the API.

## Finding on (C): the Claude API does not accept audio

Checked 2026-10-29 against the Models API with our key: `claude-opus-5-5`, `claude-sonnet-5-5`, and
`claude-haiku-5-5` report `image_input` and `pdf_input` and no audio input. Voice notes cannot be
transcribed with this key. **(C) is dropped from this feature.** Voice notes keep the 014 design:
transcription on the Limber host, built and waiting for a model file. Once that produces a transcript,
(A) can read it like any other text, since the transcript stays on the host and only text goes to the
API, under the same rules as the rest of (A).

## Constitution amendment v1.3.0 (Principle III), proposed

Principle III currently forbids third-party processing of patient uploads and requires every networked
feature to be opt-in and specified. This feature sends patient **text** to Anthropic, so it needs an
explicit allowance. Proposed text, added to Principle III:

> A feature MAY send a patient's text records (logs, diary, questionnaire answers, messages, and
> transcripts produced on the host) to one named AI processor, only if: it is off until the therapist
> turns it on for that patient; the patient has been told in plain words that their records are processed
> by that service; requests carry the pseudonymous ID and never the display name, username, or any
> account field; no audio, video, photo, or document is sent; every request and response is logged on
> the host with its size and purpose, without its content; and the processor's data-retention terms are
> stated in the feature's spec. The named processor is Anthropic (Claude API). Real clinic patients still
> require the compliance review.

Retention: by default the API keeps request data for a limited period for safety review; zero-data
retention needs an agreement with Anthropic and is not assumed. Fable models require 30-day retention and
are not used by this feature.

## Constitution Check (Principle III, as amended)

| Requirement | This feature |
|-------------|--------------|
| What crosses the network | For one patient at a time: their pseudonymous ID, program, recent logs, diary, questionnaire scores, and messages (A); their program and the coach conversation (B). |
| What never does | Display names, usernames, audio, video, photos, documents, other patients' data. |
| Off by default | Each use (A, B) is a per-patient switch, off until the therapist turns it on. With no API key configured, the switches are hidden and nothing is sent. |
| Who may use it | Demo and consented study participants only. |
| Patient sees only their own | The coach answers only from the signed-in patient's own plan; no request can name a patient. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Therapist Gets a Weekly Summary (Priority: P1)

On a patient's page the therapist presses **Summarise the last 7 days**. Within about 30 seconds Limber
shows a short summary (adherence, pain trend, diary and questionnaire changes, anything the patient asked)
and 1–3 suggested next steps, each pointing at the records it came from. The text is marked
"AI-drafted — check before acting". The therapist can save it as a session note, edit it first, or
discard it.

**Acceptance Scenarios**:

1. **Given** a patient whose pain rose over the week (demo P-021), **Then** the summary names the rise and
   links to the log entries that show it.
2. **Given** a patient with no records in the week, **Then** Limber says so without calling the API.
3. **Given** the API is unreachable or refuses, **Then** the therapist sees "The assistant isn't available
   right now" and the page works otherwise.
4. **Given** the switch is off for that patient, **Then** the button is absent.

### User Story 2 - The Therapist Gets a Draft Reply (Priority: P1)

In a conversation the therapist presses **Draft a reply**. A draft appears in the reply box, never sent
automatically. The therapist edits and sends it, or clears it. A sent message records whether it began as
a draft.

**Acceptance Scenarios**:

1. **Given** a draft, **Then** nothing reaches the patient until the therapist presses Send.
2. **Given** the patient's last message mentions chest pain, numbness, a fall, or similar red flags,
   **Then** the draft is withheld and the therapist sees "This message may need a direct response" instead.

### User Story 3 - The Patient Asks the Exercise Coach (Priority: P2)

A patient whose therapist has turned the coach on sees **Ask about your exercises** on their plan. They can
ask things like "how far should my knee bend in heel slides?" The coach answers only from that patient's
program, the exercise instructions, and the therapist's notes on each exercise, and says so. Questions
about pain getting worse, new symptoms, medication, or changing the program get "That's one for your
therapist" with a button to message them. Red-flag words get the emergency message (call 911 or go to
the nearest emergency room) and nothing else.

**Acceptance Scenarios**:

1. **Given** a question about an exercise in the program, **Then** the answer uses only that exercise's
   prescribed dose and instructions.
2. **Given** "can I do more reps than prescribed?", **Then** the coach refers them to their therapist.
3. **Given** "my calf is swollen and hot", **Then** the emergency message is shown and the model is not
   called.
4. **Given** a therapist opens the patient, **Then** they can read every coach conversation.
5. **Given** the coach is switched off mid-conversation, **Then** the next question gets "The coach is
   turned off — message your therapist instead."

### Edge Cases

- A patient sends 30 questions in an hour: after 20 per day the coach asks them to message their therapist.
- The model's answer contradicts the prescribed dose: a check on the host compares numbers in the answer
  against the program and replaces the answer with the referral if they differ.
- A response stops on `refusal` or `max_tokens`: treated as unavailable, never shown partially.

## Requirements *(mandatory)*

- **FR-001**: One module, `src/assist/`, is the only code that calls the API. Everything else calls it
  through an interface that tests replace with a fake; no test makes a network call.
- **FR-002**: The key is read from `LIMBER_ANTHROPIC_API_KEY` (in the gitignored `.env`), never from the
  shell's `ANTHROPIC_API_KEY`. No key: features hidden, preflight reports "AI assistant: off (no key)".
- **FR-003**: Models: `claude-opus-5-5` for summaries and drafts (A); `claude-sonnet-5-5` for the coach
  (B), which needs a fast answer. Both with adaptive thinking; the Opus requests use server-side
  fallbacks so an overloaded primary does not fail the request.
- **FR-004**: The fixed system prompt and the patient's program go first in each request with prompt
  caching, so repeated coach questions reuse them.
- **FR-005**: Red-flag screening runs on the host before any request (B) and before drafting (A), from a
  word list in the repository that tests cover.
- **FR-006**: Requests are built from a pseudonymised record extract; a test asserts that no account
  field can appear in any request body.
- **FR-007**: Every call is logged on the host: time, patient ID, purpose, model, input and output
  tokens, outcome. Not the content.
- **FR-008**: New dependency: the `anthropic` Python SDK. Justified under Principle V: it is the official
  client, and writing HTTP calls by hand would mean re-implementing its retries and error types.

## Success Criteria

- **SC-001**: For the three demo patients, a therapist reviewer judges every summary accurate against the
  records (no claim without a linked record).
- **SC-002**: A test set of 40 coach questions (20 in scope, 10 for the therapist, 10 red flags) gets the
  right kind of response every time: red flags by the host check, the rest checked on recorded
  model outputs.
- **SC-003**: With no key configured, the full existing test suite passes and no screen shows an AI
  control.

## Assumptions

- Cost: summaries are on demand, not scheduled, so cost follows use. A per-day cap per therapist is a
  setting (default 50 calls).
- No AI answer is ever sent to a patient without a therapist, except the coach's answers, which the
  therapist turned on and can read.
