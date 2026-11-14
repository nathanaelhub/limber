"""The progress report (feature 021 N3, FR-010 to FR-012): what a therapist hands to a patient or a referrer.

This module only gathers: every number comes from the record's existing rules (the review summary, adherence, the
questionnaire grouping, the program catalog), and nothing is worked out here. It leaves out everything the patient
wrote in their own words (check-in notes, messages, transcripts, captions), so the report can leave the clinic.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from src.ptlog.store import SessionStore

PERIODS = (("4w", "Last 4 weeks", 28), ("12w", "Last 12 weeks", 84), ("plan", "This plan of care", None),
           ("all", "Everything", None))
DEFAULT = "12w"
LABELS = {k: label for k, label, _ in PERIODS}


def period_key(value) -> str:
    return value if value in LABELS else DEFAULT


def _plan(store: SessionStore, patient_id: str):
    plan = store.current_plan(patient_id)
    if plan is None:
        plans = store.plans(patient_id)
        plan = plans[-1] if plans else None
    return plan


def since_for(store: SessionStore, patient_id: str, key: str, now: datetime) -> Optional[datetime]:
    """Where the period starts; None for everything. "This plan of care" starts on the plan's first day."""
    days = dict((k, d) for k, _, d in PERIODS).get(key)
    if days:
        return now - timedelta(days=days)
    if key == "plan":
        plan = _plan(store, patient_id)
        if plan is not None:
            return datetime.combine(date.fromisoformat(plan.start_date[:10]), time.min, tzinfo=now.tzinfo)
    return None


def _in_period(stamp: str, since: Optional[datetime]) -> bool:
    return since is None or stamp[:19] >= since.replace(tzinfo=None).isoformat(timespec="seconds")


def build(store: SessionStore, patient_id: str, key: str, now: datetime) -> Dict[str, Any]:
    """Everything the report shows, from the existing rules. The caller has checked the patient is on the caseload."""
    from src.clinic import review as clinic_review
    from src.portal import viewmodels
    from src.ptlog import entries as entry_rules, instruments, review as ptreview, tracker

    key = period_key(key)
    since = since_for(store, patient_id, key, now)
    summary = ptreview.review_summary(store, patient_id, "all", now, since=since)
    checkins = [e for e in store.entries(patient_id, "checkin", newest_first=True, limit=500)
                if _in_period(e.recorded_at, since)]
    answers = [e for e in store.entries(patient_id, "questionnaire", newest_first=True, limit=500)
               if _in_period(e.recorded_at, since)]
    notes = []
    names: Dict[Optional[int], str] = {}
    for n in store.therapist_notes(patient_id):
        if not _in_period(n["created_at"], since):
            continue
        aid = n.get("account_id")
        if aid not in names:
            account = store.account_get(aid) if aid else None
            names[aid] = (account.display_name or account.username) if account else "a former staff member"
        notes.append({**n, "author": names[aid]})
    return {
        "patient_id": patient_id,
        "period": key,
        "period_label": LABELS[key],
        "since": since.date().isoformat() if since else None,
        "generated": now.strftime("%-d %b %Y, %H:%M"),
        "plan": _plan(store, patient_id),
        "program": viewmodels.program_exercises(store, patient_id, now.date()),
        "assignment": store.active_assignment(patient_id, now.date()),
        "trends": [t for t in summary.trends.values() if t.points],
        "goals": summary.goals,
        "pain": entry_rules.pain_series(checkins),
        "adherence": tracker.adherence_for(store, patient_id, now.date()),
        "questionnaires": clinic_review.questionnaire_groups(answers, instruments.load().by_key),
        "notes": notes,
    }

