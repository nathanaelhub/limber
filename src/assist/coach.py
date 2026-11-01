"""
The patient exercise coach (feature 018, slice B, US3): questions answered from the patient's own program.

Rules that live here rather than in the prompt, because a prompt is advice and these are guarantees:
- red-flag words get the emergency card, before anything else and without calling the model;
- nothing is sent unless the patient's coach switch is on;
- a patient has a daily question cap (a clinic setting, default 20);
- the request holds only the signed-in patient's program, under their pseudonymous ID;
- the model only classifies and answers; the referral and "only your program" replies are set clinic text;
- an answer must name an exercise in the program, and every number in it must come from the program or the
  question, or the patient gets the referral instead;
- a refusal, a cut-off, an API error, or output that does not parse is "unavailable", never partial;
- every question and what the patient was shown is kept on the host for the therapist to read, and each call
  is logged with its size, never its content.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from src.assist import assistant, client as aclient, redflags
from src.ptlog.store import SessionStore

MODEL = "claude-sonnet-5-5"
EFFORT = "low"
MAX_TOKENS = 4000
MAX_QUESTION = 500
DEFAULT_DAILY_CAP = 20
CAP_SETTING = "coach_daily_cap"

# Set clinic text. Each one is shown as it is, never written by the model.
EMERGENCY_TEXT = ("Please get help now. What you described can be serious. It needs a doctor today, not at your next "
                  "visit. Call 911 or go to the nearest emergency room.")
REFERRAL_TEXT = ("That's one for your therapist. Questions about pain getting worse, new symptoms, medicine or "
                 "changing your program need your therapist. The coach can't answer them.")
REFUSAL_TEXT = "I can only answer questions about your exercise program. For anything else, message your therapist."
OFF_TEXT = "The coach is turned off — message your therapist instead."
LIMIT_TEXT = ("You've reached today's question limit. You can ask the coach again tomorrow. For anything sooner, "
              "message your therapist.")
NO_PROGRAM_TEXT = "Your therapist hasn't added exercises yet, so the coach has nothing to answer from."
UNAVAILABLE_TEXT = "The coach isn't available right now. Try again later, or message your therapist."
ER_SEARCH_URL = "https://www.google.com/maps/search/?api=1&query=emergency+room+near+me"

SET_TEXT = {"emergency": EMERGENCY_TEXT, "referral": REFERRAL_TEXT, "refusal": REFUSAL_TEXT, "off": OFF_TEXT,
            "limit": LIMIT_TEXT, "no_program": NO_PROGRAM_TEXT, "unavailable": UNAVAILABLE_TEXT}

SYSTEM = """You are the exercise coach in a physical therapy app. A patient asks about their own home exercise program.

You receive the patient's program as JSON: each exercise's name, its prescribed repetitions, any range-of-motion
target, the clinic's short instructions, and whether it was done today. The patient is identified only by a code.

Decide the kind of reply:
- "answer": the question is about how to do an exercise in the program, its prescribed dose, or which exercises
  are left today. Answer in one to three short, plain sentences. Start with the exercise name and its dose exactly
  as the program states it (for example "Heel slides: 10 reps."). Use only numbers that appear in the program.
  Set "exercise" to the exercise's name exactly as in the program. A gentle reminder to stop and tell their
  therapist if they feel sharp pain is fine.
- "referral": the question is about pain getting worse, new or changed symptoms, medication, doing more or less
  than prescribed, adding, skipping or changing exercises, or anything that needs the therapist's judgement.
  Leave "answer" empty; the app shows a set message that sends them to their therapist.
- "refusal": the question is not about this program (other health topics, other people, general chat). Leave
  "answer" empty; the app shows a set message.

Never diagnose, never give medication advice, never change the program, and never invent a dose, a number of
sets, a hold time, or an instruction the program does not contain. If the program does not say, use "referral".
Never use or guess a name."""


@dataclass
class CoachResult:
    kind: str                          # answer | referral | refusal | emergency | off | limit | no_program | unavailable
    text: str                          # what the patient is shown
    exercise: str = ""                 # the program exercise an answer is about
    turn_id: Optional[int] = None
    asked_at: str = ""
    ai: bool = False                   # True only for model-written answers; everything else is set clinic text


# ----------------------------------------------------------------------------- cap

def daily_cap(store: SessionStore) -> int:
    try:
        return max(0, int(store.clinic_setting(CAP_SETTING, str(DEFAULT_DAILY_CAP))))
    except ValueError:
        return DEFAULT_DAILY_CAP


def questions_left_today(store: SessionStore, patient_id: str) -> int:
    return max(0, daily_cap(store) - store.coach_questions_on(patient_id, store._now()[:10]))


# ----------------------------------------------------------------------------- the program extract

def program_plan(store: SessionStore, patient_id: str):
    """The plan of care the active program belongs to (feature 017), else the patient's current plan."""
    now = datetime.fromisoformat(store._now())
    assignment = store.active_assignment(patient_id, now.date())
    if assignment is not None:
        row = store.conn.execute("SELECT plan_id FROM assignments WHERE id = ?", (assignment.id,)).fetchone()
        plan = store.plan_get(row["plan_id"]) if row and row["plan_id"] is not None else None
        if plan is not None:
            return plan
    return store.current_plan(patient_id)


