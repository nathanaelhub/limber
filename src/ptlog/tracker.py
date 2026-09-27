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
    unread_messages: int = 0                  # from the patient, not yet opened by the therapist
    unreviewed_uploads: int = 0               # clips awaiting the therapist's review (feature 011)
    overdue_questionnaires: List[tuple] = field(default_factory=list)      # (instrument name, days overdue) (feature 013)
    unreviewed_voice_notes: int = 0           # spoken notes waiting to be heard (feature 014)


def _unreviewed_by_patient(store: SessionStore) -> dict:
    result: dict = {}
    for m in store.media_list(kind="clip", live_only=True):
        if m.reviewed_at is None:
            result.setdefault(m.patient_id, []).append(m)
    return result


def _overdue_questionnaires(store: SessionStore, patient: Patient, today) -> List[tuple]:
    """(name, days overdue) for each assigned questionnaire more than a week past due (feature 013).

    The name comes from the installed definition when there is one; an assignment whose file has been
    removed is left out, since the therapist cannot act on it from here."""
    from . import instruments as registry
    from . import questionnaires as qrules
    if patient.is_builtin:
        return []
    installed = registry.load().by_key
    overdue = []
    for a in store.assignments(patient.id):
        instrument = installed.get(a.instrument_key)
        if instrument is None:
            continue
        last = store.last_questionnaire_at(patient.id, a.instrument_key)
        due = qrules.next_due(a.interval, date.fromisoformat(a.start_date),
                              date.fromisoformat(last[:10]) if last else None)
        if qrules.is_overdue(due, today):
            overdue.append((instrument.name, (today - due).days))
    return overdue


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now()


def snapshot(store: SessionStore, patient: Patient, now: Optional[datetime] = None,
             thresholds: Optional[Thresholds] = None,
             per_exercise: Optional[dict] = None, unread_messages: Optional[int] = None,
             checkins: Optional[list] = None, unreviewed_uploads: Optional[int] = None) -> PatientSnapshot:
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
        flags=review._flags_from_sessions(store, patient.id, recent, now, thresholds, per_exercise, checkins),
        pending=store.pending_reviews(patient.id),
        latest_review=store.latest_review(patient.id),
        gap_days=thresholds.practice_gap, thresholds=thresholds,
        unread_messages=(store.messages_unread("patient", patient.id).get(patient.id, 0)
                         if unread_messages is None else unread_messages),
        unreviewed_uploads=(sum(1 for m in store.media_list(patient.id, "clip", live_only=True) if m.reviewed_at is None)
                            if unreviewed_uploads is None else unreviewed_uploads),
        overdue_questionnaires=_overdue_questionnaires(store, patient, today),
        unreviewed_voice_notes=sum(1 for m in store.media_list(patient.id, "voice", live_only=True)
                                   if m.reviewed_at is None),
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
    needs = (bool(open_flags) or bool(snap.pending) or (pct is not None and pct < threshold) or gap
             or snap.unread_messages > 0 or snap.unreviewed_uploads > 0 or bool(snap.overdue_questionnaires)
             or snap.unreviewed_voice_notes > 0)
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
        needs_attention=needs, unread_messages=snap.unread_messages, unreviewed_uploads=snap.unreviewed_uploads,
        overdue_questionnaires=len(snap.overdue_questionnaires),
        unreviewed_voice_notes=snap.unreviewed_voice_notes,
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
    unread = store.messages_unread("patient")
    checkins_all = store.entries_all("checkin")
    waiting_uploads = {pid: len(v) for pid, v in _unreviewed_by_patient(store).items()}
    rows: List[RosterRow] = []
    for patient in store.active_patients():
        snap = snapshot(store, patient, now, everyone[patient.id], by_exercise.get(patient.id, {}),
                        unread.get(patient.id, 0), checkins_all.get(patient.id, []), waiting_uploads.get(patient.id, 0))
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
    unread = store.messages_unread("patient")
    checkins_all = store.entries_all("checkin")
    waiting_uploads = {pid: len(v) for pid, v in _unreviewed_by_patient(store).items()}
    keyed = {kind: [] for kind in QUEUE_KINDS}
    for patient in store.active_patients():
        snap = snapshot(store, patient, now, everyone[patient.id], by_exercise.get(patient.id, {}),
                        unread.get(patient.id, 0), checkins_all.get(patient.id, []), waiting_uploads.get(patient.id, 0))
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
        if snap.unreviewed_uploads:
            n = snap.unreviewed_uploads
            keyed["new_uploads"].append((-n, QueueItem(
                "new_uploads", pid, f"uploads:{pid}", None, 0, f"{n} clip{'s' if n != 1 else ''} awaiting review from {pid}")))
        for name, days in snap.overdue_questionnaires:
            keyed["overdue_questionnaire"].append((-days, QueueItem(
                "overdue_questionnaire", pid, f"questionnaires:{pid}", None, days,
                f"{name} is {days} days overdue for {pid}")))
        if snap.unreviewed_voice_notes:
            n = snap.unreviewed_voice_notes
            keyed["new_voice_notes"].append((-n, QueueItem(
                "new_voice_notes", pid, f"inbox:{pid}", None, 0,
                f"{n} voice note{'s' if n != 1 else ''} to hear from {pid}")))
        if snap.unread_messages:
            n = snap.unread_messages
            keyed["unread_messages"].append((-n, QueueItem(
                "unread_messages", pid, f"inbox:{pid}", None, 0,
                f"{n} unread message{'s' if n != 1 else ''} from {pid}")))
        pct = snap.adherence.percentage
        if pct is not None and pct < threshold and snap.assignment is not None:
            keyed["low_adherence"].append((pct, QueueItem(
                "low_adherence", pid, f"adherence:{pid}", None, 0,
                f"Adherence {pct}% is below the {threshold}% threshold "
                f"({snap.assignment.program_name}, {snap.assignment.sessions_per_week} sessions/week)")))
    items = {kind: [it for _, it in sorted(keyed[kind], key=lambda x: (x[0], x[1].patient_id))] for kind in QUEUE_KINDS}
    return QueueResult(items=items, totals={kind: len(v) for kind, v in items.items()})
