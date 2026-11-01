"""
The therapist assistant (feature 018, slice A): a weekly summary and a draft reply, both for the therapist to
check before anything reaches the patient.

Rules that live here rather than in the prompt, because a prompt is advice and these are guarantees:
- nothing is sent unless the patient's switch is on (and, in the screens, a key is configured);
- a week with no records is answered without a call;
- a message that trips the red-flag list is never drafted;
- every claim in a summary must cite record IDs that exist in the extract, or it is dropped;
- a refusal, a truncated answer, an API error, or output that does not parse is "unavailable", never partial;
- each call is logged on the host with its size and purpose, never its content;
- each therapist has a daily call cap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from src.assist import client as aclient, extract, redflags
from src.ptlog.models import Message
from src.ptlog.store import SessionStore

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
SUMMARY_EFFORT = "medium"
DRAFT_EFFORT = "medium"
MAX_TOKENS = 16000
MAX_NEXT_STEPS = 3
DEFAULT_DAILY_CAP = 50
CAP_SETTING = "assist_daily_cap"
SWITCHES = ("summaries", "coach")
HEADINGS = ("Adherence", "Pain trend", "Diary and questionnaires", "Questions asked")

NOTICE_SUMMARIES = (
    "Your therapist may use an AI assistant (Claude, made by Anthropic) to summarise your week and to draft replies. "
    "It reads your exercise logs, check-ins, questionnaire scores and messages under your patient code, never your "
    "name. Photos, documents, videos and voice recordings are never sent to it. Your therapist reads and checks "
    "everything before it reaches you.")
NOTICE_COACH = (
    "Your therapist has turned on the exercise coach. It is an AI assistant (Claude, made by Anthropic) that answers "
    "questions using your exercise program only, under your patient code, never your name. Your therapist can read "
    "these chats. It is not for emergencies.")

SUMMARY_SYSTEM = """You help a physical therapist review one patient's week between clinic visits.

You receive a JSON extract of the patient's records. The patient is identified only by a code. Each record has an id.

Write a short summary for the therapist, in sections chosen from: Adherence (exercise done against the program),
Pain trend, Diary and questionnaires, Questions asked (anything the patient asked or raised in messages).
Leave out a section that has no records. Then give one to three suggested next steps for the therapist.

Rules:
- Every section and every next step must list, in record_ids, the ids of the records it is based on. Use only ids
  that appear in the extract. Do not state anything the records do not show.
- Two or three plain sentences per section. Numbers and dates from the records, not impressions.
- Do not diagnose, do not suggest medication, and do not change the program yourself; a next step may suggest the
  therapist reviews or checks something.
- Photos, documents, and recordings are not included in the extract; the therapist has them. Mention that one was
  sent when it matters, never what it shows.
- Refer to the person as "the patient". Never guess a name."""

DRAFT_SYSTEM = """You draft a reply from a physical therapist to their patient, for the therapist to edit before sending.

You receive a JSON extract: the patient's code, their plan and program, their recent logs, and the conversation in
this plan, oldest first. Reply to the patient's latest message or messages.

Rules:
- Two to five short sentences in plain, warm words. Write as the therapist ("I").
- Do not change exercises, doses, or the program; do not diagnose; do not give medication advice. When something
  needs the therapist's judgement, say you will look at it together at the next visit, or ask them to call the clinic.
- Never use a name. Do not add a greeting with a name or a signature.
- Photos, documents, and recordings the patient sent are not included in the extract, but the therapist has them.
  Never say one did not arrive, and do not describe what is in one.
- Output only the reply text."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {"heading": {"type": "string", "enum": list(HEADINGS)}, "text": {"type": "string"},
                           "record_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["heading", "text", "record_ids"], "additionalProperties": False}},
        "next_steps": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "record_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "record_ids"], "additionalProperties": False}},
    },
    "required": ["sections", "next_steps"],
    "additionalProperties": False,
}


@dataclass
class Claim:
    text: str
    record_ids: List[str]
    heading: str = ""


