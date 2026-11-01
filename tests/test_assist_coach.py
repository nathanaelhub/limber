"""Feature 018 slice B: the patient exercise coach (US3). Every test uses the fake client; none touches the network."""

import json
from datetime import date, datetime

import pytest

from src.assist import assistant, client as aclient, coach
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore

NOW = datetime(2026, 3, 23, 9, 15, 0)


def _reply(kind="answer", exercise="Knee Extension", answer="Knee Extension: 12 reps. Straighten your knee fully.",
           stop="end_turn", inp=900, out=120):
    text = json.dumps({"kind": kind, "exercise": exercise, "answer": answer})
    return aclient.Reply(text=text, stop_reason=stop, model=coach.MODEL, input_tokens=inp, output_tokens=out)


@pytest.fixture
def store(tmp_db, fake_clock):
    fake_clock._now = NOW
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-021", label="Jane's knee", notes="Lives on Elm Street")
        s.add_patient("P-030", label="Someone else")
        s.assign_program("P-021", "custom", "Knee Home Program", ["knee_extension", "squat"], 3,
                         start_date=date(2026, 3, 1))
        s.set_goal("P-021", "Knee Extension", target_rom=165, target_reps=12)
        s.assign_program("P-030", "custom", "Shoulder", ["shoulder_flexion"], 2, start_date=date(2026, 3, 1))
        assistant.set_switch(s, "P-021", "coach", True)
        yield s


def _fake(*replies):
    return aclient.FakeClient(list(replies))


