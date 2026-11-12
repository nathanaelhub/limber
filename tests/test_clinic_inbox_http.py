"""Feature 019 slice 2 (T013 to T015): the Inbox through the clinic app.

Opening the Inbox marks nothing read (FR-007); the warning and Send anyway work as before; an AI draft lands in
the reply box and is never sent on its own; a red-flag message withholds the draft and quotes the words (FR-008)."""

import io

import pytest

from src.portal import messages, plans
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in


@pytest.fixture
def world(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with SessionStore(tmp_db, clock=fake_clock).open() as store:
        knee = plans.open_plan(store, "P-001", "Post-op knee")
        for pid in ("P-001", "P-002"):
            messages.set_enabled(store, pid, True)
        messages.send(store, "P-001", "patient", "Is some <b>swelling</b> normal?", plan_id=knee.id)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        yield c, knee.id, tmp_db, fake_clock


def _unread(db, clock):
    with SessionStore(db, clock=clock).open() as store:
        return store.messages_unread("patient").get("P-001", 0)


def _thread(db, clock):
    with SessionStore(db, clock=clock).open() as store:
        return store.message_thread("P-001")


def test_the_inbox_and_the_conversation_page_mark_nothing_read(world):
    c, plan, db, clock = world
    page = c.get("/therapist/inbox")
    assert page.status_code == 200 and f'href="/therapist/inbox/P-001?plan={plan}"' in page.text
    assert "1 new" in page.text and "Pick an item" in page.text
    convo = c.get(f"/therapist/inbox/P-001?plan={plan}")
    assert convo.status_code == 200 and 'data-mark-read="1"' in convo.text
    assert _unread(db, clock) == 1                                         # FR-007: still unread
    assert c.post("/therapist/api/inbox/P-001/read", json={"plan_id": plan}, headers=H).status_code == 200
    assert _unread(db, clock) == 0


def test_patient_text_is_never_markup(world):
    c, plan, _, _ = world
    page = c.get(f"/therapist/inbox/P-001?plan={plan}").text
    assert "Is some &lt;b&gt;swelling&lt;/b&gt; normal?" in page and "<b>swelling</b>" not in page
    from tests.test_clinic_static import _checked
    _checked(page, "conversation")                                         # no inline style or script either


def test_reply_warning_and_send_anyway(world):
    c, plan, db, clock = world
    r = c.post("/therapist/api/inbox/P-001/reply", json={"plan_id": plan, "text": "Call me on 615 555 0142"}, headers=H)
    assert r.status_code == 409 and r.json()["needs_confirm"] is True and "phone number" in r.json()["reasons"]
    assert len(_thread(db, clock)) == 1                                    # nothing sent
    r = c.post("/therapist/api/inbox/P-001/reply", json={"plan_id": plan, "text": "Call me on 615 555 0142",
                                                         "confirm": True}, headers=H)
    assert r.status_code == 201
    sent = _thread(db, clock)[-1]
    assert sent.sender == "therapist" and sent.warned and sent.plan_id == plan
    assert c.post("/therapist/api/inbox/P-001/reply", json={"plan_id": plan, "text": " "}, headers=H).status_code == 400


def test_reply_with_a_photo_as_a_form(world):
    from PIL import Image
    c, plan, db, clock = world
    png = io.BytesIO()
    Image.new("RGB", (8, 8), "teal").save(png, "PNG")
    r = c.post("/therapist/api/inbox/P-001/reply", data={"plan_id": str(plan), "text": "Like this"},
               files=[("files", ("a.png", png.getvalue(), "image/png"))], headers=H)
    assert r.status_code == 201, r.text
    sent = _thread(db, clock)[-1]
    assert len(sent.attachments) == 1
    photo = c.get(f"/therapist/files/P-001/attachments/{sent.attachments[0].id}")
    assert photo.status_code == 200 and photo.headers["content-type"].startswith("image/")
    assert c.post("/therapist/api/inbox/P-001/uploads", json={"files": [{"type": "image/png", "size": 10}]},
                  headers=H).status_code == 501                             # local: files go with the reply


def test_no_key_no_draft_button(world):
    c, plan, _, _ = world
    page = c.get(f"/therapist/inbox/P-001?plan={plan}").text
    assert 'data-act="draft"' not in page
    assert c.post("/therapist/api/inbox/P-001/draft", json={"plan_id": plan}, headers=H).json()["state"] == "off"


def test_a_draft_lands_in_the_box_and_is_never_sent(world, monkeypatch):
    from src.assist import assistant, config
    c, plan, db, clock = world
    monkeypatch.setattr(config, "available", lambda: True)
    monkeypatch.setattr(assistant, "switches", lambda store, pid: {"summaries": True, "coach": False})
    monkeypatch.setattr(assistant, "draft_reply", lambda store, pid, plan_id, account_id=None:
                        assistant.DraftResult("ok", text="Some swelling is expected."))
    page = c.get(f"/therapist/inbox/P-001?plan={plan}").text
    assert 'data-act="draft"' in page and "AI-drafted — check before sending" in page
    r = c.post("/therapist/api/inbox/P-001/draft", json={"plan_id": plan}, headers=H)
    assert r.json() == {"state": "ok", "text": "Some swelling is expected."}
    assert len(_thread(db, clock)) == 1                                    # nothing sent on its own
    c.post("/therapist/api/inbox/P-001/reply", json={"plan_id": plan, "text": "Some swelling is expected.",
                                                     "from_draft": True}, headers=H)
    assert _thread(db, clock)[-1].from_draft is True


def test_a_red_flag_withholds_the_draft_and_quotes_the_words(world, monkeypatch):
    from src.assist import assistant, config
    c, plan, db, clock = world
    monkeypatch.setattr(config, "available", lambda: True)
    monkeypatch.setattr(assistant, "switches", lambda store, pid: {"summaries": True, "coach": False})
    with SessionStore(db, clock=clock).open() as store:
        messages.send(store, "P-001", "patient", "I have chest pain since this morning", plan_id=plan)
    page = c.get(f"/therapist/inbox/P-001?plan={plan}").text
    assert "This message may need a direct response" in page and "“chest pain”" in page
    assert 'data-act="draft"' not in page and 'data-act="handled"' in page
    assert "Urgent" in c.get("/therapist/inbox").text
    assert c.post("/therapist/api/inbox/P-001/handled", json={"plan_id": plan}, headers=H).json() == {"handled": 1}
    assert "Urgent" not in c.get("/therapist/inbox").text
    assert 'data-act="draft"' in c.get(f"/therapist/inbox/P-001?plan={plan}").text


def test_messaging_off_closes_the_reply_box(world):
    c, plan, _, _ = world
    assert c.post("/therapist/api/inbox/P-001/messaging", json={"enabled": False}, headers=H).json() == {"enabled": False}
    page = c.get(f"/therapist/inbox/P-001?plan={plan}").text
    assert "Messaging is off for P-001" in page and "data-reply" not in page
    r = c.post("/therapist/api/inbox/P-001/reply", json={"plan_id": plan, "text": "Hello"}, headers=H)
    assert r.status_code == 403


def test_remove_a_message_leaves_a_marker(world):
    c, plan, db, clock = world
    mid = _thread(db, clock)[0].id
    assert c.post(f"/therapist/api/inbox/P-001/messages/{mid}/remove", json={}, headers=H).status_code == 200
    assert _thread(db, clock)[0].removed
    assert "This message was removed." in c.get(f"/therapist/inbox/P-001?plan={plan}").text


def test_an_archived_plan_is_read_only(world, tmp_db, fake_clock):
    c, plan, db, clock = world
    mid = _thread(db, clock)[0].id
    with SessionStore(db, clock=clock).open() as store:
        plans.complete(store, plan)
        plans.archive(store, plan)
    page = c.get(f"/therapist/inbox/P-001?plan={plan}").text
    assert "data-reply" not in page and "archived" in page and 'data-act="remove"' not in page
    r = c.post(f"/therapist/api/inbox/P-001/messages/{mid}/remove", json={}, headers=H)
    assert r.status_code == 409


def test_answering_a_reschedule_request(world):
    c, plan, db, clock = world
    with SessionStore(db, clock=clock).open() as store:
        a = plans.schedule(store, "P-001", "2026-03-30T09:00", 45, plan_id=plan)
        plans.request_reschedule(store, "P-001", a.id, "Afternoons are better")
    assert "Reschedule" in c.get("/therapist/inbox").text
    page = c.get(f"/therapist/inbox/P-001?plan={plan}").text
    assert f'data-visit="{a.id}"' in page and "“Afternoons are better”" in page
    r = c.post(f"/therapist/api/inbox/P-001/visits/{a.id}/answer",
               json={"answer": "move", "date": "2026-03-31", "time": "14:30", "note": "See you then."}, headers=H)
    assert r.status_code == 200
    with SessionStore(db, clock=clock).open() as store:
        moved = store.appointment_get(a.id)
        assert not moved.reschedule_requested and moved.response_note == "See you then."
        assert plans.appointment_json(store, moved)["time"] == "14:30"
    assert "Reschedule" not in c.get("/therapist/inbox").text


def test_another_therapists_conversation_is_not_found(world):
    c, plan, db, clock = world
    with SessionStore(db, clock=clock).open() as store:
        theirs = store.plans("P-002")[0]
        messages.send(store, "P-002", "patient", "Hello", plan_id=theirs.id)
        their_message = store.message_thread("P-002")[0].id
    assert c.get("/therapist/inbox/P-002").status_code == 404              # not the lead therapist's
    c.post("/therapist/api/logout", json={}, headers=H)
    sign_in(c, "rivera")
    assert c.get(f"/therapist/inbox/P-001?plan={plan}").status_code == 404
    assert c.post("/therapist/api/inbox/P-001/reply", json={"plan_id": plan, "text": "Hi"}, headers=H).status_code == 404
    # rivera's own patient, but a plan and a message of someone else's
    assert c.post("/therapist/api/inbox/P-002/reply", json={"plan_id": plan, "text": "Hi"}, headers=H).status_code == 404
    assert c.post(f"/therapist/api/inbox/P-002/messages/{their_message}/remove", json={}, headers=H).status_code == 200
    mid = _thread(db, clock)[0].id
    assert c.post(f"/therapist/api/inbox/P-002/messages/{mid}/remove", json={}, headers=H).status_code == 404
    assert not _thread(db, clock)[0].removed
