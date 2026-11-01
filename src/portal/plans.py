"""
Plans of care and appointments (feature 017). Pure rules over SessionStore.

A plan is an episode of care: a title, a diagnosis the therapist writes (shown to the patient only when
the therapist chooses), and a status that moves active -> completed -> archived. Everything new belongs
to a plan, and an archived plan is read-only; that refusal lives in the data layer, so no route can
forget it.

Appointment times are stored in UTC and shown in the clinic's time zone, never the device's: a patient
travelling with their phone still sees the time the clinic means.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.ptlog.models import Appointment, Plan, PlanNotFound, PortalError
from src.ptlog.store import SessionStore

TITLE_MAX = 80
DIAGNOSIS_MAX = 500
NOTE_MAX = 200
REQUEST_MAX = 500
DEFAULT_TIME_ZONE = "America/Chicago"
TIME_ZONE_KEY = "time_zone"


# ---------------------------------------------------------------- plans

def _title(title) -> str:
    text = (title or "").strip() if isinstance(title, str) else ""
    if not text:
        raise PortalError("Give the plan a title, for example “Right knee, post-op”.")
    if len(text) > TITLE_MAX:
        raise PortalError(f"A plan title can be up to {TITLE_MAX} characters.")
    return text


def _diagnosis(text) -> str:
    text = (text or "").strip() if isinstance(text, str) else ""
    if len(text) > DIAGNOSIS_MAX:
        raise PortalError(f"A diagnosis can be up to {DIAGNOSIS_MAX} characters.")
    return text


def open_plan(store: SessionStore, patient_id: str, title, diagnosis="", diagnosis_visible: bool = False,
              start: Optional[date] = None) -> Plan:
    return store.plan_add(patient_id, _title(title), _diagnosis(diagnosis), bool(diagnosis_visible),
                          (start or store.clock().date()).isoformat())


def edit_plan(store: SessionStore, plan_id: int, **fields) -> Plan:
    if "title" in fields:
        fields["title"] = _title(fields["title"])
    if "diagnosis" in fields:
        fields["diagnosis"] = _diagnosis(fields["diagnosis"])
    return store.plan_update(plan_id, **fields)


def complete(store: SessionStore, plan_id: int) -> Plan:
    return store.plan_set_status(plan_id, "completed")


def reopen(store: SessionStore, plan_id: int) -> Plan:
    return store.plan_set_status(plan_id, "active")


def archive(store: SessionStore, plan_id: int) -> Plan:
    return store.plan_set_status(plan_id, "archived")


def own_plan(store: SessionStore, patient_id: str, plan_id) -> Plan:
    """The patient's plan with this id, or PlanNotFound (another patient's plan reads as missing)."""
    plan = store.plan_get(plan_id)
    if plan is None or plan.patient_id != patient_id:
        raise PlanNotFound("No such plan of care.")
    return plan


def plan_json(plan: Plan, unread: int = 0, therapist: bool = False) -> Dict[str, Any]:
    out = {"id": plan.id, "title": plan.title, "status": plan.status, "read_only": plan.read_only,
           "start_date": plan.start_date, "end_date": plan.end_date, "unread": unread}
    if therapist or plan.diagnosis_visible:
        out["diagnosis"] = plan.diagnosis
    if therapist:
        out["diagnosis_visible"] = plan.diagnosis_visible
    return out


def plans_view(store: SessionStore, patient_id: str, viewer: str = "patient") -> List[Dict[str, Any]]:
    """Every plan of one patient, with the other side's unread messages in each."""
    other = "therapist" if viewer == "patient" else "patient"
    unread = store.messages_unread_by_plan(other, patient_id)
    return [plan_json(p, unread.get(p.id, 0), therapist=viewer == "therapist") for p in store.plans(patient_id)]


# ---------------------------------------------------------------- the clinic's clock

def clinic_zone(store: SessionStore) -> ZoneInfo:
    return ZoneInfo(store.clinic_setting(TIME_ZONE_KEY, DEFAULT_TIME_ZONE))


