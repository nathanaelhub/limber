# Feature Specification: Review Over Time

**Feature Branch**: `002-review-over-time`

**Created**: 2026-09-16

**Status**: Draft

**Input**: User description: "Review over time: a physical therapist (PT) or PT student reviews a
patient's recorded sessions as a course of care instead of one session at a time. Everything
reads from the canonical session record built in feature 001; nothing here records new engine
data. For a selected patient and exercise, the PT sees trends across sessions for range of
motion, form score, reps completed versus target, rep tempo (average rep duration and its
consistency), and partial-rep rate, over a chosen period (last 2 weeks, last month, last 3
months, all time), each data point linked to the session it came from. The PT can compare any
two sessions of the same exercise side by side and see what changed in each of those measures.
The system flags patterns that need attention using explicit, documented rules that show their
evidence: form score declining across the most recent sessions, range of motion plateauing or
regressing, repeated failure to reach the target rep count, a rising share of partial reps, any
safety-stop form event, and a gap in practice longer than a set number of days. The PT can set a
goal per patient per exercise (target range of motion in degrees and target reps) and the trend
view shows progress toward it. The PT records a review on a session: marks it reviewed, adds
clinical notes in free text (no names, dates of birth, or record numbers), and chooses a next
step (continue, progress, regress, hold); the PT can see which sessions for a patient are still
pending review and when each reviewed session was reviewed. The single-session PT summary that
exists today (flags such as long pauses, form decline within a session, ROM anomalies, rest
periods) becomes the per-session part of this review. A review summary for a patient over a
period, covering trends, flags, goals, and the PT's review notes and next steps, can be exported
as a text report and as CSV for the patient's chart. Existing CLI and web app pages for progress
and PT summary are replaced by this feature's views. Data stays local and patients remain
pseudonymous."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See a Patient's Trends Across Sessions (Priority: P1)

A PT selects a patient, an exercise, and a period, and sees how that exercise has progressed
across sessions: range of motion, form score, reps completed against target, rep tempo
(average rep duration and its consistency), and the share of partial reps. Each point on a
trend is one session and links to that session's full record. If a goal is set for the
exercise, the trend shows the goal and how close the patient is to it.

**Why this priority**: This is the core of reviewing a course of care. Everything else
(flags, comparisons, reviews, exports) is built on the same per-session measures.

**Independent Test**: Record or import at least three sessions of one exercise for a patient
on different days, open the trend view for that exercise, and confirm each session appears
once, in date order, with the five measures matching that session's own summary, and that
the period filter hides sessions outside the period.

**Acceptance Scenarios**:

1. **Given** a patient with four sessions of "Knee Extension" on different days, **When** the
   PT opens the trend view for that exercise with the period "all time", **Then** four points
   are shown in date order, each with average range of motion in degrees, average form score
   out of 100, reps completed and target reps, average rep duration in seconds with its
   consistency, and partial-rep share as a percentage, and each point names its session.
2. **Given** the same patient, **When** the PT chooses the period "last 2 weeks", **Then**
   only sessions that started within the last 14 days are shown.
3. **Given** a session contains two exercise sets of the same exercise (after a reset or a
   switch back), **When** the trend is shown, **Then** that session contributes one point whose
   measures combine all its sets of that exercise.
4. **Given** an exercise with only one session in the period, **When** the trend view opens,
   **Then** the single point is shown with its values and the view states that a trend needs
   at least two sessions.
5. **Given** a goal of 120 degrees range of motion and 10 reps is set, **When** the trend
   view opens, **Then** the goal is shown alongside the measured values and the progress toward
   the range-of-motion goal is stated as a percentage of the target (capped at 100%).
6. **Given** an interrupted session in the period, **When** the trend is shown, **Then** the
   session appears with its computed values and is marked as interrupted.

---

### User Story 2 - Review a Session and Track What Is Pending (Priority: P2)

A PT opens a session, reads its per-session summary (the flags the existing single-session
summary produces: long pauses, exercise switches, form decline within the session, range of
motion anomalies, rest periods, consistent form), marks the session reviewed, adds clinical
notes, and chooses a next step: continue, progress, regress, or hold. The PT can list which
of a patient's sessions are still pending review and see when each reviewed session was
reviewed. A review can be edited later; the latest review is what counts.