@dataclass
class SummaryResult:
    state: str                                   # ok | no_records | off | cap | unavailable
    sections: List[Claim] = field(default_factory=list)
    next_steps: List[Claim] = field(default_factory=list)
    dropped: int = 0                             # claims removed because they cited no record from the extract
    record_count: int = 0
    window: Optional[dict] = None

    def as_text(self) -> str:
        """The summary as a note: AI-drafted, with the record IDs it cites."""
        lines = [f"Weekly summary {self.window['from']} to {self.window['to']} (AI-drafted)" if self.window
                 else "Weekly summary (AI-drafted)", ""]
        for c in self.sections:
            lines += [c.heading, f"{c.text} [{', '.join(c.record_ids)}]", ""]
        if self.next_steps:
            lines.append("Suggested next steps")
            lines += [f"{i}. {c.text} [{', '.join(c.record_ids)}]" for i, c in enumerate(self.next_steps, 1)]
        return "\n".join(lines).strip()


@dataclass
class DraftResult:
    state: str                                   # ok | withheld | nothing | off | cap | unavailable
    text: str = ""
    flags: List[str] = field(default_factory=list)
    message_ids: List[int] = field(default_factory=list)   # the patient messages a withheld draft was about


# ----------------------------------------------------------------------------- switches, cap, notes

def switches(store: SessionStore, patient_id: str) -> dict:
    return store.assist_switches(patient_id)


def set_switch(store: SessionStore, patient_id: str, which: str, on: bool, account_id: Optional[int] = None) -> None:
    if which not in SWITCHES:
        raise ValueError(f"Unknown assistant switch: {which}")
    store.assist_set_switch(patient_id, which, on, account_id)


def daily_cap(store: SessionStore) -> int:
    try:
        return max(0, int(store.clinic_setting(CAP_SETTING, str(DEFAULT_DAILY_CAP))))
    except ValueError:
        return DEFAULT_DAILY_CAP


def set_daily_cap(store: SessionStore, calls: int) -> None:
    store.set_clinic_setting(CAP_SETTING, str(max(0, int(calls))))


def calls_left_today(store: SessionStore, account_id: Optional[int]) -> int:
    return max(0, daily_cap(store) - store.assist_calls_on(store._now()[:10], account_id))


def save_note(store: SessionStore, patient_id: str, body: str, ai_drafted: bool, account_id: Optional[int],
              edited: bool = False, plan_id: Optional[int] = None) -> dict:
    body = (body or "").strip()
    if not body:
        raise ValueError("The note is empty.")
    return store.therapist_note_add(patient_id, body, ai_drafted, edited, account_id, plan_id)


def notes(store: SessionStore, patient_id: str) -> List[dict]:
    return store.therapist_notes(patient_id)


# ----------------------------------------------------------------------------- requests

def _body(system: str, extract_data: dict, instruction: str, effort: str, fmt: Optional[dict] = None) -> dict:
    """The fixed system prompt, then the extract, each with a cache breakpoint, then the varying instruction."""
    output_config = {"effort": effort}
    if fmt is not None:
        output_config["format"] = fmt
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
        "thinking": {"type": "adaptive"},
        "output_config": output_config,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": json.dumps(extract_data, ensure_ascii=False), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": instruction},
        ]}],
    }


def summary_request(ex: extract.Extract) -> dict:
    return _body(SUMMARY_SYSTEM, ex.data, "Summarise this patient's last 7 days for their therapist.",
                 SUMMARY_EFFORT, {"type": "json_schema", "schema": SUMMARY_SCHEMA})


def draft_request(ex: extract.Extract, answering: List[int]) -> dict:
    ids = ", ".join(f"M-{i}" for i in answering)
    return _body(DRAFT_SYSTEM, ex.data, f"Draft the therapist's reply to {ids}.", DRAFT_EFFORT)


def _call(store: SessionStore, patient_id: str, account_id: Optional[int], purpose: str, body: dict,
          client: Optional[aclient.Client], parse=lambda text: text.strip() or None):
    """Send one request, parse its text, and log it once. Returns the parsed answer, or None when the
    assistant is unavailable (no call possible, an API error, a refusal, a cut-off, or unusable output)."""
    try:
        client = client or aclient.make_client()
        reply = client.send(body)
    except aclient.AssistUnavailable as err:
        store.assist_call_add(patient_id, account_id, purpose, body["model"], 0, 0, err.reason)
        return None
    outcome = reply.stop_reason if reply.stop_reason in ("refusal", "max_tokens") else "ok"
    answer = parse(reply.text) if outcome == "ok" else None
    if outcome == "ok" and answer is None:
        outcome = "invalid"
    store.assist_call_add(patient_id, account_id, purpose, reply.model or body["model"], reply.input_tokens,
                          reply.output_tokens, outcome)
    return answer


