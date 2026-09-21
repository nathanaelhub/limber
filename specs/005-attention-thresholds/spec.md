# Feature Specification: Configurable Attention Thresholds

**Feature Branch**: `005-attention-thresholds`

**Created**: 2026-09-20

**Status**: Draft

**Input**: User description: "Configurable attention thresholds: a PT can tune, per patient, the
thresholds the review flags and the tracker use to decide that a patient needs attention. Today
only the practice-gap threshold is per patient; the other flag thresholds (form drop in points,
range-of-motion regression and plateau in degrees, consecutive sessions below target reps,
partial-rep share and rise in percent) are fixed constants, and the adherence threshold is one
value for the whole installation. A post-operative patient and a conditioning patient should not
be judged by the same numbers. The PT sees each threshold with its unit, its plain-language
meaning, its default, and whether the patient uses the default or an override; changes one;
resets one or all to the default; and every flag, the roster, the queue, and the review report
use the patient's values from then on and say which threshold produced a flag. Installation
defaults can also be changed. All data stays local."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Tune a Patient's Flag Thresholds (Priority: P1)

A PT opens a patient's review settings and sees every attention threshold with its unit, meaning,
default, and current value. They change one (for example the range-of-motion regression
threshold from 10° to 5° for a post-operative knee), and the patient's flags are evaluated with
that value from then on.

**Why this priority**: This is the core value: flags that fit the patient. Fixed numbers produce
either noise or silence for patients at the extremes.

**Independent Test**: With a patient whose latest session is 6° below their recent best, no
regression flag exists at the default 10°; set the threshold to 5° and the flag appears, naming
the 5° threshold in its evidence; reset and it disappears.

**Acceptance Scenarios**:

1. **Given** patient P-017 has no overrides, **When** the PT lists thresholds, **Then** each of
   the eight thresholds is shown with name, unit, meaning, default value, current value, and
   "default" as its origin.
2. **Given** P-017's ROM regression threshold is set to 5°, **When** flags are evaluated and the
   latest session is 6° below the best of the previous three, **Then** the regression flag is
   raised and its evidence states the 5° threshold.
3. **Given** an override exists, **When** the PT resets that threshold, **Then** the default
   applies again and the origin shows "default".
4. **Given** several overrides exist, **When** the PT resets all, **Then** every threshold
   returns to its default, including the practice-gap threshold.
5. **Given** a value outside the allowed range or not a whole number, **When** the PT saves it,
   **Then** it is rejected with a message stating the allowed range and unit, and nothing
   changes.

---

### User Story 2 - Per-Patient Adherence Threshold (Priority: P2)

A PT sets the adherence percentage below which a specific patient is marked as needing
attention on the roster and queue; patients without an override keep the installation value.

**Why this priority**: The roster's attention sort is the daily entry point; one number for all
patients misorders it.

**Independent Test**: Two patients at 55% adherence with the installation threshold at 60%: both
need attention; set one patient's threshold to 50% and only the other remains flagged for
adherence.

**Acceptance Scenarios**:

1. **Given** the installation threshold is 60% and P-017 has an override of 50%, **When** the
   roster is built and P-017's adherence is 55%, **Then** P-017 is not marked for low adherence
   while a patient without an override at 55% is.
2. **Given** P-017's override is reset, **When** the roster is built, **Then** the installation
   value applies to P-017 again.
3. **Given** the adherence view for P-017, **Then** it states the threshold in use and whether
   it is the patient's or the installation's.

---

### User Story 3 - Installation Defaults (Priority: P3)

A clinic lead changes the installation default for a threshold; every patient without an
override uses the new default, patients with overrides are unaffected, and the original
built-in defaults can be restored.

**Why this priority**: Useful for a clinic with a consistent population, but per-patient tuning
already delivers most of the value.

**Independent Test**: Change the installation default for the form-drop threshold from 10 to 8
points; a patient without an override is evaluated at 8, a patient with an override of 12 stays
at 12; restoring built-in defaults returns the first patient to 10.

**Acceptance Scenarios**:

1. **Given** the installation default for form drop is set to 8 points, **When** thresholds are
   listed for a patient without an override, **Then** the current value is 8 with origin
   "installation".
2. **Given** a patient override of 12, **When** the installation default changes, **Then** the
   patient's value stays 12 with origin "patient".
3. **Given** installation defaults were changed, **When** built-in defaults are restored,
   **Then** every installation value equals the built-in default; patient overrides remain.

---

### User Story 4 - Thresholds Visible Where Decisions Are Read (Priority: P4)