class TestSchema:
    def test_v17_coach_turns(self, tmp_db):
        with SessionStore(tmp_db).open() as s:
            assert SCHEMA_VERSION >= 17 and [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION
            cols = {r[1] for r in s.conn.execute("PRAGMA table_info(coach_turns)")}
            assert {"patient_id", "plan_id", "asked_at", "question", "kind", "answer", "exercise", "called"} <= cols

    def test_turns_go_with_the_patient(self, store):
        coach.ask(store, "P-021", "My calf is swollen and hot")
        store.delete_patient("P-021")
        assert store.conn.execute("SELECT COUNT(*) FROM coach_turns").fetchone()[0] == 0


class TestAnswers:
    """US3 scenario 1: an answer uses only that exercise's prescribed dose and instructions."""

    def test_an_answer_names_the_exercise_and_dose(self, store):
        fake = _fake(_reply())
        r = coach.ask(store, "P-021", "How many knee extensions should I do?", client=fake)
        assert (r.kind, r.exercise, r.ai) == ("answer", "Knee Extension", True)
        assert r.text.startswith("Knee Extension: 12 reps")

    def test_the_request_holds_only_this_patients_program(self, store):
        fake = _fake(_reply())
        coach.ask(store, "P-021", "How many knee extensions should I do?", client=fake)
        body = fake.bodies[0]
        sent = json.dumps(body)
        assert body["model"] == "claude-sonnet-5-5" and body["thinking"] == {"type": "adaptive"}
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
        program = json.loads(body["messages"][0]["content"][0]["text"])
        assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert program["patient"] == "P-021" and [e["name"] for e in program["exercises"]] == ["Knee Extension", "Squat"]
        assert program["exercises"][0]["reps"] == 12 and program["exercises"][0]["range_of_motion_target_degrees"] == 165
        assert "instructions" in program["exercises"][0]
        for never in ("Jane", "Elm Street", "Shoulder", "P-030"):
            assert never not in sent
        assert body["output_config"]["format"]["schema"]["properties"]["exercise"]["enum"] == ["Knee Extension", "Squat", ""]

    def test_a_number_not_in_the_program_becomes_the_referral(self, store):
        """Edge case: the model's dose contradicts the program, so the host replaces the answer."""
        fake = _fake(_reply(answer="Knee Extension: 3 sets of 20 reps."))
        r = coach.ask(store, "P-021", "How many knee extensions?", client=fake)
        assert (r.kind, r.ai) == ("referral", False) and r.text == coach.REFERRAL_TEXT
        assert store.coach_turns("P-021")[-1]["answer"] is None

    def test_numbers_from_the_question_are_allowed(self, store):
        assert coach.numbers_match("Yes, 12 reps, twice is fine on 2 days.", coach.program_extract(store, "P-021"),
                                   "Can I do 12 reps on 2 days?")

    def test_an_exercise_outside_the_program_is_not_an_answer(self, store):
        fake = _fake(_reply(exercise="Shoulder Flexion", answer="Shoulder Flexion: 10 reps."))
        assert coach.ask(store, "P-021", "How about shoulder flexion?", client=fake).kind != "answer"


class TestReferralAndRefusal:
    def test_more_reps_than_prescribed_goes_to_the_therapist(self, store):
        """US3 scenario 2: the model classifies; the patient sees set clinic text, not model text."""
        fake = _fake(_reply(kind="referral", exercise="", answer=""))
        r = coach.ask(store, "P-021", "Can I do more reps than prescribed?", client=fake)
        assert (r.kind, r.text, r.ai) == ("referral", coach.REFERRAL_TEXT, False)

    def test_off_topic_is_refused_with_set_text(self, store):
        fake = _fake(_reply(kind="refusal", exercise="", answer="ignored"))
        r = coach.ask(store, "P-021", "What's a good pizza place?", client=fake)
        assert (r.kind, r.text) == ("refusal", coach.REFUSAL_TEXT)


class TestEmergency:
    @pytest.mark.parametrize("q", ["My calf is swollen and hot", "I had a fall", "I have chest pain",
                                   "The back of my leg below the knee is really puffy, red and warm to touch.",
                                   "I can't catch my breath when I climb the stairs since yesterday."])
    def test_red_flags_never_call_the_model(self, store, q):
        """US3 scenario 3: the emergency message, and the model is not called."""
        fake = _fake()
        r = coach.ask(store, "P-021", q, client=fake)
        assert (r.kind, r.text, r.ai) == ("emergency", coach.EMERGENCY_TEXT, False) and fake.bodies == []
        assert store.conn.execute("SELECT COUNT(*) FROM assist_calls").fetchone()[0] == 0

    def test_even_when_the_coach_is_off_or_capped(self, store):
        assistant.set_switch(store, "P-021", "coach", False)
        assert coach.ask(store, "P-021", "my calf is hot and swollen", client=_fake()).kind == "emergency"


class TestOffAndLimits:
    def test_switched_off_mid_conversation(self, store):
        """US3 scenario 5."""
        coach.ask(store, "P-021", "How many knee extensions?", client=_fake(_reply()))
        assistant.set_switch(store, "P-021", "coach", False)
        fake = _fake()
        r = coach.ask(store, "P-021", "And squats?", client=fake)
        assert (r.kind, r.text) == ("off", "The coach is turned off — message your therapist instead.")
        assert fake.bodies == []

    def test_twenty_a_day_then_message_your_therapist(self, store, fake_clock):
        """Edge case: after 20 questions in a day the coach asks them to message their therapist."""
        assert coach.daily_cap(store) == 20
        store.set_clinic_setting(coach.CAP_SETTING, "2")
        coach.ask(store, "P-021", "How many knee extensions?", client=_fake(_reply()))
        coach.ask(store, "P-021", "Again?", client=_fake(_reply()))
        fake = _fake()
        assert coach.ask(store, "P-021", "Once more?", client=fake).kind == "limit" and fake.bodies == []
        fake_clock._now = datetime(2026, 3, 24, 8, 0)
        assert coach.questions_left_today(store, "P-021") == 2

    def test_coach_calls_do_not_use_the_therapists_cap(self, store):
        coach.ask(store, "P-021", "How many knee extensions?", client=_fake(_reply()))
        assert assistant.calls_left_today(store, None) == assistant.DEFAULT_DAILY_CAP

    def test_no_program(self, store):
        store.add_patient("P-040")
        assistant.set_switch(store, "P-040", "coach", True)
        fake = _fake()
        assert coach.ask(store, "P-040", "What do I do?", client=fake).kind == "no_program" and fake.bodies == []

    @pytest.mark.parametrize("q", ["", "   ", "x" * 501])
    def test_empty_or_long_questions_are_refused(self, store, q):
        with pytest.raises(ValueError):
            coach.ask(store, "P-021", q, client=_fake())


class TestUnavailable:
    @pytest.mark.parametrize("reply", [_reply(stop="refusal"), _reply(stop="max_tokens"),
                                       aclient.Reply("not json", "end_turn", coach.MODEL),
                                       aclient.Reply(json.dumps({"kind": "maybe"}), "end_turn", coach.MODEL)])
    def test_never_partial(self, store, reply):
        r = coach.ask(store, "P-021", "How many knee extensions?", client=_fake(reply))
        assert (r.kind, r.text) == ("unavailable", coach.UNAVAILABLE_TEXT)

    def test_api_error(self, store):
        r = coach.ask(store, "P-021", "How many knee extensions?", client=_fake(aclient.AssistUnavailable("network")))
        assert r.kind == "unavailable"
        assert store.conn.execute("SELECT outcome FROM assist_calls").fetchone()[0] == "network"


class TestTherapistCanRead:
    def test_every_turn_is_kept_and_the_log_has_no_content(self, store, fake_clock):
        """US3 scenario 4, and FR-007 for the coach."""
        coach.ask(store, "P-021", "How many knee extensions?", client=_fake(_reply(inp=950, out=80)))
        coach.ask(store, "P-021", "My calf is swollen and hot")
        fake_clock._now = datetime(2026, 3, 24, 8, 0)
        coach.ask(store, "P-021", "Can I add lunges?", client=_fake(_reply(kind="referral", exercise="", answer="")))
        days = coach.conversations(store, "P-021")
        assert [d["day"] for d in days] == ["2026-03-24", "2026-03-23"]
        assert [t["kind"] for t in days[1]["turns"]] == ["answer", "emergency"]
        assert days[1]["turns"][0]["question"] == "How many knee extensions?"
        call = dict(store.conn.execute("SELECT * FROM assist_calls ORDER BY id").fetchone())
        assert (call["purpose"], call["model"], call["input_tokens"], call["output_tokens"]) == \
            ("coach", "claude-sonnet-5-5", 950, 80)
        assert "knee" not in json.dumps(call).lower()


class TestPlan:
    def test_the_plan_is_the_one_the_program_belongs_to(self, store):
        """A newer plan without a program does not take the coach's heading (feature 017)."""
        knee = coach.program_plan(store, "P-021")
        store.plan_add("P-021", title="Left shoulder")
        assert coach.program_plan(store, "P-021").id == knee.id
        assert coach.program_extract(store, "P-021")["plan"] == knee.title
