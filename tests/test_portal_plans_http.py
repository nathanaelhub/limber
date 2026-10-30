"""Feature 017 through the portal: plans, a conversation per plan, attachments, appointments, and the 409
every write route gives for an archived plan (SC-002)."""

import io

import pytest
from PIL import Image
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.portal import access, messages, plans
from src.ptlog.store import SessionStore
from tests.test_attachments import PDF, jpeg_with_gps

KEY = b"k" * 32
ORIGIN = "http://testserver"
H = {"Origin": ORIGIN}


@pytest.fixture
def setup(tmp_db):
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-018")
        for pid in ("P-017", "P-018"):
            s.conversation_set_enabled(pid, True)
        knee = s.plans("P-017")[0]
        shoulder = plans.open_plan(s, "P-017", "Left shoulder", diagnosis="Rotator cuff tendinopathy")
        codes = {pid: access.issue_code(s, KEY, pid)[0] for pid in ("P-017", "P-018")}
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN])
    with TestClient(app, base_url=ORIGIN) as c:
        assert c.post("/api/login", json={"code": codes["P-017"]}, headers=H).status_code == 200
        yield c, tmp_db, knee, shoulder, codes


def store(db):
    return SessionStore(db).open()


class TestPlansAndConversations:
    def test_plans_with_unread_and_the_diagnosis_kept_back(self, setup):
        c, db, knee, shoulder, _ = setup
        with store(db) as s:
            messages.send(s, "P-017", "therapist", "How was the week?", plan_id=shoulder.id)
        listed = c.get("/api/plans").json()["plans"]
        assert [(p["title"], p["unread"]) for p in listed] == [("Plan of care", 0), ("Left shoulder", 1)]
        assert all("diagnosis" not in p for p in listed)

    def test_a_message_goes_into_one_plan(self, setup):
        c, _, knee, shoulder, _ = setup
        r = c.post(f"/api/plans/{shoulder.id}/messages", json={"text": "it clicks"}, headers=H)
        assert r.status_code == 201 and r.json()["plan_id"] == shoulder.id
        assert c.get(f"/api/plans/{knee.id}/messages").json()["messages"] == []
        view = c.get(f"/api/plans/{shoulder.id}/messages").json()
        assert [m["text"] for m in view["messages"]] == ["it clicks"] and view["can_send"] is True

    def test_another_patients_plan_is_not_found(self, setup):
        c, db, *_ = setup
        with store(db) as s:
            other = s.plans("P-018")[0].id
        assert c.get(f"/api/plans/{other}/messages").status_code == 404
        assert c.post(f"/api/plans/{other}/messages", json={"text": "hi"}, headers=H).status_code == 404

    def test_needs_sign_in_and_the_page_origin(self, setup):
        c, _, knee, *_ = setup
        assert c.post(f"/api/plans/{knee.id}/messages", json={"text": "x"},
                      headers={"Origin": "http://evil.test"}).status_code == 403
        c.cookies.clear()
        assert c.get("/api/plans").status_code == 401
        assert c.get(f"/api/plans/{knee.id}/messages").status_code == 401
        assert c.get("/api/appointments").status_code == 401