**Why this priority**: The review is the clinical act this feature exists to support, and
the pending list is what makes reviewing a course of care manageable.

**Independent Test**: Record two sessions, confirm both are pending, review one with notes and
a next step, confirm the pending list now holds only the other, reopen the reviewed session and
confirm the notes, next step, and review time are shown.

**Acceptance Scenarios**:

1. **Given** a patient has two unreviewed sessions, **When** the PT lists pending reviews for
   the patient, **Then** both sessions are listed newest first with date, exercises, and total
   reps.
2. **Given** the PT opens a session, **When** the session detail is shown, **Then** it includes
   the per-session summary flags computed from the session's events, each with its evidence
   (for example the pause length and where it occurred).
3. **Given** the PT marks a session reviewed with notes "Post-op week 3, tolerated full set"
   and next step "progress", **When** the session is reopened, **Then** it shows status
   reviewed, the notes, the next step, and the time of review, and it no longer appears in the
   pending list.
4. **Given** the PT enters notes containing what looks like a full name, a date, or a run of
   six or more digits, **When** they save, **Then** the review is rejected with the rule that
   was violated and nothing is stored.
5. **Given** a reviewed session, **When** the PT edits the notes or next step, **Then** the
   review is updated, the review time is updated, and only one review exists for the session.
6. **Given** a patient is deleted, **When** the deletion completes, **Then** every review and
   goal tied to that patient is gone as well.

---

### User Story 3 - Flags That Need Attention, With Evidence (Priority: P3)

For a patient and period, the PT sees a list of attention flags, each computed by a stated
rule and each showing the sessions and values that triggered it: form score declining, range
of motion plateauing or regressing, repeated failure to reach the target rep count, rising
share of partial reps, any safety-stop form event, and a gap in practice longer than the
patient's configured gap threshold (default 7 days).

**Why this priority**: Flags turn the trends into a short list a PT can act on, but they are
only trustworthy if every flag shows why it fired, so they come after the trends they depend
on.

**Independent Test**: Construct a patient history that should trigger each rule exactly once
(and one that should trigger none), open the flags view, and confirm the expected flags appear
with the sessions and numbers named in the rule, and that no flag appears for the clean
history.

**Acceptance Scenarios**:

1. **Given** four sessions of an exercise whose average form scores are 90, 86, 81, 75 in date
   order, **When** flags are computed, **Then** a "form declining" flag is shown naming those
   four sessions and scores.
2. **Given** four sessions whose average range of motion is 80, 81, 79, 80 degrees and a goal
   of 110 degrees, **When** flags are computed, **Then** a "range of motion plateau" flag is
   shown with the four values and the goal; **and given** the latest session is 70 degrees
   after three sessions above 82, **Then** a "range of motion regression" flag is shown instead.
3. **Given** the last three sessions of an exercise each completed fewer reps than target,
   **When** flags are computed, **Then** a "target reps not reached" flag is shown with the
   three counts and the target.
4. **Given** the most recent session has a partial-rep share of 30% and the previous three
   averaged 10%, **When** flags are computed, **Then** a "rising partial reps" flag is shown
   with both figures.
5. **Given** any session in the period contains a form event with severity "stop", **When**
   flags are computed, **Then** a "safety stop" flag is shown naming the session, the message,
   and when it occurred.
6. **Given** the patient's gap threshold is 7 days and their last session was 9 days ago,
   **When** flags are computed, **Then** a "practice gap" flag is shown with the number of days.
7. **Given** a history where none of the rules apply, **When** flags are computed, **Then** the
   view states that nothing needs attention.

---

### User Story 4 - Compare Two Sessions Side by Side (Priority: P4)

A PT picks two sessions of the same exercise (typically an earlier and a later one) and sees
each measure for both sessions and the change between them, in the measure's unit and as a
percentage where meaningful.

**Why this priority**: Comparison is a focused form of the trend view that clinicians use in
discharge and progress notes; it reuses the same measures.

**Independent Test**: Record two sessions of one exercise with known values, compare them, and
confirm each row shows both values and the correct difference.

**Acceptance Scenarios**:

