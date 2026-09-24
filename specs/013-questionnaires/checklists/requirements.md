# Specification Quality Checklist: Assigned Questionnaires

**Purpose**: Validate specification completeness and quality before planning

**Created**: 2026-09-24

**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) — YAML and "entry of kind questionnaire"
      are the owner's own stated constraints, carried over from the approved plan, not invented here
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
- [x] Scope is clearly bounded — engine plus one demo instrument; no reminders, no thresholds or flags
      from a score, no licensed instrument reproduced
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Constitution

- [x] Principle III check present (v1.2.0): what crosses the network, who may use it, deletion,
      host-only processing
- [x] Principle V: every number carries a unit and a plain-language meaning (FR-013)

## Notes

- The one real risk this spec carries is that a scoring engine invites clinical interpretation. The
  spec deliberately forbids deriving any threshold or attention flag from a questionnaire score in this
  feature, and the meaning shown always comes from the definition file rather than from the code.
- No licensed instrument's items appear anywhere in the repository. The demo instrument is written for
  this project so that the engine can be tested and demonstrated without a licence.

## Implementation notes (filled in as the feature was built)

- **Test-first held throughout this feature**: the loader, the scoring engine, the schema, the patient
  routes, and the therapist views each had a failing test file before any implementation. Two tests had
  to be corrected because *they* were wrong, not the code: the overdue boundary (the spec says "more
  than seven days", so exactly seven is not yet overdue) and a total of 21 that a comment had claimed
  was 22.
- **The identifying-details check could not reuse the free-text one.** `privacy.NAME_RE` treats two
  capitalised words in a row as a name, which would refuse the honest title "Demo Knee Function".
  Instruments are checked instead by what an item asks for (a name, a date of birth, a record number, an
  address, a phone number, an email), which is the thing the rule is actually about.
- **`entries.kind` already allowed `questionnaire`** (feature 010 left it in the CHECK constraint), so
  unlike feature 012 this migration rebuilt nothing: v12 is one `CREATE TABLE` plus a partial unique
  index for "one live assignment per instrument per patient".
- **A questionnaire's fields are not in the entry registry.** `ENTRY_KINDS["questionnaire"]` carries no
  fields, which is the signal that its shape comes from the assigned instrument; the route branches to
  `src/portal/questionnaires.accept` rather than the generic validator.
- **The scoring snapshot was worth the bytes.** It is what makes FR-008/SC-002 true without keeping old
  definition files: an edited or deleted instrument cannot move a stored score, and the therapist is
  told which version each score came from.
- **The per-session review CSV was left alone.** A questionnaire is not a session, so it is a second
  file (`to_questionnaire_csv`) plus a report section, rather than a row with most columns empty.
- **Deliberately not done**: no attention flag or threshold from a score (the spec forbids it), no
  reminders, no branching or skip logic, no free-text items, no scoring bands, and no rescoring of stored
  answers. The patient cannot delete an answered questionnaire.
- **Verified in the browser** (emulated iPhone, demo record): due on Today, the ten questions with their
  own words and both choice sets, the progress line with the minimum, six answers surviving a reload,
  too few refused with nothing stored, the total shown with its unit and direction, the draft cleared
  after sending, Today no longer offering it, the connection dropping mid-questionnaire and the answers
  being queued and then sent on reconnecting, and on the therapist side the scores, the first-to-latest
  change, the item answers with the reversed marker, the overdue questionnaire named in the queue, and
  assigning one from the Patients page. No console errors.
- **Not verified**: a real phone, a real licensed instrument, and how a twenty-item questionnaire feels
  to answer on a small screen.
