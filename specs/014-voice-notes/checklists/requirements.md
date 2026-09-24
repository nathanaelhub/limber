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
