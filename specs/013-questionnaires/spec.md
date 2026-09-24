# Feature Specification: Assigned Questionnaires

**Feature Branch**: `013-questionnaires`

**Created**: 2026-09-24

**Status**: Approved by the owner's plan approval on 2026-09-23

**Input**: Owner's plan: the therapist assigns an instrument to a patient with a repeat interval; it
shows as due on Today; the patient answers it in Limber; an engine scores it from a definition file
(sum, mean, reversed items, subscales, a missing-item rule); the therapist sees the score over time
beside pain and sessions, with definitions and units, and can export it. Ship the engine plus one demo
instrument that is not a licensed one; definitions live in YAML beside `config.yaml`, one file per
instrument, so a new instrument needs no code; answers are stored as entries of kind `questionnaire`,
one per completed questionnaire, items in the payload and the total in the score; the offline queue
must work for them.

## Constitution Check (Principle III, v1.2.0)

| Requirement | This feature |
|-------------|--------------|
| What crosses the network | The patient's answers to the items of a questionnaire their therapist assigned: a fixed choice per item, and an optional note where the instrument allows one. |
| What never does | Anything of another patient; no free text beyond the instrument's own note item, which goes through the privacy check; no identifying question is allowed in an instrument (a check refuses one). |
| Who may use it | Demo and consented study participants only. |
| Only the patient's own data | The due list and every answer come from the sign-in alone. |
| Retention and deletion | Answers go with the patient; a patient may not delete an answered questionnaire (they can tell their therapist), and the therapist may remove a note. |
| Processed only on the host | Scoring is arithmetic on the host from a local definition file; no third-party service, no model. |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Patient Answers What Is Due (Priority: P1)

The patient opens Limber and sees "Knee questionnaire · due today" on Today. They tap it, answer the
items on one scrolling page (each item a fixed set of choices with words, not bare numbers), and send.
They see their total and what it means in one plain sentence. If they close the app half way, their
answers are still there when they come back; if they are offline, the finished questionnaire is queued
and sent when the connection returns.

**Why this priority**: Without this there is nothing to score and nothing for the therapist to see.

**Independent Test**: A patient with one assigned instrument answers it on a phone; the record holds
one entry of kind `questionnaire` with every item answer and the total; Today then shows it as done
and gives the next due date.

**Acceptance Scenarios**:

1. **Given** an instrument assigned every 14 days and never answered, **Then** Today shows it as due
   and the patient can open it.
2. **Given** all items answered, **When** the patient sends it, **Then** one entry is stored with the
   items in the payload and the total as the score, and the page shows the total with its meaning.
3. **Given** an item left blank, **Then** the page says which item is missing and nothing is sent,
   unless the instrument's rule allows missing items, in which case sending is allowed and the score
   states how many were missing.
4. **Given** the patient answered it today, **Then** Today shows it as done with the next due date and
   does not offer it again.
5. **Given** the phone is offline, **When** the patient sends a finished questionnaire, **Then** it is
   saved on the phone and sent once when the connection returns, keeping the time it was answered.
6. **Given** the patient leaves the page half way and comes back, **Then** the answers they had made
   are still shown (kept on the phone only, and cleared once it is sent).

---

### User Story 2 - The Therapist Assigns and Reads the Score (Priority: P1)

The therapist picks an instrument for a patient and how often it should repeat (once, weekly,
fortnightly, monthly). They see each completed questionnaire, the score over time with the
instrument's own units and direction ("higher is better" or "higher is worse"), the subscale scores
where the instrument has them, the item answers of any one questionnaire, and an overdue marker when a
patient has not answered by the due date.

**Why this priority**: The assignment is what makes a questionnaire appear, and the score over time is
the clinical point of the feature.

**Independent Test**: A therapist assigns an instrument fortnightly, the patient answers twice, and
the therapist sees two scores with the change between them, the units, and the meaning.

**Acceptance Scenarios**:

1. **Given** the Patients page, **When** the therapist assigns "Demo Knee Function" fortnightly,
   **Then** the patient's Today offers it and the therapist sees the assignment with its next due date.
2. **Given** two completed questionnaires, **Then** the therapist sees both scores in order with the
   change, the unit, the direction, and the plain-language meaning of the score.
3. **Given** an instrument with subscales, **Then each** subscale score is shown beside the total with
   its own name and range.
4. **Given** a questionnaire is overdue by more than a week, **Then** the patient appears in the work
   queue as having an overdue questionnaire, and the roster marks them.
5. **Given** the therapist ends the assignment, **Then** Today stops offering it and the answers stay.
6. **Given** the export, **Then** each completed questionnaire is one row with the total, the subscale
   scores, how many items were missing, and the date, and the item answers are in the review report.

---

### User Story 3 - A New Instrument Needs No Code (Priority: P2)

The owner adds an instrument by writing one YAML file beside `config.yaml`: its name, what its score
means, its items with their choices and values, which items are reversed, its subscales, its scoring
method, and its missing-item rule. It appears in the therapist's list at once. A file with a mistake
in it is refused with a plain message naming the file and the problem, and does not stop the rest of
the app.

**Why this priority**: It is what makes the engine worth having, but the feature works with the one
demo instrument shipped in the repository.

**Acceptance Scenarios**:

1. **Given** a valid new definition file, **Then** the instrument can be assigned without restarting
   anything and its items appear as written.
2. **Given** a definition with an unknown scoring method, a duplicate item key, a choice value outside
   the item's range, or a subscale naming an item that does not exist, **Then** it is refused with a
   message naming the file and the problem, and the other instruments still load.
