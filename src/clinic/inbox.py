"""The clinic Inbox's rules (feature 019 slice 2, FR-007 to FR-009), moved out of the Streamlit page and tested
without a server.

"Needs you" is one list: red-flag messages, reschedule requests, and unread messages by plan of care. Opening the
Inbox marks nothing read; a conversation is marked read only when the therapist's page asks for it explicitly.
Every function takes a store already limited to the therapist's caseload, and checks by-id writes against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple

from src.portal import messages as ptmessages
from src.portal import plans as ptplans
from src.ptlog.models import Message, Plan, PTLogError, PatientNotFoundError
from src.ptlog.store import SessionStore

URGENT, RESCHEDULE, UNREAD = "urgent", "reschedule", "unread"
_ORDER = {URGENT: 0, RESCHEDULE: 1, UNREAD: 2}

DRAFT_NOTICES = {
    "nothing": "There is no new message from the patient to reply to.",
    "cap": "You have used today's AI requests. They reset tomorrow.",
    "unavailable": "The assistant isn't available right now. Write the reply yourself, or try again in a few minutes.",
    "off": "Weekly summaries and drafts are off for this patient.",
    "archived": "This plan is archived, so it takes no new replies.",
    "withheld": "This message may need a direct response, so no draft was made.",
}


class NotYours(PTLogError):
    """A patient, plan, message, visit or file that is not on this therapist's caseload: answered as not found."""

    def __init__(self, what: str = "That was not found."):
        super().__init__(what)


@dataclass
class Item:
    kind: str                    # urgent | reschedule | unread
    patient_id: str
    plan_id: Optional[int]
    plan_title: str
    line: str
    at: str                      # local ISO time, for sorting and the "when" label
    unread: int = 0
    words: List[str] = field(default_factory=list)

    @property
    def href(self) -> str:
        return conversation_href(self.patient_id, self.plan_id)


def conversation_href(patient_id: str, plan_id: Optional[int]) -> str:
    return f"/therapist/inbox/{patient_id}" + (f"?plan={plan_id}" if plan_id is not None else "")


# ----------------------------------------------------------------------------- ownership

def own_patient(store: SessionStore, patient_id: str) -> str:
    try:
        store._require_patient(patient_id)
    except PatientNotFoundError:
        raise NotYours() from None
    return patient_id


def own_plan(store: SessionStore, patient_id: str, plan_id) -> Optional[Plan]:
    """The plan, if it is this patient's; None when no plan is named. A plan of another patient is refused."""
    if plan_id is None or plan_id == "":
        return None
    try:
        plan = store.plan_get(int(plan_id))
    except (TypeError, ValueError):
        raise NotYours() from None
    if plan is None or plan.patient_id != patient_id:
        raise NotYours()
    return plan


def own_message(store: SessionStore, patient_id: str, message_id) -> Message:
    try:
        wanted = int(message_id)
    except (TypeError, ValueError):
        raise NotYours() from None
    for m in store.message_thread(own_patient(store, patient_id)):
        if m.id == wanted:
            return m
    raise NotYours()


def own_appointment(store: SessionStore, patient_id: str, appointment_id):
    try:
        a = store.appointment_get(int(appointment_id))
    except (TypeError, ValueError):
        raise NotYours() from None
    if a is None or a.patient_id != patient_id:
        raise NotYours()
    return a


def own_voice(store: SessionStore, patient_id: str, media_id):
    m = store.media_get(media_id) if isinstance(media_id, str) else None
    if m is None or m.patient_id != patient_id or m.kind != "voice":
        raise NotYours()
    return m


# ----------------------------------------------------------------------------- the "Needs you" list

def first_line(body: Optional[str], limit: int = ptmessages.FIRST_LINE) -> str:
    line = (body or "").split("\n", 1)[0].strip()
    return line if len(line) <= limit else line[:limit] + "…"


