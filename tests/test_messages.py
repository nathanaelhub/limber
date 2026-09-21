"""Feature 008 T002 — conversations between a patient and the therapist: rules and storage."""

from datetime import timedelta

import pytest

from src.portal import messages as msg
from src.ptlog.models import PatientNotFoundError, PortalError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-017", label="Post-op knee")
        s.add_patient("P-021")
        msg.set_enabled(s, "P-017", True)
        msg.set_enabled(s, "P-021", True)
        yield s


def texts(thread):
    return [(m.sender, m.body) for m in thread]


class TestBasics:
    def test_schema(self, store):
        tables = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert SCHEMA_VERSION >= 8 and {"conversations", "messages", "message_events"} <= tables
        assert [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION

    def test_off_by_default_and_toggle(self, store):
        store.add_patient("P-030")
        assert msg.is_enabled(store, "P-030") is False
        with pytest.raises(msg.MessagingOff):
            msg.send(store, "P-030", "patient", "hello")
        msg.set_enabled(store, "P-030", True)
        msg.send(store, "P-030", "patient", "hello")
        msg.set_enabled(store, "P-030", False)
        with pytest.raises(msg.MessagingOff):
            msg.send(store, "P-030", "therapist", "are you there")
        assert texts(msg.thread(store, "P-030", viewer="therapist")) == [("patient", "hello")]     # kept, not deleted
        with pytest.raises(PatientNotFoundError):
            msg.set_enabled(store, "P-404", True)

    def test_send_both_ways_and_plain_text_is_kept_exactly(self, store, fake_clock):
        body = "My knee felt <b>better</b> 🙂\nbut stairs are hard & slow"
        m = msg.send(store, "P-017", "patient", body)
        fake_clock.advance(60)
        msg.send(store, "P-017", "therapist", "  Good. Keep the pace slow on stairs.  ")
        t = msg.thread(store, "P-017", viewer="therapist")
        assert texts(t) == [("patient", body), ("therapist", "Good. Keep the pace slow on stairs.")]
        assert t[0].id == m.id and t[0].sent_at < t[1].sent_at

    @pytest.mark.parametrize("bad", ["", "   ", None, "x" * 2001, 42])
    def test_length_rules(self, store, bad):
        with pytest.raises(PortalError):
            msg.send(store, "P-017", "patient", bad)

    def test_sender_must_be_a_side(self, store):
        with pytest.raises(PortalError):
            msg.send(store, "P-017", "stranger", "hello")

    def test_discharged_patients_are_read_only(self, store):
        msg.send(store, "P-017", "patient", "before")
        store.discharge("P-017")
        for side in ("patient", "therapist"):
            with pytest.raises(msg.MessagingOff):
                msg.send(store, "P-017", side, "after")
        assert len(msg.thread(store, "P-017", viewer="therapist")) == 1


class TestPrivacyCheck:
    @pytest.mark.parametrize("text,reason", [
        ("This is Jane Smith writing", "name"),
        ("I was born 04/12/1961", "date"),
        ("my record number is 12345678", "record number"),
        ("call me on 615-555-0142 please", "phone number"),
        ("write to jane@example.org", "email address"),
    ])
    def test_reasons(self, text, reason):
        assert reason in msg.check_text(text)

    def test_ordinary_text_passes(self):
        assert msg.check_text("My knee hurt after 10 reps on Tuesday, about 3 out of 10.") == []

    def test_warn_then_allow_and_record_the_choice(self, store):
        with pytest.raises(msg.NeedsConfirmation) as warned:
            msg.send(store, "P-017", "patient", "call me on 615-555-0142")
        assert warned.value.reasons == ["phone number"] and msg.thread(store, "P-017", viewer="therapist") == []
        m = msg.send(store, "P-017", "patient", "call me on 615-555-0142", confirm=True)
        assert m.warned is True
        assert msg.send(store, "P-017", "patient", "thanks").warned is False
        events = store.message_events("P-017")
        assert [e["event"] for e in events][:2] == ["sent", "sent_despite_warning"]
        assert "615" not in str(events)                                   # the history never holds message text


class TestLimits:
    def test_twenty_an_hour_for_the_patient(self, store, fake_clock):
        for i in range(20):
            msg.send(store, "P-017", "patient", f"message {i}")
        with pytest.raises(msg.TooManyMessages):
            msg.send(store, "P-017", "patient", "one more")
        msg.send(store, "P-017", "therapist", "the therapist is not limited")
        msg.send(store, "P-021", "patient", "another patient is not affected")
        fake_clock.advance(3601)
        msg.send(store, "P-017", "patient", "an hour later")


class TestReadAndInbox:
    def test_reading_marks_only_the_other_sides_messages(self, store, fake_clock):
        msg.send(store, "P-017", "patient", "one")
        msg.send(store, "P-017", "patient", "two")
        msg.send(store, "P-017", "therapist", "reply")
        assert msg.unread_count(store, "P-017", viewer="therapist") == 2
        assert msg.unread_count(store, "P-017", viewer="patient") == 1
        msg.thread(store, "P-017", viewer="patient")
        assert msg.unread_count(store, "P-017", viewer="patient") == 0
        assert msg.unread_count(store, "P-017", viewer="therapist") == 2          # untouched
        msg.thread(store, "P-017", viewer="therapist", mark_read=False)
        assert msg.unread_count(store, "P-017", viewer="therapist") == 2
        msg.thread(store, "P-017", viewer="therapist")
        msg.thread(store, "P-017", viewer="therapist")                             # twice: no duplicates, no errors
        assert msg.unread_count(store, "P-017", viewer="therapist") == 0

    def test_inbox_newest_first_with_first_line_and_counts(self, store, fake_clock):
        msg.send(store, "P-017", "patient", "First line of mine\nsecond line")
        fake_clock.advance(60)
        msg.send(store, "P-021", "patient", "x" * 200)
        rows = msg.inbox(store)
        assert [(r.patient_id, r.unread) for r in rows] == [("P-021", 1), ("P-017", 1)]
        assert rows[1].first_line == "First line of mine" and len(rows[0].first_line) <= 81 and rows[0].first_line.endswith("…")
        assert msg.total_unread(store) == 2 and rows[0].enabled is True
        store.add_patient("P-040")
        assert "P-040" not in [r.patient_id for r in msg.inbox(store)]             # no conversation yet
        assert "P-040" in [r.patient_id for r in msg.inbox(store, include_empty=True)]


class TestRemoveAndCascade:
    def test_remove_leaves_a_marker(self, store):
        m = msg.send(store, "P-017", "patient", "I am Jane Smith", confirm=True)
        assert msg.remove(store, m.id) is True and msg.remove(store, m.id) is False
        (shown,) = msg.thread(store, "P-017", viewer="patient")
        assert shown.removed is True and shown.body == "" and "Jane" not in str(shown)
        assert store.conn.execute("SELECT body FROM messages WHERE id = ?", (m.id,)).fetchone()[0] == ""
        assert "removed" in [e["event"] for e in store.message_events("P-017")]

    def test_conversation_follows_the_patient(self, store):
        msg.send(store, "P-017", "patient", "hello")
        store.conn.execute("UPDATE patients SET id = 'P-117' WHERE id = 'P-017'")
        store.conn.commit()
        assert len(msg.thread(store, "P-117", viewer="therapist")) == 1
        store.delete_patient("P-117")
        for table in ("conversations", "messages", "message_events"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE patient_id = 'P-117'").fetchone()[0] == 0