1. **Given** session A (avg ROM 80°, avg form 85, 8/10 reps, 2.4 s per rep, 0% partial) and
   session B (avg ROM 92°, avg form 88, 10/10 reps, 2.1 s per rep, 10% partial), **When** the
   PT compares A to B, **Then** the view shows both values per measure and the changes
   (+12.0°, +3.0 points, +2 reps, −0.3 s, +10 points), with the direction that is an
   improvement made clear for each measure.
2. **Given** two sessions of different exercises, **When** the PT tries to compare them,
   **Then** the system refuses and explains that comparisons are within one exercise.
3. **Given** a session with zero completed reps of the exercise, **When** it is compared,
   **Then** its measures that need reps are shown as "not available" rather than zero.

---

### User Story 5 - Goals per Patient and Exercise (Priority: P5)

A PT sets, updates, or clears a goal for a patient and exercise: a target range of motion in
degrees and/or a target rep count. Goals appear in the trend view and in the plateau rule.

**Why this priority**: Goals sharpen trends and flags, but the feature works without them.

**Independent Test**: Set a goal, confirm it appears on the trend view and in the exported
summary, update it, confirm the new value is used, clear it, confirm it is gone.

**Acceptance Scenarios**:

1. **Given** no goal exists, **When** the PT sets a goal of 120 degrees and 12 reps for
   "Knee Extension", **Then** the goal is stored with the time it was set and shown in that
   exercise's trend view.
2. **Given** a goal exists, **When** the PT updates only the rep target, **Then** the range of
   motion target is unchanged and the goal shows the new rep target.
3. **Given** the PT enters a range of motion target outside 1 to 180 degrees or a rep target
   below 1, **When** they save, **Then** the goal is rejected with the reason.
4. **Given** a goal exists, **When** the PT clears it, **Then** the trend view no longer shows
   a goal and the plateau rule no longer uses it.

---

### User Story 6 - Export a Review Summary (Priority: P6)

A PT exports a review summary for a patient over a period as a text report and as CSV. The
report covers the trend table per exercise, the flags with their evidence, goals and progress,
and every session's review status, notes, and next step. The CSV holds one row per session per
exercise with the measures and review fields.

**Why this priority**: The export is what goes into the patient's chart; it depends on
everything above.

**Independent Test**: Build a patient with sessions, a goal, a flag, and one reviewed session,
export both formats, and confirm the report contains each section with the right values and the
CSV has one row per session-exercise with matching numbers.

**Acceptance Scenarios**:

1. **Given** a patient with two exercises over three sessions, one goal, one flag, and one
   reviewed session, **When** the PT exports the text report for "all time", **Then** the
   report has a header (pseudonymous ID, period, generated time), a trend table per exercise,
   the flag with evidence, the goal with progress, and a session-by-session list with review
   status, notes, and next step.
2. **Given** the same patient, **When** the PT exports the CSV, **Then** it has one row per
   session per exercise with columns for date, session, exercise, reps, target, average form
   score, average range of motion, average rep duration, tempo consistency, partial-rep share,
   review status, next step, and reviewed time, with units named in the header row.
3. **Given** an export is written, **When** the patient is later deleted, **Then** the export
   file is removed with the patient's other data.
4. **Given** the same inputs, **When** the export is produced twice, **Then** the two files
   differ only in the generated time.

---

### Edge Cases

- A patient has sessions but none of the selected exercise: the trend view says so and offers
  the exercises that do have sessions.
- All sessions in the period have zero counted reps: measures show "not available"; no
  form, range of motion, or tempo flags fire; the target-reps rule still applies.
- Sessions on the same day: each is its own point, ordered by start time.
- An exercise recorded under two names that differ only by side (for example "Knee Extension"
  and "Knee Extension (Right)"): they are separate exercises in trends, goals, and flags.
- The gap rule when the patient has only one session: the gap is measured from that session to
  now.
- A review saved for a session that is later reassigned to another patient moves with the
  session.
- Reviewing an interrupted session is allowed and the review shows the interrupted status.
- Fewer sessions than a rule needs (for example two sessions for the form decline rule): the
  rule does not fire and the flags view lists which rules could not be evaluated yet.
