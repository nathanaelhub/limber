"""
Conversations between a patient and the therapist (feature 008). Pure rules over SessionStore.

Free text is the one place in Limber where someone can type identifying details, so:
messaging is off until the therapist turns it on for a patient; text that looks like a name, a
date, a record number, a phone number, or an email address triggers a warning before it is sent
(the writer may edit, or send anyway, and that choice is recorded); the therapist can remove any
message; and message text is never written to logs or to the event history.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import List, Optional

from src.ptlog import privacy
from src.ptlog.models import ConversationSummary, Message, PortalError
from src.ptlog.store import SessionStore

MAX_LENGTH = 2000
PATIENT_PER_HOUR = 20
FIRST_LINE = 80
SIDES = ("patient", "therapist")
NOT_FOR_EMERGENCIES = ("Not for emergencies. Your therapist reads messages during working hours. "
                       "If this is urgent, call your clinic or emergency services.")

_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]?){9,14}\d(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CHECKS = ((privacy.NAME_RE, "name"), (privacy.DATE_RE, "date"), (_EMAIL_RE, "email address"),
           (_PHONE_RE, "phone number"), (privacy.DIGITS_RE, "record number"))


class MessagingOff(PortalError):
    def __init__(self, why: str = "Messages are not turned on for this patient."):
        super().__init__(why)


class TooManyMessages(PortalError):
    def __init__(self):
        super().__init__(f"You can send up to {PATIENT_PER_HOUR} messages an hour. Please try again later.")


class NeedsConfirmation(PortalError):
    """The text looks like it contains identifying details; the writer must confirm or edit."""

    def __init__(self, reasons: List[str]):
        super().__init__("This message looks like it contains a " + " and a ".join(reasons) +
                         ". Limber works without names or contact details. Edit it, or send it anyway.")
        self.reasons = reasons


def check_text(text: str) -> List[str]:
    """Which kinds of identifying detail the text appears to contain (empty when none)."""
    found: List[str] = []
    for pattern, reason in _CHECKS:
        if pattern.search(text) and reason not in found:
            if reason == "record number" and "phone number" in found:
                continue                                  # a phone number is also a long run of digits
            found.append(reason)
    return found


def is_enabled(store: SessionStore, patient_id: str) -> bool:
    return store.conversation_enabled(patient_id)


def set_enabled(store: SessionStore, patient_id: str, enabled: bool) -> None:
    store.conversation_set_enabled(patient_id, enabled)


def send(store: SessionStore, patient_id: str, sender: str, text, confirm: bool = False) -> Message:
    if sender not in SIDES:
        raise PortalError("A message is sent by the patient or the therapist")
    if not isinstance(text, str) or not text.strip():
        raise PortalError("Write a message first.")
    body = text.strip()
    if len(body) > MAX_LENGTH:
        raise PortalError(f"A message can be up to {MAX_LENGTH:,} characters.")
    store._require_patient(patient_id)
    if not store.conversation_enabled(patient_id):
        raise MessagingOff()
    if store.get_discharge(patient_id) is not None:
        raise MessagingOff("This conversation is closed because the patient was discharged.")
    if sender == "patient" and store.message_count_since(
            patient_id, "patient", store.clock() - timedelta(hours=1)) >= PATIENT_PER_HOUR:
        raise TooManyMessages()
    reasons = check_text(body)
    if reasons and not confirm:
        raise NeedsConfirmation(reasons)
    return store.message_add(patient_id, sender, body, warned=bool(reasons))


def thread(store: SessionStore, patient_id: str, viewer: str, mark_read: bool = True) -> List[Message]:
    """The conversation, oldest first. Reading marks the other side's messages as read."""
    if viewer not in SIDES:
        raise PortalError("viewer must be the patient or the therapist")
    store._require_patient(patient_id)
    if mark_read:
        store.messages_mark_read(patient_id, from_sender="patient" if viewer == "therapist" else "therapist")
    return store.message_thread(patient_id)


def unread_count(store: SessionStore, patient_id: str, viewer: str) -> int:
    other = "patient" if viewer == "therapist" else "therapist"
    return store.messages_unread(other, patient_id).get(patient_id, 0)


def total_unread(store: SessionStore) -> int:
    """Messages from patients that the therapist has not opened yet."""
    return sum(store.messages_unread("patient").values())


def _first_line(body: Optional[str], removed: bool) -> str:
    if removed:
        return "(message removed)"
    line = (body or "").split("\n", 1)[0].strip()
    return line if len(line) <= FIRST_LINE else line[:FIRST_LINE] + "…"


def inbox(store: SessionStore, include_empty: bool = False) -> List[ConversationSummary]:
    """One row per patient conversation, latest activity first."""
    unread = store.messages_unread("patient")
    rows = []
    for r in store.conversation_rows():
        if r["last_id"] is None and not include_empty:
            continue
        rows.append(ConversationSummary(
            patient_id=r["patient_id"], enabled=bool(r["enabled"]), unread=unread.get(r["patient_id"], 0),
            first_line=_first_line(r["last_body"], r["last_removed"] is not None) if r["last_id"] else "",
            last_sender=r["last_sender"], last_at=r["last_at"]))
    rows.sort(key=lambda c: (c.last_at or "", c.patient_id), reverse=True)
    return rows


def remove(store: SessionStore, message_id: int) -> bool:
    """The therapist removes a message (for example one with identifying details); a marker stays."""
    return store.message_remove(int(message_id))
