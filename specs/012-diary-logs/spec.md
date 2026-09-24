# Feature Specification: Exercise Diary, Medication and Sleep Logs

**Feature Branch**: `012-diary-logs`

**Created**: 2026-09-24

**Status**: Approved by the owner's plan approval on 2026-09-23

**Input**: Owner's plan: patients log exercise they did without the camera (counted in adherence,
always labelled self-reported, with the PT able to turn it off per patient), plus a simple
medication and sleep log the PT can see.

## Constitution Check (Principle III, v1.2.0)

| Requirement | This feature |
|-------------|--------------|
| What crosses the network | Numbers and fixed choices the patient enters: which exercise, reps and sets, how hard it felt, medication taken from a list the PT set, sleep hours and quality; and an optional short note. |
| What never does | Anything of another patient; no free-text medication names typed by the patient (the list comes from the PT); no video or audio. |
| Who may use it | Demo and consented study participants only. |
| Only the patient's own data | Identity from the sign-in alone. |
| Deletion | Diary sessions and log entries go with the patient. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Log Exercise Done Without the Camera (Priority: P1)

The patient did their exercises in the park, at the gym, or without their phone propped up. From
Today they tap "I did this without the camera", pick the exercise, say how many reps and sets and
how hard it felt (1 to 5), and it counts towards their week and streak. Everywhere it appears it
says self-reported.

**Independent Test**: A patient with no camera sessions logs three diary sessions in a week; their
week count, streak, and the PT's adherence all rise; range-of-motion and form trends are untouched
and no attention flag is raised by them.

**Acceptance Scenarios**:

1. **Given** today's program, **When** the patient logs Knee Extension with 10 reps, 2 sets, effort 3,
   **Then** the exercise shows as done today, this week's count rises, and the entry says self-reported.
2. **Given** the PT's roster and adherence view, **Then** the diary session counts as practice and is
   labelled self-reported; the patient's practice gap is reset by it.
3. **Given** trends, flags, goal progress, and session comparison, **Then** diary sessions never appear
   in them, because they carry no measured range of motion or form.
4. **Given** the PT turns the diary off for a patient, **Then** the option disappears from Today and
   logging is refused; entries already made stay.
5. **Given** the patient logs the same exercise twice in a day, **Then** both are kept; the exercise
   shows as done once.
6. **Given** a diary session recorded yesterday from a phone that was offline, **Then** it is stored
   with yesterday's date (within the seven-day window) and counted in that week.

### User Story 2 - Medication and Sleep (Priority: P2)

The PT writes the medication list for a patient (for example "ibuprofen 400 mg" and "paracetamol").
The patient ticks what they took and when, and logs last night's sleep (hours and quality 1 to 5).
The PT sees both beside pain and sessions.

**Acceptance Scenarios**:

1. **Given** a medication list set by the PT, **Then** the patient sees exactly those choices and no
   free-text field for a medicine name.
2. **Given** no list set, **Then** the medication log is not offered.
3. **Given** a sleep entry of 7 hours and quality 4, **Then** it is stored once for that night and can
   be corrected the same day by logging again (the later entry wins for that date).
4. **Given** the PT's "From the patient" tab, **Then** medication and sleep appear as tables with
   their units and meanings, next to pain.

### Edge Cases

- An exercise that is no longer in the configuration is not offered for logging.
- A diary session for a patient with no program: allowed, listed under "other exercise".
- Effort and quality are fixed 1 to 5 scales with words at each end so they mean the same to everyone.
- A discharged patient cannot log anything.
- The diary must never make a session look measured: a diary session has no reps with angles, so
  average range of motion and form stay empty.

## Requirements *(mandatory)*

- **FR-001**: A patient MUST be able to log exercise done without the camera: exercise (from their
  program, or any configured exercise), reps (1-200), sets (1-20), effort (1-5), optional note (200
  characters, privacy-checked), and the date and time it was done (within the last 7 days, not future).
- **FR-002**: A diary entry MUST be stored as a session with source `diary` so that every count that
  means "did they practise" includes it: done-today, sessions this week, the streak, adherence, the
  practice gap, sessions in the roster, and the patient's history.
- **FR-003**: Diary sessions MUST NOT enter any comparison of measurements: trends, first-to-latest
  change, goal progress, session comparison, and every attention rule that compares sessions. They form
  a third capture origin, `self-reported`, beside clinic and home.
- **FR-004**: Every place that lists or counts a diary session MUST label it self-reported.
- **FR-005**: The therapist MUST be able to turn the diary off and on per patient; off hides it from
  the patient and refuses new entries, keeping what exists.
- **FR-006**: The therapist MUST be able to set a per-patient medication list (each item a short name
  the therapist types, privacy-checked); the patient MUST only choose from it, never type a name.
- **FR-007**: A patient MUST be able to log medication taken (which item, when) and sleep (hours 0-14
  in halves, quality 1-5, for a given night); a later entry for the same night replaces the earlier one
  in the PT's view.
- **FR-008**: Every field MUST carry a unit and a plain-language meaning, shown to both sides.
- **FR-009**: The PT's "From the patient" tab MUST show diary sessions, medication, and sleep beside
  pain check-ins.
- **FR-010**: Deleting a patient MUST remove their diary sessions and log entries; the no-leak test
  MUST cover the new routes.
- **FR-011**: With no diary or log entries, every existing result MUST be unchanged.
- **FR-012**: The migration that allows the new session source MUST NOT lose a single row of the
  record; a test MUST upgrade a realistic previous-version record and compare every table's count.

### Key Entities

- **Diary session**: a session with source `diary`, one set per exercise carrying reported reps, sets,
  and effort instead of measured reps.
- **Entry kinds** `medication` and `sleep`, alongside `checkin` from feature 010.
- **Medication list**: a per-patient list of short names set by the therapist.

## Success Criteria

- **SC-001**: A diary entry takes under 30 seconds on a phone.
- **SC-002**: 100% of diary sessions are labelled self-reported wherever they appear.
- **SC-003**: 0 trends, flags, or comparisons include a diary session.
- **SC-004**: The previous-version record upgrades with every row intact.
- **SC-005**: With no diary entries, flags, trends, roster, queue, and exports equal feature 011's.

## Assumptions

- Effort: 1 very easy, 5 very hard. Sleep quality: 1 poor, 5 very good.
- A diary session's duration is not asked for; it is left empty.
- No reminders in this feature.