- A period with no sessions: the views say there is nothing to review in that period and show
  the date of the most recent session outside it.

## Requirements *(mandatory)*

### Functional Requirements

**Per-session measures (shared by trends, comparison, flags, exports)**

- **FR-001**: For every session and exercise name, the system MUST compute: reps completed
  (counted reps not flagged out of range), target reps (from the set), average range of motion
  in degrees, average form score out of 100, average rep duration in seconds, tempo consistency
  (the standard deviation of rep durations in seconds), and partial-rep share (partial reps
  divided by partial plus completed reps, as a percentage). Measures that require at least one
  completed rep MUST be reported as "not available" when there are none.
- **FR-002**: When a session holds several sets of the same exercise, the measures MUST combine
  all of them, and target reps MUST be the target of the last set.
- **FR-003**: Every measure MUST carry its unit and a plain-language definition wherever it is
  shown or exported, using the existing metric definitions.

**Trends**

- **FR-004**: Users MUST be able to view, for one patient and one exercise, the per-session
  measures ordered by session start time for a period of the last 14 days, last 30 days, last
  90 days, or all time, with each point identifying its session.
- **FR-005**: The trend view MUST show, for each measure, the first value, the latest value, and
  the change between them when at least two sessions are in the period, and MUST state that a
  trend needs two sessions otherwise.
- **FR-006**: When a goal exists for the exercise, the trend view MUST show the goal values and
  the progress toward the range of motion target as latest average range of motion divided by
  target, as a percentage capped at 100.
- **FR-007**: Interrupted sessions MUST be included and marked as interrupted.

**Reviews**

- **FR-008**: Users MUST be able to record one review per session with: reviewed time, free-text
  notes, and a next step that is one of continue, progress, regress, hold.
- **FR-009**: Notes MUST be rejected when they contain two or more consecutive capitalized
  words, a date in a common numeric layout, or a run of six or more digits, with the violated
  rule named.
- **FR-010**: Editing a review MUST replace the previous notes and next step and update the
  reviewed time; a session MUST never have more than one review.
- **FR-011**: Users MUST be able to list a patient's sessions that have no review, newest
  first, and see for reviewed sessions when they were reviewed and their next step.
- **FR-012**: The session detail MUST include the per-session summary produced by the existing
  single-session analysis (long pauses, exercise switches, form decline within the session,
  range of motion anomalies, rest periods, consistent form), each item with its evidence.
- **FR-013**: Reviews and goals MUST be removed when their patient is deleted and MUST follow a
  session when it is reassigned.

**Flags**

- **FR-014**: For a patient and period, the system MUST evaluate these rules per exercise and
  report each flag with the sessions and values that triggered it:
  - *Form declining*: over the four most recent sessions of the exercise, each session's
    average form score is lower than the previous one, or the most recent is at least 10 points
    below the highest of the other three.
  - *Range of motion regression*: the most recent session's average range of motion is at least
    10 degrees below the highest of the previous three sessions.
  - *Range of motion plateau*: a goal range of motion is set, the latest average range of motion
    is below it, and across the four most recent sessions the average range of motion changed by
    less than 3 degrees between the earliest and the latest of them (not evaluated when
    regression fires).
  - *Target reps not reached*: in each of the three most recent sessions, reps completed were
    below the target.
  - *Rising partial reps*: the most recent session's partial-rep share is at least 25% and at
    least 10 points above the average share of the previous three sessions.
  - *Safety stop*: any form event with severity "stop" in any session in the period (reported
    per session with the message and time).
  - *Practice gap*: more days than the patient's gap threshold between consecutive sessions in
    the period, or between the most recent session and today.
- **FR-015**: A rule that needs more sessions than are available MUST NOT fire and MUST be
  listed as "not enough sessions yet" with the number needed.
- **FR-016**: Users MUST be able to set a patient's gap threshold in days (1 to 90, default 7).

**Comparison**

- **FR-017**: Users MUST be able to compare two sessions of the same exercise and see, per
  measure, both values and the change in the measure's unit, plus the percentage change for
  range of motion, form score, and reps; comparisons across different exercises MUST be
  refused with an explanation.
- **FR-018**: The comparison MUST state, per measure, which direction counts as improvement
  (higher for range of motion, form score, and reps; lower for partial-rep share and tempo
  inconsistency; rep duration is informational).