def set_clinic_zone(store: SessionStore, name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise PortalError(f"Unknown time zone: {name!r}. Use a name like America/Chicago.")
    store.set_clinic_setting(TIME_ZONE_KEY, name)
    return name


def to_utc(store: SessionStore, local) -> str:
    """A clinic wall-clock time ('2026-11-04T09:00' or a naive datetime) as a stored UTC timestamp."""
    if isinstance(local, str):
        try:
            local = datetime.fromisoformat(local)
        except ValueError:
            raise PortalError("Give the time as YYYY-MM-DDTHH:MM.")
    if not isinstance(local, datetime):
        raise PortalError("Give the time as YYYY-MM-DDTHH:MM.")
    if local.tzinfo is None:
        local = local.replace(tzinfo=clinic_zone(store))
    return local.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def to_local(store: SessionStore, utc_text: str) -> datetime:
    return datetime.fromisoformat(utc_text).astimezone(clinic_zone(store))


# ---------------------------------------------------------------- appointments

def _minutes(minutes) -> int:
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 5 <= minutes <= 480:
        raise PortalError("An appointment lasts 5 to 480 minutes.")
    return minutes


def _note(note, limit: int = NOTE_MAX) -> str:
    text = (note or "").strip() if isinstance(note, str) else ""
    if len(text) > limit:
        raise PortalError(f"A note can be up to {limit} characters.")
    return text


def schedule(store: SessionStore, patient_id: str, local, minutes: int, note: str = "",
             plan_id: Optional[int] = None) -> Appointment:
    return store.appointment_add(patient_id, to_utc(store, local), _minutes(minutes), _note(note), plan_id)


def move(store: SessionStore, appointment_id: int, local, minutes: Optional[int] = None) -> Appointment:
    """The therapist changes the time. This answers a reschedule request, so the flag clears."""
    fields: Dict[str, Any] = {"starts_at": to_utc(store, local), "reschedule_requested": False}
    if minutes is not None:
        fields["minutes"] = _minutes(minutes)
    return store.appointment_update(appointment_id, **fields)


def cancel(store: SessionStore, appointment_id: int) -> Appointment:
    return store.appointment_update(appointment_id, status="cancelled", reschedule_requested=False)


def request_reschedule(store: SessionStore, patient_id: str, appointment_id, note) -> Appointment:
    a = store.appointment_get(appointment_id)
    if a is None or a.patient_id != patient_id:
        raise PortalError("No such appointment.")
    if a.status == "cancelled":
        raise PortalError("This appointment was cancelled.")
    if datetime.fromisoformat(a.starts_at) <= store.clock().astimezone(timezone.utc):
        raise PortalError("This appointment has already happened.")
    return store.appointment_update(a.id, reschedule_requested=True, request_note=_note(note, REQUEST_MAX),
                                    response_note="")


def decline_request(store: SessionStore, appointment_id: int, note: str = "") -> Appointment:
    return store.appointment_update(appointment_id, reschedule_requested=False, response_note=_note(note, REQUEST_MAX))


def state(store: SessionStore, a: Appointment) -> str:
    if a.status == "cancelled":
        return "cancelled"
    # A past appointment nobody marked is "past", never "missed": Limber does not know whether it happened.
    return "past" if datetime.fromisoformat(a.starts_at) <= store.clock().astimezone(timezone.utc) else "upcoming"


def appointment_json(store: SessionStore, a: Appointment) -> Dict[str, Any]:
    local = to_local(store, a.starts_at)
    return {"id": a.id, "plan_id": a.plan_id, "date": local.date().isoformat(), "time": local.strftime("%H:%M"),
            "starts_local": local.strftime("%Y-%m-%dT%H:%M"), "time_zone": str(clinic_zone(store)),
            "minutes": a.minutes, "note": a.note, "status": a.status, "state": state(store, a),
            "reschedule_requested": a.reschedule_requested, "request_note": a.request_note,
            "response_note": a.response_note}


def appointments_view(store: SessionStore, patient_id: str, plan_id: Optional[int] = None) -> List[Dict[str, Any]]:
    return [appointment_json(store, a) for a in store.appointments(patient_id, plan_id)]


def reschedule_requests(store: SessionStore) -> List[Appointment]:
    """Every flagged appointment the therapist can see, for their calendar and inbox."""
    rows = store.conn.execute(
        "SELECT patient_id, id FROM appointments WHERE reschedule_requested = 1 AND status = 'scheduled' "
        "ORDER BY starts_at").fetchall()
    return [a for a in (store.appointment_get(r["id"]) for r in rows) if a is not None]
