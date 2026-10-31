"""
The pseudonymised record extract sent to the AI processor (feature 018, FR-006).

It is built only from the clinical record under the pseudonymous patient ID: the plan titles, the program,
and the last days of sessions, check-ins, questionnaire scores, messages, and host transcripts. It never
reads the accounts tables, the patient's label or notes, or a plan's diagnosis, so no name, username, or
account field can reach a request. Every record carries an ID (`S-`, `E-`, `M-`, `T-`) that a summary must
cite for each claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from src.ptlog import programs
from src.ptlog.store import SessionStore

WINDOW_DAYS = 7
CONVERSATION_TAIL = 20


@dataclass
class Extract:
    data: Dict[str, Any]
    ids: Set[str] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return not self.data["records"]


def _num(value):
    """3.0 reads as 3: whole-number scores are sent without a decimal point."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _since(store: SessionStore, days: int) -> str:
    return (datetime.fromisoformat(store._now()) - timedelta(days=days)).isoformat()


def _program(store: SessionStore, patient_id: str) -> Optional[Dict[str, Any]]:
    a = store.active_assignment(patient_id)
    if a is None:
        return None
    return {"name": a.program_name, "sessions_per_week": a.sessions_per_week,
            "exercises": [programs.exercise_name(k) for k in a.exercise_keys]}


def _sessions(store: SessionStore, patient_id: str, since: str) -> List[Dict[str, Any]]:
    from src.portal import diary
    out = []
    for row in reversed(store.list_sessions(patient_id)):
        if row.start_time < since or row.status == "running":
            continue
        if row.source == "diary":
            s = store.load_session(row.id)
            note = diary.note_of(s)["note"]
            out.append({"id": f"S-{row.id}", "type": "self_reported_session", "at": row.start_time[:16],
                        "what": diary.summary(s), **({"note": note} if note else {})})
        else:
            out.append({"id": f"S-{row.id}", "type": "session", "at": row.start_time[:16], "where": row.origin,
                        "exercises": row.exercises, "reps": row.total_reps,
                        "avg_form_score": None if row.avg_form_score is None else round(row.avg_form_score)})
    return out


def _entries(store: SessionStore, patient_id: str, since: str) -> List[Dict[str, Any]]:
    out = []
    for e in store.entries(patient_id):
        if e.recorded_at < since:
            continue
        rec: Dict[str, Any] = {"id": f"E-{e.id}", "type": e.kind, "at": e.recorded_at[:16]}
        if e.kind == "checkin":
            rec["pain_0_to_10"] = _num(e.score)
            if e.phase in ("before", "after"):
                rec["when"] = f"{e.phase} a session"
        elif e.kind == "questionnaire":
            rec["questionnaire"] = e.payload.get("name") or e.payload.get("instrument")
            rec["total"] = _num(e.score)
        elif e.score is not None:
            rec["score"] = _num(e.score)
        note = "" if e.note_removed else (e.payload.get("note") or "")
        if note:
            rec["note"] = note
        out.append(rec)
    return out


def _messages(store: SessionStore, patient_id: str, since: Optional[str], plan_id: Optional[int],
              titles: Dict[int, str]) -> List[Dict[str, Any]]:
    thread = store.message_thread(patient_id, plan_id=plan_id)
    if since is not None:
        thread = [m for m in thread if m.sent_at >= since]
    else:
        thread = thread[-CONVERSATION_TAIL:]
    out = []
    for m in thread:
        if m.removed:
            continue
        rec: Dict[str, Any] = {"id": f"M-{m.id}", "type": "message", "from": m.sender, "at": m.sent_at[:16],
                               "plan": titles.get(m.plan_id, "")}
        if m.body:
            rec["text"] = m.body
        if m.media_id:
            rec["voice_note"] = "the patient sent a recording; the therapist has it, but it is not included here"
        live = [a for a in m.attachments if a.deleted_at is None]
        if live:
            photos = sum(1 for a in live if a.kind == "photo")
            rec["attached"] = (f"{photos} photo" + ("s" if photos != 1 else "")) if photos else "a PDF"
        out.append(rec)
        if m.media_id:
            t = store.transcription_for(m.media_id)
            if t is not None and t.state == "done" and t.text and not t.removed:
                out.append({"id": f"T-{t.id}", "type": "voice_note_transcript", "at": m.sent_at[:16],
                            "from": m.sender, "text": t.text})
    return out


def build(store: SessionStore, patient_id: str, days: int = WINDOW_DAYS) -> Extract:
    """For the weekly summary: every plan's records of the last `days` days."""
    since = _since(store, days)
    plans = store.plans(patient_id)
    titles = {p.id: p.title for p in plans}
    records = _sessions(store, patient_id, since) + _entries(store, patient_id, since) + \
        _messages(store, patient_id, since, None, titles)
    records.sort(key=lambda r: (r["at"], r["id"]))
    data = {
        "patient": patient_id,
        "window": {"from": since[:10], "to": store._now()[:10]},
        "plans": [{"title": p.title, "status": p.status, "started": p.start_date} for p in plans
                  if p.status != "archived"],
        "program": _program(store, patient_id),
        "records": records,
    }
    return Extract(data, {r["id"] for r in records})


def build_for_reply(store: SessionStore, patient_id: str, plan_id: Optional[int], days: int = WINDOW_DAYS) -> Extract:
    """For a draft reply: the plan's recent conversation plus the week's logs for context."""
    since = _since(store, days)
    plans = store.plans(patient_id)
    titles = {p.id: p.title for p in plans}
    plan = next((p for p in plans if p.id == plan_id), None) or store.current_plan(patient_id)
    conversation = _messages(store, patient_id, None, plan.id if plan else None, titles)
    logs = _sessions(store, patient_id, since) + _entries(store, patient_id, since)
    logs.sort(key=lambda r: (r["at"], r["id"]))
    data = {
        "patient": patient_id,
        "plan": plan.title if plan else None,
        "program": _program(store, patient_id),
        "recent_logs": logs,
        "records": conversation,
    }
    return Extract(data, {r["id"] for r in conversation + logs})
