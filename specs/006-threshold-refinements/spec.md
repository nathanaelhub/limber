# Feature Specification: Threshold Refinements

**Feature Branch**: `006-threshold-refinements`

**Created**: 2026-09-21

**Status**: Draft

**Input**: User description: "Finish the two ideas left open by feature 005: attention thresholds
that can differ per exercise for a patient, and a history of threshold changes so a PT can see
who-less but when and what changed."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Per-Exercise Thresholds (Priority: P1)

A patient does several exercises with different expectations: after knee surgery a 5° loss of
knee-extension range matters, while the same patient's squat depth varies more from day to day.
The PT sets a threshold for one exercise of one patient; the patient's other exercises keep the
patient's value.

**Why this priority**: One number per patient still produces noise for one exercise or silence
for another.

**Independent Test**: A patient has a 6° ROM drop in both Knee Extension and Squat. With a
Knee Extension threshold of 5°, only Knee Extension is flagged, and the flag says the threshold
is the exercise's.

**Acceptance Scenarios**:

1. **Given** P-017 has a 6° drop in Knee Extension and in Squat and no overrides, **When** the
   PT sets ROM regression to 5° for Knee Extension only, **Then** flags show a regression for
   Knee Extension stating `threshold 5 degrees`, and none for Squat.
2. **Given** an exercise override exists, **When** the PT lists thresholds for that exercise,
   **Then** the value shows origin "exercise" and the default it would fall back to (the
   patient's value).
3. **Given** an exercise override exists, **When** the PT resets it, **Then** the patient's
   value applies to that exercise again.
4. **Given** the PT tries to set practice gap or adherence for an exercise, **Then** it is
   rejected with a message that these two apply to the whole patient.
5. **Given** "reset all" for the patient, **Then** exercise overrides are removed too.

---

### User Story 2 - Threshold Change History (Priority: P2)

A PT wonders why a patient's flags changed since last week, opens the threshold history, and
sees each change: when, which threshold, for the patient, one exercise, or the installation, the
old value, and the new value.

**Why this priority**: Once thresholds differ by patient and exercise, an unexplained change in
flags must be traceable to a settings change.

**Independent Test**: Set, change, and reset a threshold; the history lists three entries newest
first with the right old and new values.

**Acceptance Scenarios**:

1. **Given** no override, **When** ROM regression is set to 5, then 6, then reset, **Then** the
   patient's history shows, newest first: `6 → default`, `5 → 6`, `default → 5`, each with its
   time.
2. **Given** a value is saved that equals the stored value, **Then** no history entry is added.
3. **Given** installation values changed, **When** the installation history is listed, **Then**
   it shows those changes; a patient's history also shows installation changes, marked as
   installation, because they affect the patient's effective values.
4. **Given** a patient is deleted, **Then** their history is removed with them.

---

### User Story 3 - Exports Name Exercise Thresholds (Priority: P3)

The review report lists exercise-specific thresholds under the thresholds section so a reader
knows a flag came from an exercise's value.

**Acceptance Scenarios**:

1. **Given** a Knee Extension override of 5°, **When** the review report is exported, **Then**
   the thresholds section contains `Knee Extension: ROM regression 5 degrees (exercise override)`.
2. **Given** the review CSV, **Then** each row's `thresholds_in_use` cell reflects the values in
   use for that row's exercise, marking exercise overrides.

### Edge Cases

- The exercise is identified by its display name as stored in sessions (the same name trends and
  flags use); an override for an exercise the patient has never performed is allowed.
- Upgrade: existing patient and installation values are kept; history starts empty.
- History records settings changes only; it holds no clinical data and no names.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A PT MUST be able to set, list, and reset thresholds for one exercise of one
  patient, for these six: form drop, ROM regression, ROM plateau, sessions below target,
  partial-rep share, partial-rep rise; practice gap and adherence MUST be rejected at exercise
  level with an explanatory message.
- **FR-002**: The value in use for an exercise MUST be the exercise override, else the patient
  override, else the installation value, else the built-in default, with origin "exercise",
  "patient", "installation", or "default".
- **FR-003**: Flags for an exercise MUST use that exercise's effective values everywhere flags
  appear (flags view, review summary, roster, queue, exports), and the evidence MUST state the
  threshold that applied.
- **FR-004**: Resetting all of a patient's thresholds MUST remove exercise overrides as well.
- **FR-005**: Every change of a stored threshold (patient, exercise, installation; set, reset,
  reset all, restore defaults) MUST add a history entry with time, scope, patient and exercise
  where applicable, threshold, old value, and new value; saving an unchanged value MUST NOT.
- **FR-006**: A PT MUST be able to list a patient's history (including installation changes,
  marked) and the installation's history, newest first, from the command line and the web app.
- **FR-007**: Exercise overrides and a patient's history MUST be removed when the patient is
  deleted and MUST follow a patient whose ID changes.
- **FR-008**: The review report MUST list exercise overrides in its thresholds section, and the
  review CSV's thresholds cell MUST reflect the row's exercise.
- **FR-009**: With no exercise overrides, all results MUST be identical to feature 005.
- **FR-010**: All data MUST remain local; history MUST contain no free text.

### Key Entities

- **Exercise Threshold Override**: patient, exercise name, threshold, value.
- **Threshold Change**: time, scope, patient, exercise, threshold, old value, new value.

## Success Criteria *(mandatory)*

- **SC-001**: With no exercise overrides, 100% of flags, roster rows, queue items, and exports
  equal feature 005's.
- **SC-002**: 100% of stored threshold changes appear in the history with correct old and new
  values; 0 entries for unchanged saves.
- **SC-003**: A PT can set an exercise threshold and see the flag change in under one minute.
- **SC-004**: The 50-patient roster stays inside its existing time budget.

## Assumptions

- No user accounts exist, so history records when and what, not who.
- History is never edited or pruned by the app; it goes away only with its patient.
- Adherence and practice gap are patient-level concepts and stay so.