3. **Given** a definition whose item text asks for a name, a date of birth, or a record number,
   **Then** it is refused: instruments must not collect identifying details.
4. **Given** a definition file is changed after a patient has answered it, **Then** stored answers keep
   the version they were answered under and are never rescored silently.

---

### Edge Cases

- An instrument assigned to a patient who is then discharged: it stops being offered; answers stay.
- Two assignments of the same instrument to one patient: the second replaces the first (one live
  assignment per instrument per patient).
- An instrument removed from the configuration after it was answered: the therapist still sees the
  stored scores and item answers, marked "definition no longer installed", and it cannot be assigned.
- A questionnaire answered twice in one day: both are kept; the later one is the latest score.
- An item with no answer where the rule allows missing items: the score says how many were missing, and
  a score computed from fewer than the rule's minimum answered items is refused.
- A definition with a single item is allowed; a definition with no items is refused.
- The patient's device clock is wrong: the answered time is handled like every other entry (the
  seven-day window from feature 010).

## Requirements *(mandatory)*

- **FR-001**: Instrument definitions MUST be read from YAML files beside `config.yaml`, one file per
  instrument, each carrying: a key, a display name, a one-sentence plain-language meaning of the score,
  the unit, the direction (higher is better or worse), the items (key, text, choices with their values),
  which items are reversed, optional subscales (name, items, range), the scoring method (`sum` or
  `mean`), the missing-item rule (how many answered items are needed, and whether the mean of the
  answered items replaces a missing one), and a version.
- **FR-002**: A definition that is invalid MUST be refused with a message naming the file and the
  problem, without preventing the other definitions from loading; the app MUST still run with no
  instruments installed.
- **FR-003**: A definition whose item text or name looks like it collects identifying details MUST be
  refused (the same check used for patient text).
- **FR-004**: The therapist MUST be able to assign one instrument to a patient with a repeat interval
  of once, weekly, fortnightly, or monthly, to see its next due date, and to end the assignment;
  ending it MUST keep the answers.
- **FR-005**: The patient MUST see what is due on Today and be able to answer it: every item with its
  choices in the instrument's own words, in the order the definition gives.
- **FR-006**: A completed questionnaire MUST be stored as one entry of kind `questionnaire` carrying
  every item answer, the instrument key and version, the total, the subscale scores, and how many items
  were missing; the total MUST be the entry's score so that it can be shown over time.
- **FR-007**: Scoring MUST be arithmetic defined by the definition alone: `sum` or `mean` of the item
  values, with reversed items reversed within their own range, subscales scored the same way over their
  own items, and the missing-item rule applied; a questionnaire with too few answered items MUST be
  refused rather than scored.
- **FR-008**: Answers MUST be scored with the version of the definition they were answered under, and
  a stored score MUST never change because a definition changed.
- **FR-009**: The patient's answers MUST be sendable offline: kept on the phone and sent once when the
  connection returns, keeping the time they were answered; a half-finished questionnaire MUST be kept
  on the phone only and cleared once it is sent.
- **FR-010**: The therapist MUST see, per patient: each completed questionnaire with its date, total,
  subscale scores, missing count, the unit, the direction, and the plain-language meaning; the item
  answers of a chosen questionnaire; and the change from the first to the latest.
- **FR-011**: A questionnaire overdue by more than seven days MUST appear in the work queue and mark
  the patient on the roster.
- **FR-012**: The review export MUST include each completed questionnaire as one row (date, instrument,
  total, subscale scores, missing count) and the item answers in the review report.
- **FR-013**: Every number shown MUST carry its unit and a plain-language meaning (constitution V).
- **FR-014**: Deleting a patient MUST remove their assignments and answers; the no-leak test MUST cover
  the new routes, including another patient's assignment or answer.
- **FR-015**: With no instruments installed and no assignments, every existing result MUST be unchanged.

### Key Entities

- **Instrument**: a definition read from a YAML file: key, name, meaning, unit, direction, items,
  reversed items, subscales, scoring method, missing-item rule, version.
- **Assignment**: which instrument a patient should answer, how often, from when, and whether it has
  ended; one live assignment per instrument per patient.
- **Completed questionnaire**: an entry of kind `questionnaire` with the item answers, instrument key
  and version, total, subscale scores, and missing count.

## Success Criteria

- **SC-001**: A patient answers a ten-item questionnaire on a phone in under two minutes.
- **SC-002**: 100% of stored questionnaires can be rescored to the same total from their stored answers
  and the version they were answered under.
- **SC-003**: Adding an instrument takes one file and no code change; an invalid file never prevents the
  app from starting.
- **SC-004**: 0 responses contain another patient's assignment, answer, or score.
- **SC-005**: With no instruments installed, flags, trends, roster, queue, and exports equal feature
  012's.

## Assumptions

- The demo instrument is written for this project ("Demo Knee Function", ten items, 0-4 each, higher is
  better, one subscale for pain and one for activity) and is explicitly not a licensed instrument; the
  owner sources real instruments and their licences later, which is why no real instrument's items are
  reproduced here.
- Repeat intervals are whole weeks or months from the assignment date; no time of day, no reminders
  (reminders are not in this feature).
- A questionnaire is answered in one sitting; a half-finished one is kept on the phone, not on the host.
- The therapist may remove a note from an answer, as with a check-in; they may not change an answer.
- Scoring is not clinical interpretation: the plain-language meaning comes from the definition file, and
  no threshold or flag is derived from a questionnaire score in this feature.
