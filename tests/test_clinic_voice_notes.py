"""Feature 019 slice 8 (SC-003): the voice-note behaviours the Streamlit Inbox tests pinned (feature 014), through
the clinic app: the recording plays and can be marked heard or deleted (a marker stays), the reply box still works
beside it, and the written-out text shows its state and can be removed."""

import hashlib

import pytest

from src.media import transcribe
from src.portal import messages, uploads, voice
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in
from tests.fixtures import media as media_fx


@pytest.fixture
def world(tmp_db, fake_clock, tmp_path):
    seed(tmp_db, fake_clock)
    note = media_fx.make_audio(tmp_path / "note.m4a", seconds=2.0)
    data = note.read_bytes()
    with SessionStore(tmp_db, clock=fake_clock).open() as store:
        messages.set_enabled(store, "P-001", True)
        up = uploads.begin(store, store.media_dir, "P-001", "voice", len(data), hashlib.sha256(data).hexdigest(),
                           chunk_bytes=len(data))
        uploads.put_part(store, store.media_dir, "P-001", up.id, 0, data)
        media = voice.finish(store, store.media_dir, "P-001", up.id)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        yield c, tmp_db, fake_clock, media


def page(c):
    return c.get("/therapist/inbox/P-001").text


def test_it_plays_and_is_marked_heard(world):
    c, db, clock, media = world
    text = page(c)
    assert "Voice note · 2 s · not heard yet" in text and f'/therapist/files/P-001/voice/{media.id}' in text
    assert c.get(f"/therapist/files/P-001/voice/{media.id}").status_code == 200
    assert c.post(f"/therapist/api/inbox/P-001/voice/{media.id}/heard", json={}, headers=H).status_code == 200
    with SessionStore(db, clock=clock).open() as store:
        assert store.media_get(media.id).reviewed_at is not None
    assert "· heard" in page(c)


def test_delete_keeps_a_marker(world):
    c, db, clock, media = world
    assert c.post(f"/therapist/api/inbox/P-001/voice/{media.id}/delete", json={}, headers=H).status_code == 200
    with SessionStore(db, clock=clock).open() as store:
        assert store.media_get(media.id).deleted_by == "therapist"
        (message,) = store.message_thread("P-001")
        assert message.removed
    assert "removed" in page(c).lower()


def test_without_writing_out_it_says_so_and_the_reply_box_works(world):
    c, db, clock, media = world
    assert "not available on this installation" in page(c)
    r = c.post("/therapist/api/inbox/P-001/reply", json={"text": "Thank you, I have listened to that."}, headers=H)
    assert r.status_code == 201
    with SessionStore(db, clock=clock).open() as store:
        assert "Thank you, I have listened to that." in [m.body for m in store.message_thread("P-001")]


def test_a_transcript_shows_and_its_text_can_be_removed(world, monkeypatch):
    c, db, clock, media = world
    monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
    with SessionStore(db, clock=clock).open() as store:
        job = store.transcription_queue(media.id)
        store.transcription_start(job.id, model="fake-small")
        store.transcription_finish(job.id, text="the knee catches going down stairs", warned=False, seconds=3.2)
    text = page(c)
    assert "the knee catches going down stairs" in text and "may contain mistakes" in text
    assert c.post(f"/therapist/api/inbox/P-001/voice/{media.id}/text", json={}, headers=H).status_code == 200
    after = page(c)
    assert "the knee catches" not in after and "the text was removed" in after


def test_a_failed_writing_out_says_why(world, monkeypatch):
    c, db, clock, media = world
    monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
    with SessionStore(db, clock=clock).open() as store:
        job = store.transcription_queue(media.id)
        store.transcription_start(job.id, model="fake-small")
        store.transcription_fail(job.id, reason="timeout")
    text = page(c)
    assert "it did not work (timeout)" in text and "<audio" in text


def test_the_dashboard_says_when_there_are_no_sessions(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        assert "No sessions recorded yet" in c.get("/therapist/dashboard").text
