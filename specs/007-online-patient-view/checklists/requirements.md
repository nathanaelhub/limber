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
- The frame-rate figures in Assumptions come from a replay experiment run outside the repository;
  the browser-model comparison (SC-008) is still to be run during planning.
- The spec names one change to an earlier feature: 004's "one running session per installation"
  becomes "one running session per patient" (FR-012).
