"""Feature 018 slice A: the therapist assistant. Every test uses the fake client; none touches the network."""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.assist import assistant, client as aclient, config, extract, redflags
from src.portal import accounts, messages
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore
from tests.conftest import REPO_ROOT

NOW = datetime(2026, 3, 23, 9, 15, 0)


def _summary_json(ids):
    return json.dumps({
        "sections": [
            {"heading": "Adherence", "text": "Logged on 2 of 7 days.", "record_ids": [ids[0]]},
            {"heading": "Pain trend", "text": "Pain rose from 3 to 6.", "record_ids": list(ids[:2])},
            {"heading": "Questions asked", "text": "Asked about stairs.", "record_ids": ["Z-999"]},   # not in the extract
        ],
        "next_steps": [
            {"text": "Look at the swelling at the next visit.", "record_ids": [ids[-1]]},
            {"text": "Unsupported idea.", "record_ids": []},
            {"text": "Ask about missed days.", "record_ids": [ids[0]]},
            {"text": "Check range of motion.", "record_ids": [ids[0]]},
            {"text": "A fourth step.", "record_ids": [ids[0]]},
        ],
    })


def _reply(text, stop="end_turn", inp=1200, out=300):
    return aclient.Reply(text=text, stop_reason=stop, model=assistant.MODEL, input_tokens=inp, output_tokens=out)


@pytest.fixture
def store(tmp_db, fake_clock):
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-021", label="Jane's knee", notes="Lives on Elm Street")
        messages.set_enabled(s, "P-021", True)
        assistant.set_switch(s, "P-021", "summaries", True)
        yield s


def _week_of_records(s, fake_clock):
    """A check-in at pain 3, then at pain 6 three days later, and a patient message."""
    fake_clock._now = NOW - timedelta(days=4)
    s.entry_add("P-021", "checkin", {"pain": 3, "note": "Stairs ok"}, 3, (NOW - timedelta(days=4)).isoformat(),
                "c-1", "standalone", None, False, False)
    fake_clock._now = NOW - timedelta(days=1)
    s.entry_add("P-021", "checkin", {"pain": 6, "note": "Knee felt tight"}, 6, (NOW - timedelta(days=1)).isoformat(),
                "c-2", "standalone", None, False, False)
    messages.send(s, "P-021", "patient", "Harder on Thursday, knee felt tight.")
    fake_clock._now = NOW


class TestBoundary:
    def test_only_src_assist_imports_the_sdk(self):
        offenders = []
        for path in REPO_ROOT.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith((".venv/", "venv/")) or "/site-packages/" in rel or rel.startswith("tests/"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"^\s*(import anthropic|from anthropic\b)", text, re.M) and not rel.startswith("src/assist/"):
                offenders.append(rel)
        assert offenders == []

    def test_the_dependency_is_declared(self):
        assert re.search(r"^anthropic>=", (REPO_ROOT / "requirements.txt").read_text(), re.M)


