# Specification Quality Checklist: Voice Notes, with a Transcript for the Therapist

**Purpose**: Validate specification completeness and quality before planning

**Created**: 2026-09-24

**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) — the named audio containers are the
      constraint (what phones produce), not a design choice, and the "no third party" rule is a privacy
      requirement from the constitution
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain (owner-approved plan of 2026-09-23)
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded — two separable slices; no spoken answers during exercises
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Constitution

- [x] Principle III check present (v1.2.0), including the reason audio is treated more carefully than
      body points: a voice identifies a person
- [x] Principle IV: FR-014 keeps model weights and network calls out of the suite
- [x] Principle V: the new dependency is required to be justified in the plan and to be optional at
      runtime (FR-009, FR-014)

## Notes

- **The one thing this spec deliberately refuses**: using the browser's speech recognition, which would
  send the patient's voice to Apple or Google. That is what made feature 015 unworkable, and it is why
  transcription here is host-only.
- **The split matters more than the transcript.** User Stories 1 and 2 need no new dependency and no
  model; User Story 3 needs both. The spec requires the installation to work with the model absent, so the
  owner can decide about the dependency separately from the feature.
- Deciding to install the speech model and its dependency on the owner's machine is the owner's call, not
  the implementer's: the plan will build and verify Stories 1 and 2 first and stop for that decision
  before installing anything.

## Implementation notes — Slice A (a voice note that arrives and plays)

- **Feature 011 had already reserved the `voice` kind** in the probe (180 s, 10 MB, no video stream), so
  the audio side was limits and wording rather than new machinery: MP3 and WAV added to the containers a
  phone may produce, a refusal for a file that carries a picture, and audio-specific sentences behind the
  same reason words the access history records.
- **The message link needed no schema change**: `media.message_id` has existed since feature 011, so the
  recording points at the message and `Message.media_id` is read back through it. v13 is one new table.
- **Three defects the browser run found that the suite had not**, all now covered by tests:
  1. `/api/media` listed clips only, so the voice page showed an empty list.
  2. The patient's conversation page never drew a player for a message carrying audio.
  3. The service's `permissions-policy` header still said `microphone=()`, so recording was blocked
     outright — the plan had predicted this one and it was still missed until the browser said so.
- **A fixture that took a minute**: audio built 1024 samples at a time is dominated by per-frame Python
  overhead. Handing the encoder one second at a time made a 200-second file cost a tenth of a second.
- **An unreachable reason word**: `no_audio` cannot be produced by any fixture, because a real file
  without audio either carries video (refused as a clip's business) or cannot be opened at all. The word
  stays, with a test that pins its wording and says why.
- **The suite's own slowness was not a regression**: a 23-minute run turned out to be two full suites
  competing on one machine. Run alone it is under two minutes.
- **`src/media/transcribe.py` exists in Slice A** but only answers whether this installation could write
  audio out at all, so the inbox can say plainly that it cannot. No model, no dependency, no worker.

## The stop before Slice B

Installing `faster-whisper` and downloading model files onto the owner's machine and the host is the
owner's decision, not the implementer's, so the plan stops here and asks. Slice A is merged and usable
either way, and the installation behaves identically with no model present.
