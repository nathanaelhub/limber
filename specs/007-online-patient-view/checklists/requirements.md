# Specification Quality Checklist: Online Patient View

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-21
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Owner decisions recorded on 2026-09-21: home use over the internet; demo and study participants
  only; pose detection in the browser; run on one machine now; therapist-issued access codes;
  separate launch; the patient sees today's program, a guided session, progress, and a streak.
- Defaults chosen rather than asked, under Assumptions: 90-day code lifetime; a second device is
  refused; the patient sees their pseudonymous ID; no reset control for patients; 15 frames per
  second nominal with a floor of 12.
- The constitution was amended to 1.1.0 for this feature (networked-feature guarantees; the
  patient portal as the one patient-facing interface).
- The frame-rate figures in Assumptions come from a replay experiment run outside the repository.
- Spec changed during planning (2026-09-21): the browser-model comparison showed identical rep
  counts but range of motion differing by 3 to 24 degrees between models, so SC-008's 5-degree
  requirement was replaced, FR-020 and SC-009 were added (home and clinic sessions are never
  compared with each other), and the Assumptions carry the measured numbers.
- The spec names one change to an earlier feature: 004's "one running session per installation"
  becomes "one running session per patient" (FR-012).

## Implementation notes (2026-09-21)

- Suite: 639 passed, 1 skipped, with no network, camera, model, or browser.
- Quickstart 1 to 5: run. Sign-in, Today's plan, a guided session, refusals, revocation, the access
  history, and two sessions at once are covered by tests; steps 3 and 4 were also driven in Chrome.
- Quickstart 7: run twice in headless Chrome with a fake camera fed from the sample squat clip:
  sign-in, Today's plan, camera start, reps counted (3), next exercise, finish, summary; the stored
  session has origin `portal`; the page made no request to any other site; the console was clean under
  the content security policy (`wasm-unsafe-eval` was enough for the WebGL backend).
- Quickstart 6 (a real phone through an HTTPS tunnel): NOT run. It needs the owner's device and a
  tunnel they accept for the study.
- Not yet tried by a person: a real camera with a real person at home.
- Added at the owner's request during implementation: US6 (one front page, therapist sign-in gating
  the therapist app; schema v7) and the Limber brand.
- Known: after the therapist hand-over the single-use pass can stay visible in the address bar of a
  real browser; it cannot be reused and expires after one minute.
- Known: the engine's "Shoulders uneven by 178 deg" message appears in side-on views at home as in
  the clinic; an engine matter, not changed here.
- Test-first exceptions: the access module and the therapist sign-in module were written in the same
  step as their tests.
