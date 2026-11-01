"""Feature 017 US1 and US2 — plans of care, conversations per plan, and archived plans kept read-only.

The refusal of writes to an archived plan lives in the data layer (FR-002), so these tests call the store
directly: if a route forgets the check, the store still refuses.
"""

from datetime import date

import pytest

from src.portal import messages, plans
from src.ptlog.models import ExerciseSetInfo, Media, PlanArchived, PlanNotFound, PortalError, PTLogError
from src.ptlog.store import SessionStore

INFO = ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0)
MEDIA_ID = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-018")
        s.conversation_set_enabled("P-017", True)
        yield s


def archived(store, pid="P-017"):
    """The patient's only plan, completed and archived."""
    (plan,) = store.plans(pid)
    plans.complete(store, plan.id)
    return plans.archive(store, plan.id)


class TestPlans:
    def test_a_new_patient_starts_with_one_active_plan(self, store):
        (plan,) = store.plans("P-017")
        assert plan.title == "Plan of care" and plan.status == "active" and not plan.diagnosis_visible
        assert plan.start_date == "2026-03-23" and store.current_plan("P-017").id == plan.id

    def test_open_a_second_plan_with_a_diagnosis(self, store):
        knee = store.plans("P-017")[0]
        shoulder = plans.open_plan(store, "P-017", "Left shoulder", diagnosis="Rotator cuff tendinopathy",
                                   start=date(2026, 3, 20))
        assert [p.title for p in store.plans("P-017")] == ["Plan of care", "Left shoulder"]
        assert shoulder.diagnosis == "Rotator cuff tendinopathy" and shoulder.start_date == "2026-03-20"
        assert store.current_plan("P-017").id == shoulder.id and knee.status == "active"

    def test_titles_and_diagnoses_are_checked(self, store):
        with pytest.raises(PortalError, match="title"):
            plans.open_plan(store, "P-017", "  ")
        with pytest.raises(PortalError, match="80"):
            plans.open_plan(store, "P-017", "x" * 81)
        with pytest.raises(PortalError, match="500"):
            plans.open_plan(store, "P-017", "Knee", diagnosis="x" * 501)

    def test_the_diagnosis_reaches_the_patient_only_when_shown(self, store):
        plan = plans.edit_plan(store, store.plans("P-017")[0].id, diagnosis="ACL reconstruction")
        assert "diagnosis" not in plans.plan_json(plan)
        assert plans.plan_json(plan, therapist=True)["diagnosis"] == "ACL reconstruction"
        plan = plans.edit_plan(store, plan.id, diagnosis_visible=True)
        assert plans.plan_json(plan)["diagnosis"] == "ACL reconstruction"

    def test_status_moves_active_completed_archived(self, store):
        plan = store.plans("P-017")[0]
        with pytest.raises(PTLogError, match="completed before archiving"):
            plans.archive(store, plan.id)
        done = plans.complete(store, plan.id)
        assert done.status == "completed" and done.end_date == "2026-03-23"
        assert plans.reopen(store, plan.id).status == "active" and store.plan_get(plan.id).end_date is None
        plans.complete(store, plan.id)
        gone = plans.archive(store, plan.id)
        assert gone.read_only and gone.archived_at
        with pytest.raises(PlanArchived):
            plans.reopen(store, plan.id)

    def test_another_patients_plan_reads_as_missing(self, store):
        other = store.plans("P-018")[0]
        with pytest.raises(PlanNotFound):
            plans.own_plan(store, "P-017", other.id)
        with pytest.raises(PlanNotFound):
            store.message_add("P-017", "patient", "hi", warned=False, plan_id=other.id)

    def test_caseload_scoping_hides_other_plans(self, store):
        other = store.plans("P-018")[0]
        store.restrict({"P-017"})
        assert store.plans("P-018") == [] and store.plan_get(other.id) is None
        assert store.messages_unread_by_plan("patient", "P-018") == {}

    def test_plans_go_with_the_patient(self, store):
        plans.open_plan(store, "P-018", "Second")
        store.delete_patient("P-018")
        assert store.conn.execute("SELECT COUNT(*) FROM plans_of_care WHERE patient_id = 'P-018'").fetchone()[0] == 0