def program_extract(store: SessionStore, patient_id: str) -> Optional[dict]:
    """The signed-in patient's active program and nothing else: no name, account field, label, notes, diagnosis,
    logs, or messages. None when there is no program to answer from."""
    from src.portal import viewmodels
    now = datetime.fromisoformat(store._now())
    assignment = store.active_assignment(patient_id, now.date())
    if assignment is None:
        return None
    exercises = viewmodels.program_exercises(store, patient_id, now.date())
    if not exercises:
        return None
    from src.ptlog import programs
    catalog = programs.load_catalog()
    done = viewmodels.done_today_keys(store, patient_id, now)
    items = []
    for e in exercises:
        item = {"name": e["name"], "reps": e["target_reps"], "done_today": e["key"] in done}
        goal = store.get_goal(patient_id, e["name"])
        if goal is not None and goal.target_rom:
            item["range_of_motion_target_degrees"] = int(goal.target_rom) if float(goal.target_rom).is_integer() \
                else goal.target_rom
        description = catalog.exercises.get(e["key"], {}).get("description")
        if description:
            item["instructions"] = description
        items.append(item)
    plan = program_plan(store, patient_id)
    return {"patient": patient_id, "plan": plan.title if plan else None, "program": assignment.program_name,
            "sessions_per_week": int(assignment.sessions_per_week), "exercises": items}


def suggestions(extract_data: Optional[dict]) -> List[str]:
    """Three questions the coach can answer from this program."""
    if not extract_data:
        return []
    names = [e["name"] for e in extract_data["exercises"]]
    out = [f"How many reps of {names[0]} should I do?",
           f"How do I do {names[1] if len(names) > 1 else names[0]}?",
           "Which exercises are left for today?"]
    return out


# ----------------------------------------------------------------------------- the request

def schema(extract_data: dict) -> dict:
    names = [e["name"] for e in extract_data["exercises"]]
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["answer", "referral", "refusal"]},
            "exercise": {"type": "string", "enum": names + [""]},
            "answer": {"type": "string"},
        },
        "required": ["kind", "exercise", "answer"],
        "additionalProperties": False,
    }


def request(extract_data: dict, question: str) -> dict:
    """The fixed system prompt, then the program, each with a cache breakpoint, then the question."""
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": schema(extract_data)}},
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": json.dumps(extract_data, ensure_ascii=False), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"The patient asks: {question}"},
        ]}],
    }


_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set:
    return {str(int(float(n))) if float(n).is_integer() else n for n in _NUMBER.findall(text or "")}


def numbers_match(answer: str, extract_data: dict, question: str) -> bool:
    """Every number in an answer must appear in the program or the patient's own question (the dose check)."""
    allowed = _numbers(json.dumps(extract_data)) | _numbers(question)
    return _numbers(answer) <= allowed


def _parse(text: str, extract_data: dict, question: str):
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("kind") not in ("answer", "referral", "refusal"):
        return None
    kind = data["kind"]
    if kind != "answer":
        return kind, "", ""
    names = {e["name"] for e in extract_data["exercises"]}
    answer, exercise = data.get("answer"), data.get("exercise")
    if not isinstance(answer, str) or not answer.strip():
        return None
    if exercise not in names or not numbers_match(answer, extract_data, question):
        return "referral", "", exercise if exercise in names else ""
    return "answer", answer.strip(), exercise


# ----------------------------------------------------------------------------- asking

def _turn(store, patient_id, question, kind, answer=None, exercise=None, called=False) -> CoachResult:
    plan = program_plan(store, patient_id)
    row = store.coach_turn_add(patient_id, question, kind, answer, exercise or None, called,
                               plan.id if plan else None)
    return CoachResult(kind, answer if kind == "answer" else SET_TEXT[kind], exercise or "", row["id"],
                       row["asked_at"], ai=kind == "answer")


def ask(store: SessionStore, patient_id: str, question: str, client: Optional[aclient.Client] = None) -> CoachResult:
    question = " ".join((question or "").split())
    if not question:
        raise ValueError("Write a question first.")
    if len(question) > MAX_QUESTION:
        raise ValueError(f"Keep a question under {MAX_QUESTION} characters.")
    if redflags.screen(question):                      # first, whatever else is true
        return _turn(store, patient_id, question, "emergency")
    if not assistant.switches(store, patient_id)["coach"]:
        return _turn(store, patient_id, question, "off")
    if questions_left_today(store, patient_id) <= 0:
        return _turn(store, patient_id, question, "limit")
    data = program_extract(store, patient_id)
    if data is None:
        return _turn(store, patient_id, question, "no_program")
    parsed = assistant._call(store, patient_id, None, "coach", request(data, question), client,
                             lambda text: _parse(text, data, question))
    if parsed is None:
        return _turn(store, patient_id, question, "unavailable", called=True)
    kind, answer, exercise = parsed
    return _turn(store, patient_id, question, kind, answer or None, exercise, called=True)


# ----------------------------------------------------------------------------- the therapist's log

def conversations(store: SessionStore, patient_id: str) -> List[dict]:
    """Every coach turn grouped by day, newest day first, each day's turns oldest first."""
    days: dict = {}
    for t in store.coach_turns(patient_id):
        days.setdefault(t["asked_at"][:10], []).append(t)
    return [{"day": d, "turns": days[d]} for d in sorted(days, reverse=True)]
