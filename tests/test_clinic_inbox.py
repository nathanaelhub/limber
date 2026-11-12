"""Feature 019 slice 2 (T012, FR-007 to FR-009): the Inbox's rules, tested without a server.

Moved from the Streamlit page: the "Needs you" list, the plan summary, which plan a conversation opens on, the
read-only precedence, and the voice-note states. Reading any of it marks nothing read."""

from datetime import datetime

import pytest

from src.clinic import inbox
from src.portal import accounts, messages, plans
from src.ptlog.store import SessionStore
from tests.clinic_helpers import seed


@pytest.fixture
def world(tmp_db, fake_clock):
    made = seed(tmp_db, fake_clock)
    store = SessionStore(tmp_db, clock=fake_clock).open()
    knee = plans.open_plan(store, "P-001", "Post-op knee")
    ankle = plans.open_plan(store, "P-001", "Left ankle")
    other = plans.open_plan(store, "P-002", "Shoulder")
    for pid in ("P-001", "P-002"):
        messages.set_enabled(store, pid, True)
    yield store, made, knee, ankle, other, fake_clock
    store.close()


def _unread(store, pid):
    return store.messages_unread("patient").get(pid, 0)


def test_needs_you_lists_unread_by_plan_and_marks_nothing_read(world):
    store, made, knee, ankle, _, clock = world
    messages.send(store, "P-001", "patient", "Is some swelling normal?", plan_id=knee.id)
    clock.advance(60)
    messages.send(store, "P-001", "patient", "The band feels easy now", plan_id=ankle.id)
    accounts.restrict(store, made["therapist"])
    items = inbox.needs_you(store)
    assert [(i.kind, i.plan_title, i.line) for i in items] == [
        ("unread", "Left ankle", "The band feels easy now"), ("unread", "Post-op knee", "Is some swelling normal?")]
    assert items[0].href == f"/therapist/inbox/P-001?plan={ankle.id}"
    inbox.thread(store, "P-001", knee)                              # displaying a thread marks nothing either
    assert _unread(store, "P-001") == 2


def test_a_red_flag_comes_first_with_the_words(world):
    store, made, knee, _, _, clock = world
    messages.send(store, "P-001", "patient", "Fine today", plan_id=knee.id)
    clock.advance(60)
    plans.schedule(store, "P-001", "2026-03-30T09:00", 45, plan_id=knee.id)
    a = store.appointments("P-001")[0]
    plans.request_reschedule(store, "P-001", a.id, "Afternoons are better")
    messages.send(store, "P-001", "patient", "I have chest pain since this morning", plan_id=knee.id)
    accounts.restrict(store, made["therapist"])
    items = inbox.needs_you(store)
    assert [i.kind for i in items] == ["urgent", "reschedule"]
    assert items[0].words == ["chest pain"]
    assert "Afternoons are better" in items[1].line and items[1].line.startswith("Asks to move Mon 30 Mar, 09:00")


def test_another_therapists_patients_never_appear(world):
    store, made, _, _, other, _ = world
    messages.send(store, "P-002", "patient", "Hello", plan_id=other.id)
    accounts.restrict(store, made["therapist"])
    assert inbox.needs_you(store) == []
    assert [c["patient_id"] for c in inbox.conversations(store)] == ["P-001"]


def test_by_id_checks_refuse_another_caseload(world):
    store, made, knee, _, other, _ = world
    theirs = messages.send(store, "P-002", "patient", "Hello", plan_id=other.id)
    accounts.restrict(store, made["therapist"])
    with pytest.raises(inbox.NotYours):
        inbox.own_patient(store, "P-002")
    with pytest.raises(inbox.NotYours):
        inbox.own_plan(store, "P-001", other.id)                   # a plan of another patient
    with pytest.raises(inbox.NotYours):
        inbox.own_message(store, "P-001", theirs.id)
    assert inbox.own_plan(store, "P-001", knee.id).id == knee.id and inbox.own_plan(store, "P-001", None) is None


def test_the_plan_summary_and_the_default_plan(world):
    store, _, knee, ankle, _, _ = world
    first = store.plans("P-001")[0]                                  # every patient starts with one plan
    plans.complete(store, ankle.id)
    plans.archive(store, ankle.id)
    assert inbox.plan_summary(store, "P-001") == f"{first.title} · Post-op knee"
    assert inbox.default_plan(store, "P-001").id == first.id         # the first that takes replies
    store.message_add("P-001", "patient", "About the knee", warned=False, plan_id=knee.id)
    assert inbox.plan_summary(store, "P-001") == f"{first.title} · Post-op knee (1)"
    assert inbox.default_plan(store, "P-001").id == knee.id          # unread wins over the first plan


def test_an_archived_plan_shows_only_while_it_holds_unread(world):
    store, _, _, ankle, _, _ = world
    store.message_add("P-001", "patient", "An old question", warned=False, plan_id=ankle.id)
    plans.complete(store, ankle.id)
    plans.archive(store, ankle.id)
    assert "Left ankle (1)" in inbox.plan_summary(store, "P-001")
    assert inbox.default_plan(store, "P-001").id == ankle.id


def test_read_only_precedence(world):
    store, _, knee, ankle, _, _ = world
    assert inbox.reply_state(store, "P-001", knee) == "open"
    messages.set_enabled(store, "P-001", False)
    assert inbox.reply_state(store, "P-001", knee) == "off"
    plans.complete(store, ankle.id)
    plans.archive(store, ankle.id)
    assert inbox.reply_state(store, "P-001", store.plan_get(ankle.id)) == "archived"
    store.discharge("P-001")
    assert inbox.reply_state(store, "P-001", store.plan_get(ankle.id)) == "discharged"


def test_send_needs_confirmation_for_identifying_text(world):
    store, _, knee, _, _, _ = world
    with pytest.raises(messages.NeedsConfirmation) as warned:
        inbox.send(store, "P-001", knee, "Call me on 615 555 0142", confirm=False)
    assert "phone number" in warned.value.reasons
    sent = inbox.send(store, "P-001", knee, "Call me on 615 555 0142", confirm=True, from_draft=True)
    assert sent.warned and sent.from_draft and sent.plan_id == knee.id


def test_labels():
    now = datetime(2026, 11, 12, 10, 0)
    assert inbox.when_label("2026-11-12T08:40:00", now) == "8:40"
    assert inbox.when_label("2026-11-11T17:05:00", now) == "Yesterday"
    assert inbox.when_label("2026-11-09T09:00:00", now) == "Mon"
    assert inbox.when_label("2026-10-01T09:00:00", now) == "1 Oct"
    assert inbox.day_label("2026-11-12T08:40:00", now) == "Today"
    assert inbox.day_label("2026-11-03T08:40:00", now) == "Tue 3 Nov"


class Job:
    def __init__(self, state, text=None, removed=False, warned=False, reason=None):
        self.state, self.text, self.removed, self.warned, self.reason = state, text, removed, warned, reason


def test_voice_note_states():
    assert inbox.voice_state(None, False)[1] is None and "not available" in inbox.voice_state(None, False)[0]
    assert "still being done" in inbox.voice_state(Job("queued"), True)[0]
    assert "did not work (decode)" in inbox.voice_state(Job("failed", reason="decode"), True)[0]
    assert inbox.voice_state(Job("done", "x", removed=True), True) == ("Written out automatically: the text was removed.", None)
    note, text = inbox.voice_state(Job("done", "It hurts at six", warned=True), True)
    assert text == "It hurts at six" and "may contain mistakes" in note and "identifying" in note
    assert inbox.voice_state(Job("done", ""), True)[1] == "Nothing recognisable was said."