class TestConversationsPerPlan:
    def test_a_message_stays_in_its_plan(self, store):
        knee = store.plans("P-017")[0]
        shoulder = plans.open_plan(store, "P-017", "Left shoulder")
        messages.send(store, "P-017", "patient", "knee is stiff", plan_id=knee.id)
        messages.send(store, "P-017", "patient", "shoulder clicks", plan_id=shoulder.id)
        messages.send(store, "P-017", "therapist", "try ice", plan_id=shoulder.id)
        assert [m.body for m in messages.thread(store, "P-017", "patient", plan_id=knee.id)] == ["knee is stiff"]
        assert [m.body for m in store.message_thread("P-017", shoulder.id)] == ["shoulder clicks", "try ice"]
        assert len(store.message_thread("P-017")) == 3                # every plan, for the therapist's full view

    def test_no_plan_named_means_the_current_one(self, store):
        shoulder = plans.open_plan(store, "P-017", "Left shoulder")
        m = messages.send(store, "P-017", "patient", "hello")
        assert m.plan_id == shoulder.id

    def test_unread_counts_per_plan_roll_up_to_the_patient(self, store):
        knee = store.plans("P-017")[0]
        shoulder = plans.open_plan(store, "P-017", "Left shoulder")
        for plan_id in (knee.id, shoulder.id, shoulder.id):
            messages.send(store, "P-017", "patient", "a note", plan_id=plan_id)
        assert store.messages_unread_by_plan("patient", "P-017") == {knee.id: 1, shoulder.id: 2}
        assert messages.unread_count(store, "P-017", "therapist") == 3
        messages.thread(store, "P-017", "therapist", plan_id=shoulder.id)       # reading one plan marks only it
        assert store.messages_unread_by_plan("patient", "P-017") == {knee.id: 1}
        view = {p["id"]: p["unread"] for p in plans.plans_view(store, "P-017", viewer="therapist")}
        assert view == {knee.id: 1, shoulder.id: 0}


class TestArchivedPlansAreReadOnly:
    """US1 scenario 2: both sides can read an archived plan, nothing can be added, edited, or deleted."""

    def test_reading_still_works(self, store):
        m = messages.send(store, "P-017", "therapist", "see you Tuesday")
        plan = archived(store)
        thread = messages.thread(store, "P-017", "patient", plan_id=plan.id)     # marking read is allowed
        assert [x.id for x in thread] == [m.id] and thread[0].read_at is not None

    def test_every_write_is_refused(self, store, fake_clock):
        m = messages.send(store, "P-017", "patient", "before")
        sid = store.start_session("P-017", "video", "clip.mp4")
        store.end_session(sid)
        entry = store.entry_add("P-017", "checkin", {"pain": 3, "note": "fine"}, 3.0, "2026-03-23T08:00:00",
                                "c-1", "before", None, False, False)
        store.assign_instrument("P-017", "demo_knee_function", "weekly")
        live = store.instrument_assignment("P-017", "demo_knee_function")
        store.media_add(Media(id=MEDIA_ID, patient_id="P-017", kind="clip", ext="mp4", container="mov",
                              codec="h264", bytes=10, duration=1.0, sha256="x"))
        plan = archived(store)
        refused = [
            lambda: store.message_add("P-017", "patient", "after", warned=False),
            lambda: store.message_add("P-017", "patient", "after", warned=False, plan_id=plan.id),
            lambda: messages.send(store, "P-017", "therapist", "after", plan_id=plan.id),
            lambda: store.message_remove(m.id),
            lambda: store.start_session("P-017", "video", "clip.mp4"),
            lambda: store.add_diary_session("P-017", INFO, 10, 1, None, "2026-03-23T08:00:00"),
            lambda: store.set_review(sid, "continue"),
            lambda: store.entry_add("P-017", "checkin", {"pain": 2}, 2.0, "2026-03-23T09:00:00", "c-2", "before",
                                    None, False, False),
            lambda: store.entry_remove_note(entry.id),
            lambda: store.assign_program("P-017", "custom", "Knee", ["knee_extension"]),
            lambda: store.assign_instrument("P-017", "demo_knee_function", "monthly"),
            lambda: store.end_assignment(live.id),
            lambda: store.media_add(Media(id="00000000-0000-4000-8000-0000000000bb", patient_id="P-017", kind="clip",
                                          ext="mp4", container="mov", codec="h264", bytes=10, duration=1.0, sha256="y")),
            lambda: store.media_update(MEDIA_ID, caption="changed"),
            lambda: store.media_update(MEDIA_ID, reviewed_at="2026-03-23T10:00:00"),
            lambda: plans.edit_plan(store, plan.id, title="Renamed"),
            lambda: plans.schedule(store, "P-017", "2026-03-30T09:00", 45, plan_id=plan.id),
        ]
        for n, write in enumerate(refused):
            with pytest.raises(PlanArchived):
                write()
            store.conn.rollback()
        assert [x.body for x in store.message_thread("P-017")] == ["before"]

    def test_the_patient_may_still_delete_their_own_upload(self, store):
        store.media_add(Media(id=MEDIA_ID, patient_id="P-017", kind="clip", ext="mp4", container="mov",
                              codec="h264", bytes=10, duration=1.0, sha256="x"))
        archived(store)
        store.media_update(MEDIA_ID, deleted_at="2026-03-23T10:00:00", deleted_by="patient")
        assert store.media_get(MEDIA_ID).deleted_by == "patient"

    def test_a_new_plan_takes_new_records_again(self, store):
        archived(store)
        fresh = plans.open_plan(store, "P-017", "Right knee, second episode")
        assert messages.send(store, "P-017", "patient", "back again").plan_id == fresh.id