def message_line(m: Message) -> str:
    if m.removed:
        return "(message removed)"
    if m.media_id:
        return "Voice note"
    if m.body:
        return first_line(m.body)
    if m.attachments:
        photos = sum(1 for a in m.attachments if a.kind == "photo")
        return f"{photos} photo" + ("" if photos == 1 else "s") if photos else "A PDF"
    return ""


def needs_you(store: SessionStore) -> List[Item]:
    """Everything waiting on the therapist, most pressing first: red flags, then reschedule requests, then
    unread messages by plan, each newest first. Reading this list marks nothing read."""
    from src.assist import assistant, redflags
    items: List[Item] = []
    plans_of = {}
    for row in ptmessages.inbox(store):
        pid = row.patient_id
        plans_of[pid] = {p.id: p for p in store.plans(pid)}
        unread = store.messages_unread_by_plan("patient", pid)
        thread = store.message_thread(pid)
        for plan_id, plan in plans_of[pid].items():
            flagged = assistant.needs_attention(store, pid, plan_id)
            if flagged:
                words: List[str] = []
                for m in flagged:
                    words += [w for w in redflags.found_words(m.body) if w not in words]
                items.append(Item(URGENT, pid, plan_id, plan.title, "May need a direct response",
                                  flagged[-1].sent_at, unread.get(plan_id, 0), words))
                continue
            if unread.get(plan_id):
                latest = [m for m in thread if m.plan_id == plan_id and m.sender == "patient"]
                last = latest[-1] if latest else None
                items.append(Item(UNREAD, pid, plan_id, plan.title, message_line(last) if last else "",
                                  last.sent_at if last else "", unread[plan_id]))
    for a in ptplans.reschedule_requests(store):
        view = ptplans.appointment_json(store, a)
        plan = store.plan_get(a.plan_id)
        when = _visit_label(view["starts_local"])
        line = f"Asks to move {when}" + (f": “{first_line(a.request_note, 60)}”" if a.request_note else "")
        items.append(Item(RESCHEDULE, a.patient_id, a.plan_id, plan.title if plan else "", line,
                          (a.updated_at or "")[:19]))
    items.sort(key=lambda i: i.at or "", reverse=True)
    items.sort(key=lambda i: _ORDER[i.kind])
    return items


def _visit_label(starts_local: str) -> str:
    d = datetime.fromisoformat(starts_local)
    return d.strftime("%a %-d %b, %H:%M")


def conversations(store: SessionStore) -> List[dict]:
    """Every conversation on the caseload, latest first, for opening one that needs nothing."""
    rows = []
    for r in ptmessages.inbox(store, include_empty=True):
        rows.append({"patient_id": r.patient_id, "unread": r.unread, "enabled": r.enabled,
                     "line": ("You: " if r.last_sender == "therapist" else "") + r.first_line if r.last_at else "",
                     "at": r.last_at or "", "summary": plan_summary(store, r.patient_id),
                     "href": conversation_href(r.patient_id, None)})
    return rows


def plan_summary(store: SessionStore, patient_id: str) -> str:
    """One line per patient: each plan with the patient's unread messages in it; archived plans only when they
    still hold unread messages."""
    unread = store.messages_unread_by_plan("patient", patient_id)
    parts = []
    for p in store.plans(patient_id):
        if p.read_only and not unread.get(p.id):
            continue
        parts.append(p.title + (f" ({unread[p.id]})" if unread.get(p.id) else ""))
    return " · ".join(parts)


def default_plan(store: SessionStore, patient_id: str) -> Optional[Plan]:
    """The plan a conversation opens on: the first with unread messages, else the first that takes replies,
    else the first."""
    plans = store.plans(patient_id)
    if not plans:
        return None
    unread = store.messages_unread_by_plan("patient", patient_id)
    for pick in ([p for p in plans if unread.get(p.id)], [p for p in plans if not p.read_only], plans):
        if pick:
            return pick[0]
    return None


def total(store: SessionStore) -> int:
    return len(needs_you(store))


# ----------------------------------------------------------------------------- the open conversation

