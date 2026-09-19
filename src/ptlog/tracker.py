"""
Caseload views derived from the canonical record: roster rows, attention sort, filters,
adherence per patient, and the cross-patient queue (feature 003). Nothing is stored.

Each patient's sessions are loaded once for the widest window needed and reused for the
counts, the 30-day flags, and adherence (research D6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional

from . import adherence as adherence_mod
from . import review
from .models import Adherence, Assignment, FlagResult, Patient, QueueItem, QueueResult, Review, RosterRow, Session, SessionSummaryRow
from .store import SessionStore

FLAG_WINDOW_DAYS = 30
ADHERENCE_LOOKBACK_DAYS = 36     # four complete weeks plus the current one


@dataclass
class PatientSnapshot:
    patient: Patient
    rows: List[SessionSummaryRow]            # newest first, cheap
    sessions: List[Session]                  # full graphs inside the window, oldest first
    assignment: Optional[Assignment]
    adherence: Adherence
    flags: FlagResult
    pending: List[SessionSummaryRow]
    latest_review: Optional[Review]
    gap_days: int


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now()


def snapshot(store: SessionStore, patient: Patient, now: Optional[datetime] = None) -> PatientSnapshot:
    """One load of the patient's sessions, reused for counts, flags, and adherence."""
    now = _now(now)
    today = now.date()
    rows = store.list_sessions(patient.id)
    assignment = None if patient.is_builtin else store.active_assignment(patient.id, today)
    window_start = now - timedelta(days=FLAG_WINDOW_DAYS)
    if assignment is not None:
        window_start = min(window_start, now - timedelta(days=ADHERENCE_LOOKBACK_DAYS))
    sessions = store.sessions_in_period(patient.id, window_start) if rows else []
    recent_iso = (now - timedelta(days=FLAG_WINDOW_DAYS)).isoformat()
    recent = [s for s in sessions if s.start_time >= recent_iso]
    return PatientSnapshot(
        patient=patient, rows=rows, sessions=sessions, assignment=assignment,
        adherence=adherence_mod.compute(assignment, sessions, today),
        flags=review._flags_from_sessions(store, patient.id, recent, now),
        pending=store.pending_reviews(patient.id),
        latest_review=store.latest_review(patient.id),
        gap_days=store.get_gap_days(patient.id),
    )


def row_from_snapshot(snap: PatientSnapshot, now: datetime, threshold: int) -> RosterRow:
    last = snap.rows[0].start_time if snap.rows else None
    days_since = (now - datetime.fromisoformat(last)).days if last else None
    since7 = (now - timedelta(days=7)).isoformat()
    since30 = (now - timedelta(days=FLAG_WINDOW_DAYS)).isoformat()
    open_flags = [f for f in snap.flags.flags if f.rule != "practice_gap"]
    gap = (days_since is not None and days_since > snap.gap_days) or any(f.rule == "practice_gap" for f in snap.flags.flags)
    pct = snap.adherence.percentage
    program_name = snap.assignment.program_name if snap.assignment else "none"
    program_status = snap.adherence.status if snap.assignment else "none"
    needs = bool(open_flags) or bool(snap.pending) or (pct is not None and pct < threshold) or gap
    return RosterRow(
        patient_id=snap.patient.id, label=snap.patient.label, is_builtin=snap.patient.is_builtin,
        program_id=snap.assignment.program_id if snap.assignment else None,
        program_name=program_name, program_status=program_status,
        days_since_last=days_since,
        sessions_7d=sum(1 for r in snap.rows if r.start_time >= since7),
        sessions_30d=sum(1 for r in snap.rows if r.start_time >= since30),
        adherence_pct=pct, adherence_note=snap.adherence.note,
        pending_reviews=len(snap.pending), open_flags=len(open_flags), practice_gap=gap,
        last_next_step=snap.latest_review.next_step if snap.latest_review else None,
        needs_attention=needs,
    )


def attention_key(row: RosterRow) -> tuple:
    """More flags, then more pending, then lower adherence (no program last), then longer since last."""
    adherence_rank = row.adherence_pct if row.adherence_pct is not None else 101
    days = -row.days_since_last if row.days_since_last is not None else 1
    return (-row.open_flags, -row.pending_reviews, adherence_rank, days, row.patient_id)


def roster(store: SessionStore, now: Optional[datetime] = None, sort: str = "attention",
           program: Optional[str] = None, needs_attention: bool = False) -> List[RosterRow]:
    """Every active patient with the FR-001 columns; the built-in patient only when it holds sessions."""
    now = _now(now)
    threshold = store.get_adherence_threshold()
    rows: List[RosterRow] = []
    for patient in store.active_patients():
        snap = snapshot(store, patient, now)
        if patient.is_builtin and not snap.rows:
            continue
        rows.append(row_from_snapshot(snap, now, threshold))
    if program:
        rows = [r for r in rows if r.program_id == program]
    if needs_attention:
        rows = [r for r in rows if r.needs_attention]
    if sort == "id":
        rows.sort(key=lambda r: (not r.is_builtin, r.patient_id.lower()))
    else:
        rows.sort(key=attention_key)
    return rows


def adherence_for(store: SessionStore, patient_id: str, today: Optional[date] = None) -> Adherence:
    """Week-by-week adherence for one patient (FR-009 … FR-012)."""
    today = today or datetime.now().date()
    from .models import PatientNotFoundError
    if store.get_patient(patient_id) is None:
        raise PatientNotFoundError(f"Patient '{patient_id}' not found")
    assignment = store.active_assignment(patient_id, today)
    if assignment is None:
        return adherence_mod.compute(None, [], today)
    since = datetime.combine(date.fromisoformat(assignment.start_date), datetime.min.time())
    return adherence_mod.compute(assignment, store.sessions_in_period(patient_id, since), today)
