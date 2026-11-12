"""The clinic Patients page's rules (feature 019 slice 3a, Story 3), moved out of the Streamlit page and tested
without a server: the list rows and their status line, the header under the patient code, the three facts at the
top of Overview, which plan actions are allowed, the questionnaire rows, the program history and home access.

Every function takes a store already limited to the therapist's caseload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from src.portal import plans as ptplans
from src.ptlog.models import Plan
from src.ptlog.store import SessionStore

PLAN_STATUS = {"active": "Open", "completed": "Completed", "archived": "Archived (read-only)"}


@dataclass
class Row:
    patient_id: str
    title: str                  # the open plan's title, else the label
    status: str                 # one short line under it
    warn: bool = False          # the status needs attention (shown with words, never colour alone)
    discharged: bool = False
    label: str = ""             # the staff label, for search only

    @property
    def href(self) -> str:
        return f"/therapist/patients/{self.patient_id}"


def _ago(days: int) -> str:
    if days <= 0:
        return "started today"
    if days < 14:
        return f"started {days} day{'s' if days != 1 else ''} ago"
    return f"started {days // 7} weeks ago"


def header(store: SessionStore, patient_id: str, today: date) -> str:
    """The line under the patient code: the open plan, when it started, and any other open plans."""
    live = [p for p in store.plans(patient_id) if p.status == "active"]
    if not live:
        return "No open plan of care."
    first = live[0]
    line = f"{first.title} · {_ago((today - date.fromisoformat(first.start_date[:10])).days)}"
    if len(live) > 1:
        line += " · Also: " + ", ".join(p.title for p in live[1:])
    return line


def pain(store: SessionStore, patient_id: str) -> Optional[dict]:
    """The latest pain at check-in and its change from a week before it: {"score", "change", "words"}."""
    pains = [e for e in store.entries(patient_id, kind="checkin") if e.score is not None]
    if not pains:
        return None
    latest = pains[-1]
    week_before = (datetime.fromisoformat(latest.recorded_at[:19]) - timedelta(days=7)).isoformat()
    before = [e for e in pains if e.recorded_at < week_before]
    change, words = None, None
    if before:
        change = latest.score - before[-1].score
        words = (f"Up {change:g} from last week" if change > 0 else f"Down {-change:g} from last week"
                 if change < 0 else "Same as last week")
    return {"score": latest.score, "change": change, "words": words}


def facts(store: SessionStore, patient_id: str, now: datetime) -> dict:
    """Days done in the last 7, the latest pain with its change, and the next visit."""
    since = (now - timedelta(days=7)).isoformat()
    days = {r.start_time[:10] for r in store.list_sessions(patient_id) if r.start_time >= since}
    upcoming = [v for v in ptplans.appointments_view(store, patient_id) if v["state"] == "upcoming"]
    visit = None
    if upcoming:
        v = upcoming[0]
        visit = {"when": datetime.fromisoformat(v["starts_local"]).strftime("%a %-d %b, %H:%M"),
                 "detail": f"{v['minutes']} minutes" + (f" · {v['note']}" if v["note"] else "")}
    return {"days_done": len(days), "pain": pain(store, patient_id), "visit": visit}


def rows(store: SessionStore, now: datetime) -> List[Row]:
    """Every patient on the caseload, most in need first; discharged patients last."""
    from src.assist import assistant
    out = []
    for p in store.list_patients():
        if p.is_builtin:
            continue
        live = [pl for pl in store.plans(p.id) if pl.status == "active"]
        title = live[0].title if live else (p.label or "")
        if store.get_discharge(p.id) is not None:
            out.append(Row(p.id, title, label=p.label or "", status="Discharged", discharged=True))
            continue
        if assistant.needs_attention(store, p.id):
            out.append(Row(p.id, title, label=p.label or "", status="! Urgent message", warn=True))
            continue
        hurt = pain(store, p.id)
        if hurt and hurt["change"] is not None and hurt["change"] > 0:
            out.append(Row(p.id, title, label=p.label or "", status="↑ Pain rising", warn=True))
            continue
        last = p.last_session_at
        entries = store.entries(p.id, newest_first=True, limit=1)
        latest = max([x for x in (last, entries[0].recorded_at if entries else None) if x], default=None)
        if latest is None:
            out.append(Row(p.id, title, label=p.label or "", status="New · No records yet"))
            continue
        idle = (now.date() - date.fromisoformat(latest[:10])).days
        out.append(Row(p.id, title, label=p.label or "", status=f"Inactive {idle // 7} weeks" if idle >= 14
                       else "Last active " + datetime.fromisoformat(latest[:19]).strftime("%-d %b")))
    out.sort(key=lambda r: (r.discharged, not r.warn, r.patient_id))
    return out


def search(rows: List[Row], query: str) -> List[Row]:
    """Patients whose code, plan title or staff label contains the text, ignoring case."""
    q = query.strip().lower()
    return [r for r in rows if q and (q in r.patient_id.lower() or q in r.title.lower() or q in r.label.lower())]


def plan_actions(plan: Plan) -> List[str]:
    """What can be done to a plan: an open plan is edited or completed; a completed one is edited, reopened or
    archived; an archived plan is read-only."""
    return {"active": ["edit", "complete"], "completed": ["edit", "reopen", "archive"]}.get(plan.status, [])


def questionnaire_rows(store: SessionStore, patient_id: str, installed, today: date) -> List[dict]:
    from src.ptlog import questionnaires as qrules
    out = []
    for a in store.assignments(patient_id):
        instrument = installed.by_key.get(a.instrument_key)
        answered = store.last_questionnaire_at(patient_id, a.instrument_key)
        due = qrules.next_due(a.interval, date.fromisoformat(a.start_date),
                              date.fromisoformat(answered[:10]) if answered else None)
        out.append({"id": a.id, "name": instrument.name if instrument else f"{a.instrument_key} (file not installed)",
                    "how_often": qrules.interval_words(a.interval),
                    "last": answered[:10] if answered else "not yet",
                    "next": due.isoformat() if due else "nothing more due",
                    "overdue": bool(due and qrules.is_overdue(due, today)),
                    "notice": instrument.notice if instrument else ""})
    return out


def program_rows(store: SessionStore, patient_id: str, today: date) -> List[dict]:
    from src.ptlog import adherence, programs
    return [{"name": h.program_name, "from": h.start_date, "to": h.end_date or "open",
             "status": adherence.assignment_status(h, today), "per_week": h.sessions_per_week,
             "exercises": ", ".join(programs.exercise_name(k) for k in h.exercise_keys)}
            for h in store.assignment_history(patient_id)]


def access_line(status) -> str:
    """Home access in one line; the code itself is never stored, so it is never shown again."""
    if status.state == "active":
        line = f"Access code in use until {status.expires_at[:10]}"
    else:
        line = {"none": "No access code yet", "expired": "The access code has expired",
                "revoked": "The access code was revoked"}.get(status.state, status.state)
    if status.last_used_at:
        line += f" · Last used {status.last_used_at[:16].replace('T', ' ')}"
    return line


def medication_lines(text) -> List[str]:
    if not isinstance(text, str):
        return []
    return [line for line in text.splitlines() if line.strip()]