def reply_state(store: SessionStore, patient_id: str, plan: Optional[Plan]) -> str:
    """Whether the reply box shows, and if not why, in this order: discharged, archived plan, messaging off."""
    if store.get_discharge(patient_id) is not None:
        return "discharged"
    if plan is not None and plan.read_only:
        return "archived"
    if not ptmessages.is_enabled(store, patient_id):
        return "off"
    return "open"


READ_ONLY_TEXT = {
    "discharged": "This patient is discharged, so the conversation is read-only.",
    "archived": "This plan of care is archived, so its conversation is read-only.",
}


def withheld(store: SessionStore, patient_id: str, plan_id: Optional[int]) -> Tuple[List[Message], List[str]]:
    """Red-flag messages since the last reply that have not been marked handled, and the words that tripped."""
    from src.assist import assistant, redflags
    flagged = assistant.needs_attention(store, patient_id, plan_id)
    words: List[str] = []
    for m in flagged:
        words += [w for w in redflags.found_words(m.body) if w not in words]
    return flagged, words


def assist_on(store: SessionStore, patient_id: str) -> bool:
    """Whether Draft a reply is offered: a key on this installation and summaries on for the patient."""
    from src.assist import assistant, config
    return config.available() and bool(assistant.switches(store, patient_id)["summaries"])


def thread(store: SessionStore, patient_id: str, plan: Optional[Plan]) -> List[Message]:
    """The conversation for display. Never marks anything read (FR-007): that is `mark_read`."""
    return ptmessages.thread(store, patient_id, viewer="therapist", mark_read=False,
                             plan_id=plan.id if plan else None)


def mark_read(store: SessionStore, patient_id: str, plan: Optional[Plan]) -> None:
    store.messages_mark_read(patient_id, from_sender="patient", plan_id=plan.id if plan else None)


def send(store: SessionStore, patient_id: str, plan: Optional[Plan], text, confirm: bool,
         files: Sequence[Tuple[str, bytes]] = (), from_draft: bool = False, media_dir=None) -> Message:
    """Send the reply. A reply that looks identifying raises NeedsConfirmation; the page sends it again with
    confirm only while the text is the one the warning was about."""
    return ptmessages.send(store, patient_id, "therapist", text, confirm=confirm,
                           plan_id=plan.id if plan else None, files=files, media_dir=media_dir,
                           from_draft=from_draft)


# ----------------------------------------------------------------------------- labels

def when_label(iso: Optional[str], now: datetime) -> str:
    """8:40 today, Yesterday, Mon within the week, else 4 Nov."""
    if not iso:
        return ""
    t = datetime.fromisoformat(iso[:19])
    if t.date() == now.date():
        return t.strftime("%-H:%M")
    if t.date() == (now - timedelta(days=1)).date():
        return "Yesterday"
    if now.date() - t.date() < timedelta(days=7):
        return t.strftime("%a")
    return t.strftime("%-d %b")


def day_label(iso: str, now: datetime) -> str:
    t = datetime.fromisoformat(iso[:19])
    if t.date() == now.date():
        return "Today"
    if t.date() == (now - timedelta(days=1)).date():
        return "Yesterday"
    return t.strftime("%a %-d %b")


def voice_state(job, transcripts_available: bool) -> Tuple[str, Optional[str]]:
    """(the line about the written-out text, the text to show or None)."""
    if not transcripts_available:
        return ("Written out automatically: not available on this installation. The recording is the record.", None)
    if job is None or job.state in ("queued", "running"):
        return ("Written out automatically: still being done. The recording plays now; reload for the text.", None)
    if job.state == "failed":
        return (f"Written out automatically: it did not work ({job.reason}). The recording is unaffected.", None)
    if job.removed:
        return ("Written out automatically: the text was removed.", None)
    note = "Automatic transcript — may contain mistakes. Listen before relying on it."
    if job.warned:
        note += " This text looks like it contains identifying details."
    return (note, job.text or "Nothing recognisable was said.")
