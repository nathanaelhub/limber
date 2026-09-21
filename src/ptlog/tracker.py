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
from .thresholds import Thresholds

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
    thresholds: Optional[Thresholds] = None   # the patient's effective attention thresholds


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now()


def snapshot(store: SessionStore, patient: Patient, now: Optional[datetime] = None,
             thresholds: Optional[Thresholds] = None,
             per_exercise: Optional[dict] = None) -> PatientSnapshot:
    """One load of the patient's sessions, reused for counts, flags, and adherence."""
    now = _now(now)
    today = now.date()
    if thresholds is None:
        thresholds = store.effective_thresholds(patient.id)
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
        flags=review._flags_from_sessions(store, patient.id, recent, now, thresholds, per_exercise),
        pending=store.pending_reviews(patient.id),
        latest_review=store.latest_review(patient.id),
        gap_days=thresholds.practice_gap, thresholds=thresholds,
    )


def row_from_snapshot(snap: PatientSnapshot, now: datetime, threshold: Optional[int] = None) -> RosterRow:
    """`threshold` overrides the patient's effective adherence threshold (kept for older callers)."""
    if threshold is None:
        threshold = snap.thresholds.adherence
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
    everyone = store.effective_thresholds_all()
    by_exercise = store.effective_thresholds_by_exercise_all()
    rows: List[RosterRow] = []
    for patient in store.active_patients():
        snap = snapshot(store, patient, now, everyone[patient.id], by_exercise.get(patient.id, {}))
        if patient.is_builtin and not snap.rows:
            continue
        rows.append(row_from_snapshot(snap, now))
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


# ------------------------------------------------------------------ queue (US4)

def queue(store: SessionStore, now: Optional[datetime] = None) -> QueueResult:
    """Everything needing the PT's action across active patients, oldest first per kind (FR-013)."""
    from .models import QUEUE_KINDS
    now = _now(now)
    everyone = store.effective_thresholds_all()
    by_exercise = store.effective_thresholds_by_exercise_all()
    keyed = {kind: [] for kind in QUEUE_KINDS}
    for patient in store.active_patients():
        snap = snapshot(store, patient, now, everyone[patient.id], by_exercise.get(patient.id, {}))
        threshold = snap.thresholds.adherence
        if patient.is_builtin and not snap.rows:
            continue
        pid = patient.id
        starts = {s.id: s.start_time for s in snap.sessions}
        for row in snap.pending:
            age = (now - datetime.fromisoformat(row.start_time)).days
            desc = (f"Session {row.id} on {row.start_time[:10]} ({', '.join(row.exercises) or 'no exercise'}, "
                    f"{row.total_reps or 0} reps) awaits review")
            keyed["pending_review"].append((-age, QueueItem("pending_review", pid, f"session:{row.id}", row.id, age, desc)))
        gap_value: Optional[int] = None
        for f in snap.flags.flags:
            if f.rule == "practice_gap":
                gap_value = max(gap_value or 0, int(f.values.get("days", 0)))
                continue
            earliest = min((starts[i] for i in f.session_ids if i in starts), default=None)
            age = (now - datetime.fromisoformat(earliest)).days if earliest else 0
            keyed["attention_flag"].append((-age, QueueItem("attention_flag", pid, f"flags:{pid}", None, age, f"[{f.rule}] {f.message}")))
        last = snap.rows[0].start_time if snap.rows else None
        days_since = (now - datetime.fromisoformat(last)).days if last else None
        if days_since is not None and days_since > snap.gap_days:
            gap_value = max(gap_value or 0, days_since)
        if gap_value:
            keyed["practice_gap"].append((-gap_value, QueueItem(
                "practice_gap", pid, f"flags:{pid}", None, gap_value,
                f"{gap_value} days since the last session (threshold {snap.gap_days} days)")))
        pct = snap.adherence.percentage
        if pct is not None and pct < threshold and snap.assignment is not None:
            keyed["low_adherence"].append((pct, QueueItem(
                "low_adherence", pid, f"adherence:{pid}", None, 0,
                f"Adherence {pct}% is below the {threshold}% threshold "
                f"({snap.assignment.program_name}, {snap.assignment.sessions_per_week} sessions/week)")))
    items = {kind: [it for _, it in sorted(keyed[kind], key=lambda x: (x[0], x[1].patient_id))] for kind in QUEUE_KINDS}
    return QueueResult(items=items, totals={kind: len(v) for kind, v in items.items()})