# ----------------------------------------------------------------------------- the weekly summary (US1)

def _claims(items, ids, with_heading: bool):
    kept, dropped = [], 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        cited = [i for i in item.get("record_ids") or [] if isinstance(i, str) and i in ids]
        text = item.get("text")
        heading = item.get("heading") if with_heading else ""
        if not cited or not isinstance(text, str) or not text.strip() or (with_heading and heading not in HEADINGS):
            dropped += 1
            continue
        kept.append(Claim(text=text.strip(), record_ids=cited, heading=heading or ""))
    return kept, dropped


def weekly_summary(store: SessionStore, patient_id: str, account_id: Optional[int] = None,
                   client: Optional[aclient.Client] = None) -> SummaryResult:
    if not switches(store, patient_id)["summaries"]:
        return SummaryResult("off")
    ex = extract.build(store, patient_id)
    if ex.empty:
        return SummaryResult("no_records", window=ex.data["window"])
    if calls_left_today(store, account_id) <= 0:
        return SummaryResult("cap", window=ex.data["window"])
    def parse(text):
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        sections, d1 = _claims(data.get("sections"), ex.ids, True)
        steps, d2 = _claims(data.get("next_steps"), ex.ids, False)
        d2 += max(0, len(steps) - MAX_NEXT_STEPS)
        return (sections, steps[:MAX_NEXT_STEPS], d1 + d2) if sections or steps else None

    answer = _call(store, patient_id, account_id, "summary", summary_request(ex), client, parse)
    if answer is None:
        return SummaryResult("unavailable", record_count=len(ex.ids), window=ex.data["window"])
    sections, steps, dropped = answer
    return SummaryResult("ok", sections, steps, dropped, len(ex.ids), ex.data["window"])


# ----------------------------------------------------------------------------- draft replies (US2)

def _unanswered(thread: List[Message]) -> List[Message]:
    """The patient's messages since the therapist last wrote in this conversation."""
    out: List[Message] = []
    for m in thread:
        if m.sender == "therapist":
            out = []
        elif not m.removed:
            out.append(m)
    return out


def _flagged(store: SessionStore, waiting: List[Message]) -> List[tuple]:
    handled = store.messages_handled([m.id for m in waiting])
    return [(m, redflags.screen(m.body)) for m in waiting if m.id not in handled and redflags.screen(m.body)]


def needs_attention(store: SessionStore, patient_id: str, plan_id: Optional[int] = None) -> List[Message]:
    """Unanswered patient messages that tripped the red-flag list and were not marked handled."""
    plan_ids = [plan_id] if plan_id is not None else [p.id for p in store.plans(patient_id)]
    found: List[Message] = []
    for pid in plan_ids:
        found += [m for m, _ in _flagged(store, _unanswered(store.message_thread(patient_id, plan_id=pid)))]
    return found


def mark_handled(store: SessionStore, message_id: int, account_id: Optional[int]) -> None:
    """The therapist dealt with a flagged message by phone: it leaves the attention list, and who and when
    is recorded."""
    store.message_mark_handled(message_id, "phone", account_id)


def draft_reply(store: SessionStore, patient_id: str, plan_id: Optional[int] = None, account_id: Optional[int] = None,
                client: Optional[aclient.Client] = None) -> DraftResult:
    if not switches(store, patient_id)["summaries"]:
        return DraftResult("off")
    plan = store.plan_get(plan_id) if plan_id is not None else store.current_plan(patient_id)
    waiting = _unanswered(store.message_thread(patient_id, plan_id=plan.id if plan else None))
    if not waiting:
        return DraftResult("nothing")
    flagged = _flagged(store, waiting)
    if flagged:
        words = sorted({w for _, hits in flagged for w in hits})
        return DraftResult("withheld", flags=words, message_ids=[m.id for m, _ in flagged])
    if calls_left_today(store, account_id) <= 0:
        return DraftResult("cap")
    ex = extract.build_for_reply(store, patient_id, plan.id if plan else None)
    text = _call(store, patient_id, account_id, "draft", draft_request(ex, [m.id for m in waiting]), client)
    if text is None:
        return DraftResult("unavailable")
    return DraftResult("ok", text=text)
