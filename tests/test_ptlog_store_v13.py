"""Feature 014 T004 — a message may carry audio, and a transcript belongs to that audio.

The link needs no schema change at all: `media.message_id` has been there since feature 011, so a voice
note points at the message it arrived as, and `Message.media_id` is read back through that column. Only
`transcriptions` is new. The migration test still counts every table, because the cheap migrations are
the ones that lose rows quietly.
"""

import sqlite3
from datetime import datetime

import pytest

from src.ptlog.models import Media, PTLogError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

PREVIOUS = 12
MEDIA_ID = "00000000-0000-4000-8000-000000000001"


def _previous_version_record(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, sql in MIGRATIONS:
        if version > PREVIOUS:
            break
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version VALUES (?, '2026-03-01T00:00:00')", (version,))
    conn.commit()
    conn.close()
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys=ON")
    for pid, builtin in (("P-017", 0), ("P-018", 0), ("unassigned", 1)):
        conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES (?, ?, NULL, '2026-03-01', ?)",
                     (pid, "label " + pid, builtin))
    conn.execute("INSERT INTO conversations (patient_id, enabled, updated_at) VALUES ('P-017', 1, '2026-09-01T09:00:00')")
    conn.execute("INSERT INTO messages (patient_id, sender, body, sent_at) VALUES ('P-017', 'patient', 'my knee hurts', '2026-09-01T09:00:00')")
    conn.execute("INSERT INTO media (id, patient_id, kind, ext, container, codec, bytes, duration, sha256, created_at) "
                 "VALUES (?, 'P-017', 'clip', 'mp4', 'mov', 'h264', 100, 2.0, 'x', '2026-09-01T11:00:00')", (MEDIA_ID,))
    conn.execute("INSERT INTO instrument_assignments (patient_id, instrument_key, interval, start_date, created_at) "
                 "VALUES ('P-017', 'demo_knee_function', 'weekly', '2026-09-01', '2026-09-01T09:00:00')")
    conn.commit()
    conn.close()


def _counts(path):
    conn = sqlite3.connect(str(path))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.close()
    return counts


