"""Feature 018 slice A in the therapist app (T010): the weekly summary panel, draft replies and the withheld
notice in the inbox, and the AI settings. Streamlit AppTest with the fake client; no network."""

import json

import pytest
from streamlit.testing.v1 import AppTest

from src.assist import assistant, client as aclient, extract
from src.portal import messages
from src.ptlog.store import SessionStore
from tests.test_app_pages import APP, seeded_env  # noqa: F401  (fixture)


def _app(page, **state):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = page
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def _text(at):
    return " ".join([x.value for x in at.text] + [x.value for x in at.markdown] + [c.value for c in at.caption] +
                    [w.value for w in at.warning] + [i.value for i in at.info] + [e.value for e in at.error] +
                    [s.value for s in at.success])


def _buttons(at):
    return {b.key for b in at.button}


@pytest.fixture
def ai_on(monkeypatch, seeded_env):  # noqa: F811
    """A key is configured, P-017 has summaries switched on, and every call goes to a fake client."""
    monkeypatch.setenv("LIMBER_ANTHROPIC_API_KEY", "sk-test-not-real")
    with SessionStore(seeded_env).open() as s:
        messages.set_enabled(s, "P-017", True)
        assistant.set_switch(s, "P-017", "summaries", True)
    fake = aclient.FakeClient([])
    monkeypatch.setattr(aclient, "make_client", lambda: fake)
    return seeded_env, fake


def _summary_reply(db):
    with SessionStore(db).open() as s:
        ids = sorted(extract.build(s, "P-017").ids)
    text = json.dumps({"sections": [{"heading": "Adherence", "text": "Two sessions logged this week.", "record_ids": ids}],
                       "next_steps": [{"text": "Check knee range at the next visit.", "record_ids": ids[:1]}]})
    return aclient.Reply(text=text, stop_reason="end_turn", model=assistant.MODEL, input_tokens=900, output_tokens=120)


class TestNoKey:
    def test_no_ai_control_anywhere(self, seeded_env):  # noqa: F811
        with SessionStore(seeded_env).open() as s:
            messages.set_enabled(s, "P-017", True)
            assistant.set_switch(s, "P-017", "summaries", True)
            messages.send(s, "P-017", "patient", "How many heel slides today?")
        for page, state in (("patients", {}), ("inbox", {"inbox_open": "P-017"})):
            at = _app(page, **state)
            assert not at.exception, [e.value for e in at.exception]
            shown = _text(at)
            assert "Weekly summary" not in shown and "AI settings" not in shown and "AI-drafted" not in shown
            assert not {k for k in _buttons(at) if k and ("assist" in k or "draft" in k)}
            assert not [t for t in at.toggle if t.key and t.key.startswith("assist_")]


class TestSummaryPanel:
    def test_summarise_save_and_the_marker(self, ai_on):
        db, fake = ai_on
        fake.script.append(_summary_reply(db))
        at = _app("patients", patients_edit_select="P-017")
        assert not at.exception, [e.value for e in at.exception]
        assert "Summarise the last 7 days" in [b.label for b in at.button]
        at.button(key="assist_summarise_P-017").click().run()
        assert not at.exception, [e.value for e in at.exception]
        shown = _text(at)
        assert "AI-drafted — check before acting" in shown and "Two sessions logged this week." in shown
        assert "P-017 never sees this summary." in shown
        at.button(key="assist_save_P-017").click().run()
        assert "Saved as a session note" in _text(at)
        with SessionStore(db).open() as s:
            (note,) = assistant.notes(s, "P-017")
            assert note["ai_drafted"] and "Two sessions logged this week." in note["body"]

    def test_unavailable(self, ai_on):
        db, fake = ai_on
        fake.script.append(aclient.AssistUnavailable("overloaded"))
        at = _app("patients", patients_edit_select="P-017")
        at.button(key="assist_summarise_P-017").click().run()
        assert "The assistant isn't available right now" in _text(at)

    def test_no_records(self, ai_on, monkeypatch):
        db, fake = ai_on
        with SessionStore(db).open() as s:
            s.add_patient("P-090")
            assistant.set_switch(s, "P-090", "summaries", True)
        at = _app("patients", patients_edit_select="P-090")
        at.button(key="assist_summarise_P-090").click().run()
        assert "No records this week" in _text(at) and fake.bodies == []


class TestAISettings:
    def test_switches_default_off_and_turn_on(self, ai_on):
        db, _ = ai_on
        with SessionStore(db).open() as s:
            s.add_patient("P-091")
        at = _app("patients", patients_edit_select="P-091")
        assert not at.exception, [e.value for e in at.exception]
        assert "Both are off for every new patient" in _text(at)
        toggle = at.toggle(key="assist_sw_summaries_P-091")
        assert toggle.value is False and at.toggle(key="assist_sw_coach_P-091").value is False
        toggle.set_value(True).run()
        with SessionStore(db).open() as s:
            assert assistant.switches(s, "P-091") == {"summaries": True, "coach": False}
        assert "Anthropic" in _text(at)                                   # the notice the patient is shown


class TestDraftReply:
    def test_the_draft_fills_the_box_and_is_marked(self, ai_on):
        db, fake = ai_on
        with SessionStore(db).open() as s:
            messages.send(s, "P-017", "patient", "How many heel slides today?")
        fake.script.append(aclient.Reply(text="Ten, the same as last week.", stop_reason="end_turn",
                                         model=assistant.MODEL, input_tokens=500, output_tokens=40))
        at = _app("inbox", inbox_open="P-017")
        assert not at.exception, [e.value for e in at.exception]
        at.button(key="inbox_draft").click().run()
        assert at.text_area(key="inbox_reply").value == "Ten, the same as last week."
        assert "AI-drafted — check before sending" in _text(at)
        with SessionStore(db).open() as s:
            assert s.message_thread("P-017")[-1].sender == "patient"         # nothing sent
        at.button(key="inbox_send").click().run()
        with SessionStore(db).open() as s:
            last = s.message_thread("P-017")[-1]
            assert (last.sender, last.body, last.from_draft) == ("therapist", "Ten, the same as last week.", True)

    def test_a_draft_never_follows_to_another_conversation(self, ai_on):
        db, fake = ai_on
        with SessionStore(db).open() as s:
            s.add_patient("P-092")
            messages.set_enabled(s, "P-092", True)
            messages.send(s, "P-017", "patient", "How many heel slides today?")
        fake.script.append(aclient.Reply(text="Ten, the same as last week.", stop_reason="end_turn",
                                         model=assistant.MODEL, input_tokens=500, output_tokens=40))
        at = _app("inbox", inbox_open="P-017")
        at.button(key="inbox_draft").click().run()
        at.selectbox(key="inbox_open").set_value("P-092").run()
        assert not at.exception, [e.value for e in at.exception]
        assert at.text_area(key="inbox_reply").value == "" and "AI-drafted" not in _text(at)

    def test_withheld_and_handled_by_phone(self, ai_on):
        db, fake = ai_on
        with SessionStore(db).open() as s:
            m = messages.send(s, "P-017", "patient", "I had a fall this morning getting out of bed.")
        at = _app("inbox", inbox_open="P-017")
        assert not at.exception, [e.value for e in at.exception]
        assert "This message may need a direct response" in _text(at) and "mentioned “had a fall”" in _text(at)
        assert at.button(key="inbox_draft").disabled
        at.button(key="inbox_handled").click().run()
        assert "This message may need a direct response" not in _text(at)
        with SessionStore(db).open() as s:
            assert s.messages_handled([m.id]) == {m.id}
        assert fake.bodies == []