class TestAttachmentsOverHttp:
    def test_photos_go_up_stripped_and_come_back_private(self, setup):
        c, _, knee, *_ = setup
        r = c.post(f"/api/plans/{knee.id}/messages", headers=H, data={"text": "swelling"},
                   files=[("files", ("knee.jpg", jpeg_with_gps(), "image/jpeg")),
                          ("files", ("knee2.jpg", jpeg_with_gps(), "image/jpeg"))])
        assert r.status_code == 201, r.text
        (a, b) = r.json()["attachments"]
        assert a["kind"] == "photo" and (a["width"], a["height"]) == (30, 40)
        got = c.get(f"/api/attachments/{a['id']}")
        assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
        assert got.headers["content-security-policy"] == "sandbox" and "no-store" in got.headers["cache-control"]
        assert dict(Image.open(io.BytesIO(got.content)).getexif()) == {}
        assert "knee.jpg" not in got.headers["content-disposition"]
        assert c.delete(f"/api/attachments/{b['id']}", headers=H).status_code == 200
        assert c.get(f"/api/attachments/{b['id']}").status_code == 404

    def test_a_mismatched_file_is_refused_plainly(self, setup):
        c, _, knee, *_ = setup
        r = c.post(f"/api/plans/{knee.id}/messages", headers=H, data={"text": "x"},
                   files=[("files", ("scan.pdf", b"<html></html>", "application/pdf"))])
        assert r.status_code == 400 and "isn't the kind of file" in r.json()["error"]

    def test_another_patient_cannot_open_it(self, setup):
        c, _, knee, _, codes = setup
        r = c.post(f"/api/plans/{knee.id}/messages", headers=H, data={"text": ""},
                   files=[("files", ("plan.pdf", PDF, "application/pdf"))])
        att = r.json()["attachments"][0]["id"]
        c.cookies.clear()
        c.post("/api/login", json={"code": codes["P-018"]}, headers=H)
        assert c.get(f"/api/attachments/{att}").status_code == 404
        assert c.delete(f"/api/attachments/{att}", headers=H).status_code == 404


class TestAppointments:
    def test_list_and_ask_to_reschedule(self, setup):
        c, db, knee, *_ = setup
        with store(db) as s:
            plans.set_clinic_zone(s, "America/Chicago")
            a = plans.schedule(s, "P-017", "2030-11-04T09:00", 45, "Re-check range of motion", plan_id=knee.id)
            plans.schedule(s, "P-018", "2030-11-04T10:00", 45)
        body = c.get("/api/appointments").json()
        assert body["time_zone"] == "America/Chicago"
        (view,) = body["appointments"]
        assert (view["time"], view["state"], view["note"]) == ("09:00", "upcoming", "Re-check range of motion")
        r = c.post(f"/api/appointments/{a.id}/reschedule", json={"note": "Afternoon please"}, headers=H)
        assert r.status_code == 200 and r.json()["reschedule_requested"] is True
        assert c.post("/api/appointments/9999/reschedule", json={}, headers=H).status_code == 400


class TestArchivedPlanRefusesEveryWriteRoute:
    """SC-002."""

    @pytest.fixture
    def archived(self, setup):
        c, db, knee, shoulder, _ = setup
        with store(db) as s:
            a = plans.schedule(s, "P-017", "2030-11-04T09:00", 45, plan_id=knee.id)
            for plan in (knee, shoulder):
                plans.complete(s, plan.id)
                plans.archive(s, plan.id)
        return c, knee, a

    def test_409(self, archived):
        c, knee, appointment = archived
        writes = [
            c.post(f"/api/plans/{knee.id}/messages", json={"text": "hello"}, headers=H),
            c.post(f"/api/plans/{knee.id}/messages", headers=H, data={"text": ""},
                   files=[("files", ("a.jpg", jpeg_with_gps(), "image/jpeg"))]),
            c.post("/api/messages", json={"text": "hello"}, headers=H),
            c.post("/api/entries", json={"kind": "checkin", "client_id": "c1",
                                         "data": {"pain": 4, "area": "knee", "stiffness": "mild",
                                                  "swelling": "none", "note": ""}}, headers=H),
            c.post("/api/diary", json={"exercise": "squat", "reps": 12, "sets": 2, "effort": 3}, headers=H),
            c.post("/api/uploads", json={"kind": "clip", "total_bytes": 1000, "sha256": "0" * 64}, headers=H),
            c.post(f"/api/appointments/{appointment.id}/reschedule", json={"note": "x"}, headers=H),
        ]
        for r in writes:
            assert r.status_code == 409 and r.json().get("archived") is True, (r.request.url, r.status_code, r.text)
        view = c.get(f"/api/plans/{knee.id}/messages").json()
        assert view["plan"]["read_only"] is True and view["can_send"] is False