def test_the_upgrade_keeps_every_row(tmp_db):
    _previous_version_record(tmp_db)
    before = _counts(tmp_db)
    assert "transcriptions" not in before
    with SessionStore(tmp_db).open() as s:
        assert SCHEMA_VERSION >= 13 and [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION
        assert s.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        thread = s.message_thread("P-017")
        assert [m.body for m in thread] == ["my knee hurts"] and thread[0].media_id is None
        assert len(s.assignments("P-017")) == 1 and s.media_get(MEDIA_ID) is not None
    after = _counts(tmp_db)
    assert after["transcriptions"] == 0
    for table, n in before.items():
        expected = n + (SCHEMA_VERSION - PREVIOUS) if table == "schema_version" else n
        assert after[table] == expected, f"{table}: {n} rows before, {after[table]} after"


class TestAMessageWithAudio:
    @pytest.fixture
    def store(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as s:
            s.add_patient("P-017")
            s.add_patient("P-018")
            s.conversation_set_enabled("P-017", True)
            s.media_add(Media(id=MEDIA_ID, patient_id="P-017", kind="voice", ext="m4a", container="mov",
                              codec="aac", bytes=2048, duration=12.5, sha256="hash"))
            yield s

    def _voice_id(self, store):
        return store.media_list("P-017", "voice")[0].id

    def test_a_message_can_carry_a_voice_note(self, store):
        media_id = self._voice_id(store)
        m = store.message_add("P-017", "patient", "", warned=False, media_id=media_id)
        assert m.media_id == media_id and m.sender == "patient"
        (stored,) = store.message_thread("P-017")
        assert stored.media_id == media_id and stored.body == ""
        assert store.messages_unread("patient") == {"P-017": 1}      # it counts as unread like any message
        assert store.message_for_media(media_id).id == m.id
        assert store.message_for_media("no-such-id") is None

    def test_removing_the_message_detaches_the_audio(self, store):
        """Removing a message must not leave its recording playable in the thread. Deleting the file
        itself is the therapist's Delete button, which goes through the media pipeline (US2)."""
        media_id = self._voice_id(store)
        m = store.message_add("P-017", "patient", "", warned=False, media_id=media_id)
        assert store.message_remove(m.id) is True
        (stored,) = store.message_thread("P-017")
        assert stored.removed is True and stored.media_id is None
        assert store.messages_unread("patient") == {}
        assert store.media_get(media_id) is not None                 # the row is still there to be deleted properly

    def test_deleting_the_recording_leaves_the_message_and_its_marker(self, store):
        media_id = self._voice_id(store)
        store.message_add("P-017", "patient", "", warned=False, media_id=media_id)
        store.media_update(media_id, deleted_at="2026-09-25T09:00:00", deleted_by="patient")
        (stored,) = store.message_thread("P-017")
        assert stored.media_id == media_id                          # the row stays, as the marker in the thread
        assert store.media_get(media_id).deleted_at is not None


class TestTranscriptions:
    @pytest.fixture
    def store(self, tmp_db, fake_clock):
        with SessionStore(tmp_db, clock=fake_clock).open() as s:
            s.add_patient("P-017")
            s.add_patient("P-018")
            for n, pid in enumerate(("P-017", "P-018"), start=1):
                s.media_add(Media(id=f"00000000-0000-4000-8000-00000000000{n}", patient_id=pid, kind="voice",
                                  ext="m4a", container="mov", codec="aac", bytes=2048, duration=9.0,
                                  sha256=f"hash-{pid}"))
            yield s

    def ids(self, store, pid="P-017"):
        return store.media_list(pid, "voice")[0].id

    def test_a_job_moves_through_its_states(self, store, fake_clock):
        media_id = self.ids(store)
        job = store.transcription_queue(media_id)
        assert (job.state, job.attempts, job.text) == ("queued", 0, None)
        assert [j.id for j in store.transcriptions_waiting()] == [job.id]
        started = store.transcription_start(job.id, model="fake-small")
        assert started.state == "running" and started.attempts == 1 and started.model == "fake-small"
        assert store.transcriptions_waiting() == []                  # a running job is not offered again
        fake_clock.advance(4)
        done = store.transcription_finish(job.id, text="my knee hurts on the stairs", warned=False, seconds=4.0)
        assert done.state == "done" and done.seconds == 4.0 and "stairs" in done.text
        assert store.transcription_for(media_id).state == "done"

    def test_a_failure_keeps_a_reason_word(self, store):
        media_id = self.ids(store)
        job = store.transcription_queue(media_id)
        store.transcription_start(job.id, model="fake-small")
        failed = store.transcription_fail(job.id, reason="timeout")
        assert failed.state == "failed" and failed.reason == "timeout" and failed.text is None

    def test_queueing_twice_keeps_one_job(self, store):
        media_id = self.ids(store)
        first = store.transcription_queue(media_id)
        assert store.transcription_queue(media_id).id == first.id
        assert len(store.transcriptions_waiting()) == 1

    def test_the_text_can_be_removed_by_the_therapist(self, store):
        media_id = self.ids(store)
        job = store.transcription_queue(media_id)
        store.transcription_start(job.id, model="fake-small")
        store.transcription_finish(job.id, text="I saw Doctor Jane Smith", warned=True, seconds=1.0)
        assert store.transcription_remove_text(job.id) is True
        row = store.transcription_for(media_id)
        assert row.text == "" and row.removed is True and row.warned is True
        assert store.transcription_remove_text(job.id) is False

    def test_a_transcript_goes_with_its_audio_and_its_patient(self, store):
        """A media row is kept as a marker when a recording is deleted, so the transcript has to be
        dropped deliberately: what was said must not outlive the recording of it (FR-006)."""
        mine, theirs = self.ids(store), self.ids(store, "P-018")
        for media_id in (mine, theirs):
            job = store.transcription_queue(media_id)
            store.transcription_start(job.id, model="fake-small")
            store.transcription_finish(job.id, text="said something", warned=False, seconds=1.0)
        assert store.transcription_drop(mine) is True
        assert store.transcription_for(mine) is None
        assert store.transcription_drop(mine) is False
        assert store.transcription_for(theirs) is not None
        store.delete_patient("P-018")                                # and the whole patient cascades
        assert store.transcription_for(theirs) is None
        assert store.conn.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0] == 0

    def test_a_job_for_an_unknown_recording_is_refused(self, store):
        with pytest.raises(PTLogError):
            store.transcription_queue("00000000-0000-4000-8000-000000000999")
