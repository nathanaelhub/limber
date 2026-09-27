"""Feature 014 T006/T008 — a spoken note arrives as a message the therapist already knows how to read.

Everything below the message is feature 011's pipeline; what is new is that finishing a `voice` upload
puts the recording in the conversation, and that the patient's own rules (messaging on, not discharged)
decide whether it is offered at all.
"""

import hashlib
from datetime import datetime, timedelta

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.media.probe import MediaRejected
from src.portal import access, messages, uploads, voice
from src.ptlog.models import PortalError
from src.ptlog.store import SessionStore
from tests.fixtures import media as fx

KEY = b"k" * 32
ORIGIN = "http://testserver"
NOW = datetime(2026, 9, 27, 18, 0, 0)


@pytest.fixture
def env(tmp_db, tmp_path):
    from tests.conftest import FakeClock
    with SessionStore(tmp_db, clock=FakeClock(NOW)).open() as store:
        store.add_patient("P-017")
        store.add_patient("P-018")
        for pid in ("P-017", "P-018"):
            messages.set_enabled(store, pid, True)
        note = fx.make_audio(tmp_path / "note.m4a", seconds=2.0)
        yield store, store.media_dir, note


def send_voice(store, media_dir, patient, path, confirm=False, chunk=4096):
    data = path.read_bytes()
    up = uploads.begin(store, media_dir, patient, "voice", len(data), hashlib.sha256(data).hexdigest(),
                       chunk_bytes=chunk)
    for n, start in enumerate(range(0, len(data), chunk)):
        uploads.put_part(store, media_dir, patient, up.id, n, data[start:start + chunk])
    return voice.finish(store, media_dir, patient, up.id, confirm=confirm)


class TestSendingAVoiceNote:
    def test_it_arrives_as_a_message_with_its_recording(self, env):
        store, media_dir, note = env
        media = send_voice(store, media_dir, "P-017", note)
        assert media.kind == "voice" and media.ext == "m4a" and 1.5 <= media.duration <= 2.5
        assert uploads.media_path(media_dir, media).is_file()
        (message,) = store.message_thread("P-017")
        assert message.sender == "patient" and message.body == "" and message.media_id == media.id
        assert store.messages_unread("patient") == {"P-017": 1}       # the therapist sees one new thing
        assert store.message_for_media(media.id).id == message.id
        assert [m.id for m in uploads.list_media(store, "P-017", "voice")] == [media.id]
        assert uploads.list_media(store, "P-017", "clip") == []       # counted apart from clips
        events = [(a.event, a.detail) for a in store.portal_audit_list("P-017")]
        assert ("upload_stored", "voice") in events

    def test_the_patient_sees_it_in_their_own_conversation(self, env):
        store, media_dir, note = env
        media = send_voice(store, media_dir, "P-017", note)
        view = messages.thread(store, "P-017", viewer="patient")
        (shown,) = view
        assert shown.media_id == media.id and shown.body == ""
        assert voice.playable(store, "P-017", media.id) is not None
        assert voice.playable(store, "P-018", media.id) is None       # not theirs

    def test_a_refused_recording_leaves_no_message(self, env, tmp_path):
        store, media_dir, _ = env
        with_video = fx.make_video(tmp_path / "v.mp4", seconds=1.5, audio=True)
        with pytest.raises(MediaRejected) as err:
            send_voice(store, media_dir, "P-017", with_video)
        assert err.value.reason == "has_video"
        assert store.message_thread("P-017") == [] and uploads.list_media(store, "P-017", "voice") == []
        assert store.portal_audit_list("P-017")[0].event == "upload_rejected"

    def test_deleting_removes_the_file_and_marks_the_message(self, env):
        store, media_dir, note = env
        media = send_voice(store, media_dir, "P-017", note)
        path = uploads.media_path(media_dir, media)
        assert voice.delete(store, media_dir, "P-017", media.id, by="patient") is True
        assert not path.exists()
        (message,) = store.message_thread("P-017")
        assert message.removed is True and message.media_id is None
        assert store.media_get(media.id).deleted_by == "patient"      # the marker stays
        assert store.messages_unread("patient") == {}
        assert voice.delete(store, media_dir, "P-017", media.id, by="patient") is False

    def test_another_patients_recording_is_simply_not_found(self, env):
        store, media_dir, note = env
        media = send_voice(store, media_dir, "P-017", note)
        assert voice.delete(store, media_dir, "P-018", media.id, by="patient") is False
        assert uploads.media_path(media_dir, media).exists()

    def test_refused_when_messaging_is_off_or_the_patient_is_discharged(self, env):
        store, media_dir, note = env
        messages.set_enabled(store, "P-017", False)
        with pytest.raises(PortalError) as err:
            send_voice(store, media_dir, "P-017", note)
        assert "message" in str(err.value).lower()
        assert store.message_thread("P-017") == [] and uploads.list_media(store, "P-017", "voice") == []
        messages.set_enabled(store, "P-017", True)
        store.discharge("P-018", reason="finished")
        with pytest.raises(PortalError):
            send_voice(store, media_dir, "P-018", note)

    def test_the_hourly_message_limit_still_applies(self, env):
        store, media_dir, note = env
        for _ in range(messages.PATIENT_PER_HOUR):
            messages.send(store, "P-017", "patient", "typed message")
        with pytest.raises(messages.TooManyMessages):
            send_voice(store, media_dir, "P-017", note)
        assert uploads.list_media(store, "P-017", "voice") == []      # nothing stored when it is refused