class TestKey:
    def test_no_key_means_off(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "shell-token-that-must-be-ignored")
        assert config.api_key() is None and not config.available()
        assert config.status_line() == "AI assistant: off (no key)"

    def test_from_the_environment(self, monkeypatch):
        monkeypatch.setenv(config.KEY_ENV, "sk-test-env")
        assert config.api_key() == "sk-test-env" and config.available()
        assert config.status_line() == "AI assistant: on"

    def test_from_the_env_file(self, monkeypatch, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# comment\nOTHER=1\nLIMBER_ANTHROPIC_API_KEY=sk-test-file\n")
        monkeypatch.setenv(config.ENV_FILE_ENV, str(env))
        assert config.api_key() == "sk-test-file"

    def test_the_key_never_reaches_the_status_or_the_log(self, monkeypatch, store, fake_clock):
        monkeypatch.setenv(config.KEY_ENV, "sk-secret-value")
        _week_of_records(store, fake_clock)
        assistant.weekly_summary(store, "P-021", client=aclient.FakeClient([_reply("not json")]))
        dump = json.dumps([dict(r) for r in store.conn.execute("SELECT * FROM assist_calls")])
        assert "sk-secret-value" not in dump and "sk-secret-value" not in config.status_line()


class TestSchema:
    def test_v16_tables_and_defaults(self, tmp_db):
        with SessionStore(tmp_db).open() as s:
            tables = {r[0] for r in s.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert SCHEMA_VERSION >= 16 and [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION
            assert {"assist_switches", "assist_calls", "therapist_notes", "message_handled"} <= tables
            assert "from_draft" in {r[1] for r in s.conn.execute("PRAGMA table_info(messages)")}
            s.add_patient("P-030")
            assert assistant.switches(s, "P-030") == {"summaries": False, "coach": False}

    def test_switches_go_with_the_patient(self, store):
        assistant.set_switch(store, "P-021", "coach", True)
        assert assistant.switches(store, "P-021") == {"summaries": True, "coach": True}
        store.assist_call_add("P-021", None, "summary", assistant.MODEL, 10, 5, "ok")
        assistant.save_note(store, "P-021", "A note.", ai_drafted=True, account_id=None)
        store.delete_patient("P-021")
        for table in ("assist_switches", "assist_calls", "therapist_notes"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table

    def test_an_unknown_switch_is_refused(self, store):
        with pytest.raises(ValueError):
            assistant.set_switch(store, "P-021", "everything", True)


class TestRedFlags:
    @pytest.mark.parametrize("text", [
        "I have chest pain when I walk", "My left foot feels numb", "I had a fall this morning", "I fell on the stairs",
        "my calf is swollen and hot", "Short of breath after the exercises", "I fainted", "numbness in my toes",
        "There is blood in my cough", "I can't feel my leg"])
    def test_flags(self, text):
        assert redflags.screen(text)

    @pytest.mark.parametrize("text", [
        "Harder on Thursday, knee felt tight.", "How far should I bend in heel slides?", "I fall asleep easily now",
        "Thanks, see you Tuesday", ""])
    def test_does_not_flag(self, text):
        assert redflags.screen(text) == []

    def test_the_words_found_are_what_the_patient_wrote(self):
        assert sorted(redflags.found_words("I had a Fall and now my foot is numb")) == ["had a fall", "numb"]

    def test_the_list_lives_in_the_repository(self):
        path = REPO_ROOT / "src" / "assist" / "red_flags.txt"
        assert path.is_file() and len([l for l in path.read_text().splitlines() if l and not l.startswith("#")]) >= 15


class TestExtract:
    def test_seven_days_with_record_ids(self, store, fake_clock):
        fake_clock._now = NOW - timedelta(days=12)
        store.entry_add("P-021", "checkin", {"pain": 2, "note": "old"}, 2, (NOW - timedelta(days=12)).isoformat(),
                        "c-0", "standalone", None, False, False)
        fake_clock._now = NOW
        _week_of_records(store, fake_clock)
        ex = extract.build(store, "P-021")
        kinds = [r["type"] for r in ex.data["records"]]
        assert kinds.count("checkin") == 2 and "message" in kinds
        assert all(r["id"] in ex.ids for r in ex.data["records"])
        assert "old" not in json.dumps(ex.data)
        assert ex.data["patient"] == "P-021" and not ex.empty

    def test_empty_week(self, store):
        assert extract.build(store, "P-021").empty

    def test_never_the_label_notes_or_diagnosis(self, store, fake_clock):
        plan = store.plans("P-021")[0]
        store.plan_update(plan.id, diagnosis="ACL tear, left knee")
        _week_of_records(store, fake_clock)
        dump = json.dumps(extract.build(store, "P-021").data)
        assert "Jane" not in dump and "Elm Street" not in dump and "ACL" not in dump


class TestNoAccountFieldsInRequests:
    def test_no_account_field_in_any_request_body(self, store, fake_clock):
        boss = accounts.create_account(store, username="zelda.admin", display_name="Zelda Quartermaine",
                                       password="correct horse battery", role="admin")
        accounts.create_account(store, username="sam.p021", display_name="Samuel Whitfield",
                                password="correct horse battery", role="patient", patient_id="P-021")
        _week_of_records(store, fake_clock)
        fake = aclient.FakeClient([_reply(_summary_json(["E-1", "E-2"])), _reply("Thanks for letting me know.")])
        assistant.weekly_summary(store, "P-021", account_id=boss.id, client=fake)
        assistant.draft_reply(store, "P-021", account_id=boss.id, client=fake)
        assert len(fake.bodies) == 2
        dump = json.dumps(fake.bodies)
        for forbidden in ("zelda", "Zelda", "Quartermaine", "sam.p021", "Samuel", "Whitfield", "password", "salt"):
            assert forbidden not in dump


class TestRequestShape:
    def test_model_thinking_fallbacks_and_cache_order(self, store, fake_clock):
        _week_of_records(store, fake_clock)
        fake = aclient.FakeClient([_reply(_summary_json(["E-1"]))])
        assistant.weekly_summary(store, "P-021", client=fake)
        body = fake.bodies[0]
        assert body["model"] == "claude-opus-5-5"
        assert body["thinking"] == {"type": "adaptive"} and body["output_config"]["effort"] in ("low", "medium", "high")
        assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in body["betas"]
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
        first = body["messages"][0]["content"][0]
        assert first.get("cache_control") == {"type": "ephemeral"} and '"patient": "P-021"' in first["text"]
        assert body["output_config"]["format"]["type"] == "json_schema"


class TestWeeklySummary:
    def test_claims_need_records(self, store, fake_clock):
        _week_of_records(store, fake_clock)
        ids = sorted(extract.build(store, "P-021").ids)
        result = assistant.weekly_summary(store, "P-021", client=aclient.FakeClient([_reply(_summary_json(ids))]))
        assert result.state == "ok"
        headings = [s.heading for s in result.sections]
        assert headings == ["Adherence", "Pain trend"]                    # the uncited claim is dropped
        assert len(result.next_steps) == 3 and all(n.record_ids for n in result.next_steps)
        assert result.dropped == 3                                           # 1 section + 2 steps (one empty, one past 3)

    def test_no_records_means_no_call(self, store):
        fake = aclient.FakeClient([])
        result = assistant.weekly_summary(store, "P-021", client=fake)
        assert result.state == "no_records" and fake.bodies == []

    def test_switch_off_means_no_call(self, store, fake_clock):
        _week_of_records(store, fake_clock)
        assistant.set_switch(store, "P-021", "summaries", False)
        fake = aclient.FakeClient([])
        assert assistant.weekly_summary(store, "P-021", client=fake).state == "off" and fake.bodies == []

    def test_as_note_text(self, store, fake_clock):
        _week_of_records(store, fake_clock)
        ids = sorted(extract.build(store, "P-021").ids)
        result = assistant.weekly_summary(store, "P-021", client=aclient.FakeClient([_reply(_summary_json(ids))]))
        text = result.as_text()
        assert "Pain rose from 3 to 6." in text and "Suggested next steps" in text


class TestUnavailable:
    @pytest.mark.parametrize("reply", [_reply("{}", stop="refusal"), _reply('{"sections": [', stop="max_tokens"),
                                       _reply("not json at all")])
    def test_never_partial(self, store, fake_clock, reply):
        _week_of_records(store, fake_clock)
        result = assistant.weekly_summary(store, "P-021", client=aclient.FakeClient([reply]))
        assert result.state == "unavailable" and result.sections == []

    def test_api_error(self, store, fake_clock):
        _week_of_records(store, fake_clock)
        fake = aclient.FakeClient([aclient.AssistUnavailable("overloaded")])
        assert assistant.weekly_summary(store, "P-021", client=fake).state == "unavailable"
        assert assistant.draft_reply(store, "P-021", client=aclient.FakeClient([aclient.AssistUnavailable("x")])).state \
            == "unavailable"


class TestCallLog:
    def test_every_call_is_logged_without_content(self, store, fake_clock):
        _week_of_records(store, fake_clock)
        ids = sorted(extract.build(store, "P-021").ids)
        assistant.weekly_summary(store, "P-021", client=aclient.FakeClient([_reply(_summary_json(ids), inp=1500, out=420)]))
        assistant.weekly_summary(store, "P-021", client=aclient.FakeClient([_reply("x", stop="refusal")]))
        rows = [dict(r) for r in store.conn.execute("SELECT * FROM assist_calls ORDER BY id")]
        assert [(r["patient_id"], r["purpose"], r["model"], r["outcome"]) for r in rows] == [
            ("P-021", "summary", "claude-opus-5-5", "ok"), ("P-021", "summary", "claude-opus-5-5", "refusal")]
        assert (rows[0]["input_tokens"], rows[0]["output_tokens"]) == (1500, 420)
        assert set(rows[0]) == {"id", "at", "patient_id", "account_id", "purpose", "model", "input_tokens",
                                "output_tokens", "outcome"}


class TestDailyCap:
    def test_cap_per_therapist(self, store, fake_clock):
        _week_of_records(store, fake_clock)
        assistant.set_daily_cap(store, 2)
        ids = sorted(extract.build(store, "P-021").ids)
        fake = aclient.FakeClient([_reply(_summary_json(ids))] * 3)
        states = [assistant.weekly_summary(store, "P-021", account_id=7, client=fake).state for _ in range(3)]
        assert states == ["ok", "ok", "cap"] and len(fake.bodies) == 2
        assert assistant.weekly_summary(store, "P-021", account_id=8,
                                        client=aclient.FakeClient([_reply(_summary_json(ids))])).state == "ok"
        fake_clock.advance(86400)
        assert assistant.weekly_summary(store, "P-021", account_id=7,
                                        client=aclient.FakeClient([_reply(_summary_json(ids))])).state != "cap"

    def test_default_is_fifty(self, store):
        assert assistant.daily_cap(store) == 50


class TestNotes:
    def test_saved_with_the_marker(self, store):
        note = assistant.save_note(store, "P-021", "Pain rose this week.", ai_drafted=True, account_id=None)
        assert note["ai_drafted"] and assistant.notes(store, "P-021")[0]["body"] == "Pain rose this week."
        with pytest.raises(ValueError):
            assistant.save_note(store, "P-021", "   ", ai_drafted=True, account_id=None)


class TestDraftReply:
    def test_a_draft_is_never_sent(self, store, fake_clock):
        _week_of_records(store, fake_clock)
        before = len(store.message_thread("P-021"))
        result = assistant.draft_reply(store, "P-021", client=aclient.FakeClient([_reply("Thanks for telling me.")]))
        assert result.state == "ok" and result.text == "Thanks for telling me."
        assert len(store.message_thread("P-021")) == before

    def test_withheld_on_a_red_flag_without_calling(self, store):
        messages.send(store, "P-021", "patient", "I had a fall this morning getting out of bed.")
        messages.send(store, "P-021", "patient", "Now my left foot feels numb.")
        fake = aclient.FakeClient([])
        result = assistant.draft_reply(store, "P-021", client=fake)
        assert result.state == "withheld" and fake.bodies == [] and result.flags

    def test_an_answered_red_flag_does_not_block_later_drafts(self, store):
        messages.send(store, "P-021", "patient", "I had a fall this morning.")
        messages.send(store, "P-021", "therapist", "Call the clinic now please.")
        messages.send(store, "P-021", "patient", "Done, all fine. How many heel slides today?")
        result = assistant.draft_reply(store, "P-021", client=aclient.FakeClient([_reply("Ten, as before.")]))
        assert result.state == "ok"

    def test_sent_message_records_the_draft(self, store):
        m = messages.send(store, "P-021", "therapist", "Ten, as before.", from_draft=True)
        assert store.message_thread("P-021")[-1].from_draft and m.from_draft
        assert not messages.send(store, "P-021", "therapist", "Typed myself.").from_draft

    def test_the_draft_request_holds_the_conversation(self, store):
        messages.send(store, "P-021", "patient", "How did the stairs go? They were fine.")
        fake = aclient.FakeClient([_reply("Glad to hear it.")])
        assistant.draft_reply(store, "P-021", client=fake)
        assert "They were fine." in json.dumps(fake.bodies[0])
        assert fake.bodies[0]["model"] == "claude-opus-5-5"


class TestHandledByPhone:
    def test_clears_the_attention_flag_and_is_recorded(self, store):
        m = messages.send(store, "P-021", "patient", "I had a fall this morning.")
        assert [x.id for x in assistant.needs_attention(store, "P-021")] == [m.id]
        assistant.mark_handled(store, m.id, account_id=None)
        assert assistant.needs_attention(store, "P-021") == []
        assert store.conn.execute("SELECT how FROM message_handled WHERE message_id = ?", (m.id,)).fetchone()[0] == "phone"
        assert assistant.draft_reply(store, "P-021", client=aclient.FakeClient([_reply("ok")])).state == "ok"


class TestPreflight:
    def test_reported_as_optional(self, tmp_db, tmp_path):
        from src.deploy import preflight
        checks = preflight.run(tmp_db, tmp_path, "https://limber.example.org", "https://limber.example.org/therapist")
        (ai,) = [c for c in checks if c.name == "ai_assistant"]
        assert ai.optional and not ai.ok and ai.detail.startswith("AI assistant: off (no key)")