**Goals**

- **FR-019**: Users MUST be able to set, update, and clear one goal per patient and exercise
  with an optional target range of motion (1 to 180 degrees) and an optional target rep count
  (at least 1), recording when it was last set.

**Exports**

- **FR-020**: Users MUST be able to export a review summary for a patient and period as a text
  report containing: header (pseudonymous ID, period, generated time), a trend table per
  exercise, the flags with evidence, goals with progress, and a session list with review
  status, notes, and next step.
- **FR-021**: Users MUST be able to export the same scope as CSV with one row per session per
  exercise and the columns: date, session, exercise, reps completed, target reps, average form
  score (0-100), average range of motion (degrees), average rep duration (seconds), tempo
  consistency (seconds), partial-rep share (%), interrupted, review status, next step,
  reviewed time.
- **FR-022**: Export files MUST be named with the pseudonymous ID, the period, and the
  generation time only, MUST be written to the same export location as session exports, and
  MUST be removed when the patient is deleted.

**Replacement and scope**

- **FR-023**: The command-line progress command and the web app's Progress Report and PT
  Summary pages MUST be replaced by this feature's trend, flags, comparison, review, and export
  views; the single-session summary remains available inside the session review.
- **FR-024**: This feature MUST read only from the canonical session record and MUST NOT
  change how sessions are recorded.
- **FR-025**: All review data MUST be stored locally with the session record and MUST identify
  patients only by their pseudonymous ID.

### Key Entities

- **Session Measure**: the per-session, per-exercise figures defined in FR-001, derived from
  the recorded reps, partial reps, and sets; not stored separately.
- **Review**: one per session; reviewed time, notes, next step (continue | progress | regress |
  hold); belongs to the session and therefore to its patient.
- **Goal**: one per patient and exercise; optional target range of motion, optional target
  reps, time last set.
- **Review Settings**: per patient; gap threshold in days (default 7).
- **Attention Flag**: computed, not stored; rule name, exercise (if applicable), the sessions
  and values that triggered it, and a one-sentence explanation.
- **Review Export**: a text report or CSV file for a patient and period, tracked so patient
  deletion removes it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any session, the per-session measures shown in trends, comparisons, and
  exports equal the values recomputed by hand from that session's recorded reps and partial
  reps, for 100% of sessions.
- **SC-002**: Every attention flag shown names the sessions and values that triggered it; a
  history constructed to trigger each rule once produces exactly those flags and a clean history
  produces none.
- **SC-003**: A PT can open a patient, read the flags, review one session with notes and a
  next step, and export the summary in under three minutes on first use.
- **SC-004**: Trend, flag, comparison, and pending-review views for a patient with 200 sessions
  render in under two seconds each.
- **SC-005**: Zero reviews or goals remain after their patient is deleted, and a review follows
  its session when the session is reassigned.
- **SC-006**: Exported reports and CSVs contain no patient identifier other than the
  pseudonymous ID, and no notes that violate the notes rules can be stored.
- **SC-007**: After this feature ships, the replaced progress and summary views no longer
  exist, and every measure they showed is available in the new views.

## Assumptions

- **One reviewer per installation.** Reviews record when, not who; the tool runs locally for
  one PT or student, so a reviewer identity is not stored.
- **Flag thresholds are fixed defaults** in this version (the numbers in FR-014); only the
  practice-gap threshold is adjustable per patient. Making the others adjustable is a later
  feature.
- **Exercises are keyed by their recorded name**, so left and right variants are separate
  exercises for trends, goals, and flags.
- **Notes rules mirror the patient label rules.** Clinicians write relative references such as
  "post-op week 3" rather than dates, so the date pattern is rejected outright rather than
  warned about.
- **No review history.** Editing a review overwrites it; an audit trail of edits is out of
  scope.
- **The per-session summary logic that exists today is reused as is**; its flag definitions
  are not changed by this feature.
- **Session exports from feature 001 are unchanged**; this feature adds the review summary
  formats alongside them.
- **The multi-patient tracker** (roster, program assignment, adherence, review queue across
  patients) is the next feature; this one is scoped to one patient at a time.