class TestOverHttp:
    @pytest.fixture
    def client(self, env, tmp_db):
        """The other patient's note is seeded before the service starts: two writers on one SQLite
        file at once is a locked database, not a test."""
        store, media_dir, note = env
        theirs = send_voice(store, media_dir, "P-018", note)
        codes = {pid: access.issue_code(store, KEY, pid)[0] for pid in ("P-017", "P-018")}
        app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN])
        with TestClient(app, base_url=ORIGIN) as c:
            c.post("/api/login", json={"code": codes["P-017"]}, headers={"Origin": ORIGIN})
            yield c, note, store, theirs

    def upload(self, c, note, chunk=4096):
        data = note.read_bytes()
        begun = c.post("/api/uploads", json={"kind": "voice", "total_bytes": len(data),
                                             "sha256": hashlib.sha256(data).hexdigest(), "chunk_bytes": chunk},
                       headers={"Origin": ORIGIN})
        assert begun.status_code == 201, begun.text
        upload_id = begun.json()["id"]
        for n, start in enumerate(range(0, len(data), chunk)):
            part = c.put(f"/api/uploads/{upload_id}/parts/{n}", content=data[start:start + chunk],
                         headers={"Origin": ORIGIN, "Content-Type": "application/octet-stream"})
            assert part.status_code == 200, part.text
        return upload_id

    def test_the_whole_way_over_http(self, client):
        c, note, store, _ = client
        upload_id = self.upload(c, note)
        done = c.post(f"/api/uploads/{upload_id}/finish", json={"as": "voice"}, headers={"Origin": ORIGIN})
        assert done.status_code == 201, done.text
        body = done.json()
        assert body["kind"] == "voice" and body["type"].startswith("audio/")
        thread = c.get("/api/messages").json()["messages"]
        assert len(thread) == 1 and thread[0]["media_id"] == body["id"] and thread[0]["from"] == "you"
        played = c.get(f"/api/media/{body['id']}")
        assert played.status_code == 200 and played.headers["content-type"].startswith("audio/")
        assert c.delete(f"/api/media/{body['id']}", headers={"Origin": ORIGIN}).status_code == 200
        assert c.get("/api/messages").json()["messages"][0]["removed"] is True

    def test_today_offers_a_voice_note_only_when_messaging_is_on(self, client):
        c, note, store, _ = client
        assert c.get("/api/today").json()["voice"]["enabled"] is True
        messages.set_enabled(store, "P-017", False)
        body = c.get("/api/today").json()
        assert body["voice"]["enabled"] is False and "notice" in body["voice"]

    def test_the_page_is_served_and_states_the_notice(self, client):
        c = client[0]
        r = c.get("/voice")
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert "therapist" in r.text.lower() and "delete" in r.text.lower()

    def test_no_other_patients_recording_on_the_new_routes(self, client):
        c, note, store, other = client
        assert c.get(f"/api/media/{other.id}").status_code == 404
        assert c.delete(f"/api/media/{other.id}", headers={"Origin": ORIGIN}).status_code == 404
        for route in ("/api/today", "/api/messages", "/api/media", "/voice"):
            text = c.get(route).text
            assert "P-018" not in text and other.id not in text, route
