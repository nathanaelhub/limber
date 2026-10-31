"""Feature 017 in the therapist app (T010): the inbox by plan with attachments and reschedule flags, and plans
of care and appointments on the patient page. Streamlit AppTest, so no browser is needed."""

import io
from datetime import date, timedelta

from PIL import Image
from streamlit.testing.v1 import AppTest

from src.portal import messages, plans
from src.ptlog.store import SessionStore
from tests.test_app_pages import APP, seeded_env  # noqa: F401  (fixture)


def _png():
    out = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 120, 100)).save(out, "PNG")
    return out.getvalue()


def _seed(db):
    with SessionStore(db).open() as s:
        s.add_patient("P-021")
        messages.set_enabled(s, "P-021", True)
        knee = s.plans("P-021")[0]
        plans.edit_plan(s, knee.id, title="Right knee, post-op")
        shoulder = plans.open_plan(s, "P-021", "Left shoulder")
        messages.send(s, "P-021", "patient", "Knee felt tight on the stairs", plan_id=knee.id,
                      files=[("image/png", _png())], media_dir=s.media_dir)
        messages.send(s, "P-021", "patient", "Shoulder clicks overhead", plan_id=shoulder.id)
        a = plans.schedule(s, "P-021", (date.today() + timedelta(days=5)).isoformat() + "T09:00", 45,
                           "Re-check range of motion", plan_id=knee.id)
        plans.request_reschedule(s, "P-021", a.id, "Afternoons are better")
    return knee, shoulder, a


def _app(page, **state):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = page
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def _text(at):
    return " ".join([x.value for x in at.text] + [x.value for x in at.markdown] + [c.value for c in at.caption] +
                    [w.value for w in at.warning] + [i.value for i in at.info])


class TestInboxByPlan:
    def test_one_plan_at_a_time_with_the_photo_and_the_flag(self, seeded_env):  # noqa: F811
        knee, shoulder, _ = _seed(seeded_env)
        at = _app("inbox", inbox_open="P-021", inbox_plan=knee.id)
        assert not at.exception, [e.value for e in at.exception]
        shown = _text(at)
        assert "stairs" in shown and "clicks overhead" not in shown
        assert "1 photo" in shown
        assert "asked to reschedule" in shown and "Afternoons are better" in shown
        with SessionStore(seeded_env).open() as s:                 # only the open plan was marked read
            assert s.messages_unread_by_plan("patient", "P-021") == {shoulder.id: 1}

    def test_a_reply_goes_into_the_chosen_plan(self, seeded_env):  # noqa: F811
        knee, shoulder, _ = _seed(seeded_env)
        at = _app("inbox", inbox_open="P-021", inbox_plan=shoulder.id)
        at.text_area(key="inbox_reply").set_value("Keep the arm below shoulder height for now.").run()
        at.button(key="inbox_send").click().run()
        assert not at.exception, [e.value for e in at.exception]
        with SessionStore(seeded_env).open() as s:
            last = messages.thread(s, "P-021", "therapist", mark_read=False, plan_id=shoulder.id)[-1]
            assert (last.sender, last.plan_id) == ("therapist", shoulder.id)

    def test_an_archived_plan_is_read_only(self, seeded_env):  # noqa: F811
        knee, *_ = _seed(seeded_env)
        with SessionStore(seeded_env).open() as s:
            plans.complete(s, knee.id)
            plans.archive(s, knee.id)
        at = _app("inbox", inbox_open="P-021", inbox_plan=knee.id)
        assert not at.exception, [e.value for e in at.exception]
        assert "archived" in _text(at) and not [t for t in at.text_area if t.key == "inbox_reply"]


class TestPlansOnThePatientPage:
    def test_open_edit_complete_and_archive(self, seeded_env):  # noqa: F811
        _seed(seeded_env)
        at = _app("patients", patients_edit_select="P-021")
        assert not at.exception, [e.value for e in at.exception]
        at.text_input(key="plan_new_title_P-021").set_value("Left ankle")
        at.text_area(key="plan_new_diagnosis_P-021").set_value("Lateral ankle sprain, grade II")
        at.button(key="plan_open").click().run()
        assert not at.exception, [e.value for e in at.exception]
        with SessionStore(seeded_env).open() as s:
            ankle = [p for p in s.plans("P-021") if p.title == "Left ankle"][0]
            assert ankle.diagnosis.startswith("Lateral") and ankle.diagnosis_visible is False
        at.session_state["plan_edit_select_P-021"] = ankle.id
        at.run()
        at.toggle(key=f"plan_show_dx_{ankle.id}").set_value(True)
        at.button(key=f"plan_save_{ankle.id}").click().run()
        at.button(key=f"plan_complete_{ankle.id}").click().run()
        at.button(key=f"plan_archive_{ankle.id}").click().run()
        assert not at.exception, [e.value for e in at.exception]
        with SessionStore(seeded_env).open() as s:
            p = s.plan_get(ankle.id)
            assert p.diagnosis_visible is True and p.status == "archived"


class TestAppointmentsOnThePatientPage:
    def test_add_move_decline_and_cancel(self, seeded_env):  # noqa: F811
        knee, _, flagged = _seed(seeded_env)
        at = _app("patients", patients_edit_select="P-021")
        assert "Afternoons are better" in _text(at)
        day = date.today() + timedelta(days=9)
        at.date_input(key="appt_new_date_P-021").set_value(day)
        at.text_input(key="appt_new_time_P-021").set_value("14:30")
        at.number_input(key="appt_new_minutes_P-021").set_value(30)
        at.text_input(key="appt_new_note_P-021").set_value("Strength check")
        at.button(key="appt_add").click().run()
        assert not at.exception, [e.value for e in at.exception]
        with SessionStore(seeded_env).open() as s:
            added = [a for a in s.appointments("P-021") if a.note == "Strength check"][0]
            assert plans.appointment_json(s, added)["time"] == "14:30"
        at.text_input(key=f"appt_move_time_{flagged.id}").set_value("15:00")
        at.button(key=f"appt_move_{flagged.id}").click().run()
        with SessionStore(seeded_env).open() as s:
            moved = s.appointment_get(flagged.id)
            assert moved.reschedule_requested is False and plans.appointment_json(s, moved)["time"] == "15:00"
            plans.request_reschedule(s, "P-021", flagged.id, "Still no good")
        at.run()
        at.text_input(key=f"appt_reply_{flagged.id}").set_value("That's the only slot this week.")
        at.button(key=f"appt_decline_{flagged.id}").click().run()
        at.button(key=f"appt_cancel_{added.id}").click().run()
        assert not at.exception, [e.value for e in at.exception]
        with SessionStore(seeded_env).open() as s:
            assert s.appointment_get(flagged.id).response_note == "That's the only slot this week."
            assert s.appointment_get(added.id).status == "cancelled"
