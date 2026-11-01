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

## Constitution amendment v1.3.0 (Principle III), applied 2026-10-30

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
3. **Given** a withheld message the therapist dealt with by phone, **When** they press **Mark as handled by
   phone**, **Then** it leaves the inbox's "may need a direct response" list, its unread count clears, and
   the record keeps who marked it and when. Nothing is sent to the patient. (Added 2026-10-30 from the
   Claude Design review, `design/limber-export/screens/TherapistInbox.html`, state 5b.)

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

- **FR-009**: A withheld message can be marked **handled by phone**: it clears from the inbox flag and the
  unread count, sends nothing, and is recorded with the therapist and time (US2 scenario 3).

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

## Slice A as built (2026-10-30)

The therapist assistant (US1, US2, FR-009) is built; the coach (US3) is not, and only its switch is stored.
Tasks and tests: `specs/018-ai-assistant/tasks.md`. Where the build differs from or adds to the text above:

- **Fallbacks (FR-003)**: server-side fallbacks are documented for the installed SDK (`anthropic` 2.3.0), so
  requests send `fallbacks: "default"` with the `server-side-fallback-2026-07-01` beta through
  `client.beta.messages.create`. Live calls accept it together with the JSON output schema.
- **Effort**: `medium` for both summaries and drafts, set explicitly (the model's default). Live summaries on
  the demo record took 13–16 s, drafts 4–7 s, inside the 30-second target.
- **Prompt caching (FR-004)**: both cache breakpoints are sent (system prompt, then the extract), but slice A
  requests are about 1,300–2,100 input tokens, below the model's minimum cacheable prefix, so nothing is
  cached yet. The breakpoints cost nothing and will take effect for the coach's longer, repeated prefix.
- **Summary output**: a JSON schema through structured outputs (`output_config.format`). The host still
  validates it: a claim or next step with no record ID from the extract is dropped, at most 3 next steps are
  kept, and the panel says how many statements were left out. Output that does not parse is "unavailable".
- **The extract (FR-006)** leaves out the plan's diagnosis, the patient's label, and the patient's notes as well
  as every account field, because none of them is in the amendment's list of text records. Photos,
  documents, and recordings are named as sent, never included; the prompts say so, so a draft never claims
  one did not arrive.
- **Red flags (FR-005)**: the list is `src/assist/red_flags.txt`. A draft is withheld when any patient message
  since the therapist's last reply in that plan trips it, not only the last one. The notice quotes the words
  the patient wrote ("P-023 mentioned “had a fall”, “numb”").
- **Mark as handled by phone (FR-009)** clears the message from the attention flag and allows a draft again;
  it is recorded in `message_handled` with the account and time. The unread count clears when the therapist
  opens the conversation, as for every message.
- **Session notes**: Limber had no free-standing therapist note, so slice A adds `therapist_notes`. A saved
  summary keeps an "AI-drafted" marker, plus "edited" when the therapist changed it. The design's "until you
  edit and sign it" is not used, because Limber does not sign notes.
- **Daily cap**: counted per signed-in account per day (the account-less private machine counts as one);
  `assist_daily_cap` in clinic settings, default 50. Every call that reached the API counts, whatever its
  outcome.
- **Patient notice**: the Settings page shows, in plain words, each switch the therapist turned on and that
  the processor is Anthropic (`GET /api/me/assistant`). Nothing shows when no key is configured.
- **A draft never follows the therapist to another conversation**: found in the browser walk and fixed; a
  test pins it.
- **Deleting a patient** also deletes their rows in the call log, which has no foreign key because it is a log.

