# Specification Quality Checklist

**Created**: 2026-09-24

- [x] Focused on user value; requirements testable; success criteria measurable
- [x] Edge cases, assumptions identified
- [x] Constitution Principle III check present (v1.2.0)
- [x] No [NEEDS CLARIFICATION] markers (owner-approved plan of 2026-09-23)

## Implementation notes (filled in as the feature was built)

- **T004/T005 deviation**: the origin, adherence, and review changes were written together with their
  tests in one step for `measures.py` and `review.py`; `adherence.py` and `origin.py` were watched
  failing first. Recorded here rather than claimed otherwise.
- **No access-history event for a logged session.** The `portal_audit` CHECK constraint would have
  needed a third table rebuild for a `diary_logged` event, and the session row already records who
  logged what, when, and with which origin. The spec does not require one.
- **The note lives on the session**, in `source_extras`, not in a new column: it belongs to the
  session rather than the set, and it needed no further migration.
- **Three names could not be used.** The no-leak guard forbids the word `label` anywhere in a patient
  response (a patient's label is private), so the diary's own marker is `marked_as`. A fixture
  patient's label "Shoulder" was a substring of the configured exercise "Shoulder Flexion", which made
  the guard fail on an innocent response; the fixture now uses a label that cannot collide.
- **Found by the browser run, not the suite**: the per-patient controls on the Patients page shared one
  widget key, so switching patients showed and would have saved the previous patient's medication
  list; and an entry queued while offline did not raise the offline banner. Both are now covered by a
  test (`test_the_medication_list_does_not_follow_the_therapist_to_the_next_patient`).
- **Deliberately not done**: no reminders, no free-text medicine names, no diary entry for a
  discharged patient, and no way for a patient to edit or delete a logged session (they can tell their
  therapist; the record is append-only).