The review report, the review CSV, and the flags view state the thresholds that were in use for
the patient, marking the ones that differ from the built-in defaults, so a reader of an export
knows how the flags were produced.

**Why this priority**: Keeps exports interpretable once thresholds differ between patients.

**Independent Test**: Export a review report for a patient with one override; the report lists
the thresholds in use and marks the overridden one.

**Acceptance Scenarios**:

1. **Given** P-017 has a ROM regression override of 5°, **When** the review report is exported,
   **Then** it contains a thresholds section listing all values with units and marks the 5°
   value as a patient override.
2. **Given** no overrides and no installation changes, **When** the report is exported,
   **Then** the thresholds section states that built-in defaults were used.

---

### Edge Cases

- A patient is deleted: their overrides are removed with them.
- A patient ID is changed: overrides follow the patient.
- An override equal to the current default is stored as an override (origin "patient") and
  stays fixed if the default later changes.
- The number of sessions each rule looks at (four, or three for target reps) is part of each
  rule's definition and is not configurable, except the consecutive-sessions-below-target
  count, which is a threshold.
- Thresholds changed after a review was marked do not alter the stored review; flags are always
  computed from current thresholds when viewed.
- Existing installations keep their current practice-gap overrides and installation adherence
  value after the upgrade.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST define these thresholds, each with a name, unit, plain-language
  meaning, built-in default, and allowed whole-number range: practice gap (days, 7, 1-90);
  form drop (points, 10, 1-50); ROM regression (degrees, 10, 1-60); ROM plateau (degrees, 3,
  1-30); sessions below target reps (sessions, 3, 2-10); partial-rep share (percent, 25,
  1-100); partial-rep rise (percentage points, 10, 1-100); adherence (percent, 60, 1-100).
- **FR-002**: A PT MUST be able to list a patient's thresholds showing, for each, the current
  value, the default it would otherwise use, and its origin: "patient", "installation", or
  "default".
- **FR-003**: A PT MUST be able to set, reset one, and reset all per-patient overrides; invalid
  values MUST be rejected with the allowed range and unit and leave stored values unchanged.
- **FR-004**: Flag evaluation MUST use the patient's effective thresholds (patient override,
  else installation value, else built-in default) everywhere flags appear: flags view, session
  review view, review summary, roster, queue, and exports.
- **FR-005**: A raised flag's evidence MUST state the threshold value that applied.
- **FR-006**: Roster and queue adherence attention MUST use the patient's effective adherence
  threshold, and the adherence view MUST state the threshold in use and its origin.
- **FR-007**: A clinic lead MUST be able to set and reset installation values for every
  threshold and restore all built-in defaults; patient overrides MUST be unaffected.
- **FR-008**: The review report and review CSV MUST include the thresholds in use and mark
  values that differ from the built-in defaults with their origin.
- **FR-009**: Existing practice-gap overrides and the existing installation adherence value
  MUST be preserved by the upgrade, and the existing commands and controls for them MUST keep
  working.
- **FR-010**: With no overrides and no installation changes, every flag, roster, queue, and
  export result MUST be identical to the results before this feature, apart from the added
  thresholds section and evidence wording.
- **FR-011**: Overrides MUST be removed when their patient is deleted and MUST follow a patient
  whose ID changes.
- **FR-012**: Threshold management MUST be available from both the command line and the web
  app, and all data MUST remain on the local machine.

### Key Entities

- **Threshold Definition**: key, name, unit, meaning, built-in default, allowed range.
- **Patient Threshold Override**: patient, threshold key, value.
- **Installation Threshold Value**: threshold key, value.
- **Effective Threshold**: the value in use for a patient with its origin.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a caseload with no overrides, 100% of flags, roster rows, and queue items are
  unchanged from before the feature.
- **SC-002**: A PT can change one threshold for a patient and see the flags update in under
  one minute on first use.
- **SC-003**: 100% of raised flags state the threshold that applied.
- **SC-004**: 100% of invalid values are rejected with the allowed range and unit.
- **SC-005**: Building the roster for 50 patients with 20 sessions each stays within the
  existing roster time budget with per-patient thresholds in use.
- **SC-006**: 100% of review exports state the thresholds in use.

## Assumptions

- **Whole numbers only**; the existing thresholds are whole numbers and clinical use does not
  need finer steps.
- **Rule window sizes stay fixed** (see Edge Cases); only the values listed in FR-001 are
  configurable.
- **No audit history of threshold changes** in this feature; the export states the values in
  use at export time.
- **No per-exercise thresholds**; a threshold applies to all of a patient's exercises.
- **Anyone using the installation may change installation defaults**; there are no user
  accounts in the product.
