"""The clinic Review page's rules (feature 019 slice 5b, T026), moved out of the Streamlit page and tested without a
server. The record's own review, flag and threshold modules do the clinical work; this module holds what the page
decided on its own: which choices to offer, when a threshold is stored, how a goal is cleared, how answers are
grouped, and that every id in a request belongs to the patient in the address.

Three behaviours were wrong in Streamlit and are fixed here:
- Compare found shared exercises by splitting a display string on ", "; it now reads the sessions' sets.
- A goal target set to 0 ("none") kept its old value; it now removes that target.
- A questionnaire with an answer lacking a total broke its chart (dates and totals of different lengths).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.clinic.inbox import NotYours
from src.ptlog import review as ptreview
from src.ptlog import thresholds as ptthresholds
from src.ptlog.models import PERIODS, PTLogError, SessionNotFoundError
from src.ptlog.store import SessionStore

SECTIONS = (("trends", "Trends"), ("flags", "Flags"), ("compare", "Compare"), ("session", "Session review"),
            ("from-patient", "From the patient"), ("goals", "Goals and thresholds"), ("export", "Export"))
SECTION_KEYS = {k for k, _ in SECTIONS}
WHOLE_PATIENT = "Whole patient"


def period(value) -> str:
    return value if value in PERIODS else "all"


# ----------------------------------------------------------------------------- ownership

def own_session(store: SessionStore, patient_id: str, session_id) -> int:
    """A session id from a request, only when it is this patient's (the caseload limit is already applied)."""
    try:
        sid = int(session_id)
        session = store.load_session(sid)
    except (TypeError, ValueError, SessionNotFoundError):
        raise NotYours() from None
    if session.patient_id != patient_id:
        raise NotYours()
    return sid


def own_entry(store: SessionStore, patient_id: str, entry_id, kind: str = "checkin"):
    try:
        wanted = int(entry_id)
    except (TypeError, ValueError):
        raise NotYours() from None
    for e in store.entries(patient_id, kind):
        if e.id == wanted:
            return e
    raise NotYours()


def own_clip(store: SessionStore, patient_id: str, media_id):
    from src.portal import uploads
    m = uploads.get_media(store, patient_id, media_id if isinstance(media_id, str) else "")
    if m is None or m.kind != "clip":
        raise NotYours()
    return m


# ----------------------------------------------------------------------------- compare

def shared_exercises(store: SessionStore, session_a: int, session_b: int) -> List[str]:
    """Exercises both sessions recorded, from their sets (not from a joined display string)."""
    def names(sid: int) -> List[str]:
        seen: List[str] = []
        for s in store.load_session(sid).sets:
            if s.exercise_name not in seen:
                seen.append(s.exercise_name)
        return seen
    b = set(names(session_b))
    return [n for n in names(session_a) if n in b]


# ----------------------------------------------------------------------------- thresholds

def threshold_scopes(store: SessionStore, patient_id: str) -> List[str]:
    """The whole patient, then every exercise the patient recorded or has an override for."""
    names = set(ptreview.exercise_names(store, patient_id)) | set(store.get_exercise_thresholds(patient_id))
    return [WHOLE_PATIENT] + sorted(names)


def threshold_context(store: SessionStore, patient_id: str, exercise: Optional[str]):
    """(effective, inherited, overrides, keys): what applies now, what would apply without these overrides, the
    overrides themselves, and the keys this scope edits (an exercise edits only the per-exercise ones)."""
    effective = store.effective_thresholds(patient_id, exercise)
    if exercise:
        inherited = store.effective_thresholds(patient_id)
        overrides = store.get_exercise_thresholds(patient_id).get(exercise, {})
        keys = ptthresholds.EXERCISE_KEYS
    else:
        inherited = ptthresholds.resolve(None, store.get_installation_thresholds())
        overrides = store.get_patient_thresholds(patient_id)
        keys = None
    return effective, inherited, overrides, keys


def thresholds_to_store(entered: Dict[str, int], inherited, overrides: Dict[str, int]) -> Dict[str, int]:
    """Store a value only when it differs from what would be inherited, or when it already is an override (so
    setting an override back to the inherited value keeps it stored, as before)."""
    return {k: int(v) for k, v in entered.items() if int(v) != inherited.value(k) or k in overrides}


def threshold_values(body: dict, rows: List[dict]) -> Dict[str, int]:
    """The entered values, each a whole number within its threshold's limits."""
    out = {}
    for r in rows:
        value = body.get(r["key"])
        if value is None or isinstance(value, bool):
            raise PTLogError(f"Give a value for {r['name']}.")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise PTLogError(f"{r['name']} must be a whole number.") from None
        if not r["minimum"] <= number <= r["maximum"]:
            raise PTLogError(f"{r['name']} must be from {r['minimum']} to {r['maximum']} {r['unit']}.")
        out[r["key"]] = number
    return out


def saved_message(changed: Dict[str, int]) -> str:
    return ("Thresholds saved." if changed else
            "Nothing to save: every value already matches what it would inherit.")


# ----------------------------------------------------------------------------- goals

def update_goal(store: SessionStore, patient_id: str, exercise: str, rom, reps) -> Optional[object]:
    """Set the goal; 0 (or empty) removes that target, and both at 0 removes the goal."""
    def clean(value, top: int, name: str) -> Optional[int]:
        if value in (None, "", 0):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise PTLogError(f"{name} must be a whole number.") from None
        if not 0 <= number <= top:
            raise PTLogError(f"{name} must be from 0 to {top}.")
        return number or None
    target_rom, target_reps = clean(rom, 180, "Target range of motion"), clean(reps, 200, "Target reps")
    if exercise not in ptreview.exercise_names(store, patient_id):
        raise PTLogError("Choose an exercise this patient has recorded.")
    store.clear_goal(patient_id, exercise)            # set_goal keeps a target it is given None for
    if target_rom is None and target_reps is None:
        return None
    return store.set_goal(patient_id, exercise, target_rom=target_rom, target_reps=target_reps)


# ----------------------------------------------------------------------------- from the patient

def around(entry) -> str:
    return {"before": f"before session {entry.session_id}",
            "after": f"after session {entry.session_id}"}.get(entry.phase, "on its own")


def pain_flags(store: SessionStore, patient_id: str) -> List:
    """Pain rising and high pain, from the check-ins alone (no need to load every session)."""
    from src.ptlog import flags
    checkins = store.entries(patient_id, "checkin")
    return [f for f in flags.pain_rules(checkins, store.effective_thresholds(patient_id)) if hasattr(f, "message")]


def questionnaire_groups(entries, installed) -> List[dict]:
    """Answers by questionnaire, newest first, with the stored scores (nothing rescored) and the change from the
    first to the latest total in the direction the questionnaire wants."""
    from src.ptlog import questionnaires as qrules
    groups: Dict[str, List] = {}
    for e in entries:
        groups.setdefault(e.payload.get("instrument", "?"), []).append(e)
    out = []
    for key, answers in groups.items():
        snap = answers[0].payload.get("snapshot") or {}
        higher_better = snap.get("direction") == "higher_is_better"
        subscales = {s["key"]: s["name"] for s in snap.get("subscales", [])}
        rows = []
        for e in answers:
            row = {"id": e.id, "when": e.recorded_at[:16].replace("T", " ") + (" (time adjusted)" if e.time_adjusted else ""),
                   "total": e.payload.get("total"), "missing": e.payload.get("missing", 0),
                   "subscales": [(subscales[k], (e.payload.get("subscales") or {}).get(k)) for k in subscales]}
            rows.append(row)
        scored = [(e.recorded_at[:10], e.payload.get("total")) for e in reversed(answers)
                  if e.payload.get("total") is not None]          # dates and totals stay paired
        change = None
        if len(scored) >= 2:
            delta = round(scored[-1][1] - scored[0][1], 1)
            verdict = ("no change" if not delta else
                       "the direction you want" if (delta > 0) == higher_better else "not the direction you want")
            change = f"First to latest: {scored[0][1]:g} → {scored[-1][1]:g} ({delta:+g} {snap.get('unit', '')}), {verdict}."
        now = installed.get(key)
        version_note = None
        if qrules.differs_from_installed(snap, now):
            said = f"is now version {now.version}" if now else "is no longer installed"
            version_note = (f"Answered under version {snap.get('version')}; the definition {said}. The scores are the "
                            "ones worked out at the time; nothing has been rescored.")
        out.append({"key": key, "name": snap.get("name") or answers[0].payload.get("name") or key,
                    "unit": snap.get("unit", ""), "meaning": snap.get("meaning", ""), "notice": snap.get("notice"),
                    "direction": "a higher score is better" if higher_better else "a higher score is worse",
                    "version_note": version_note, "subscale_names": list(subscales.values()), "rows": rows,
                    "series": scored, "change": change, "answers": answers})
    return out


def diary_rows(store: SessionStore, patient_id: str) -> List[dict]:
    from src.portal import diary
    from src.ptlog.origin import DIARY, capture_origin
    sessions = [s for s in store.sessions_in_period(patient_id, None) if capture_origin(s) == DIARY]
    rows = []
    for s in sorted(sessions, key=lambda x: x.start_time, reverse=True)[:100]:
        first = s.sets[0] if s.sets else None
        note = diary.note_of(s)
        rows.append({"when": s.start_time[:16].replace("T", " "), "exercise": first.exercise_name if first else "",
                     "reported": f"{first.reported_sets or 1} × {first.reported_reps or 0} reps" if first else "",
                     "total": s.total_reps,
                     "effort": (f"{first.effort} {dict(diary.EFFORT).get(first.effort, '')}".strip()
                                if first and first.effort else ""),
                     "note": note["note"] + (" · sent after a privacy warning" if note["warned"] else "")})
    return rows


def export_names(patient_id: str, period_key: str, generated_at: str) -> Dict[str, str]:
    stamp = datetime.fromisoformat(generated_at[:19]).strftime("%Y%m%d_%H%M%S")
    return {"report": f"{patient_id}_review_{period_key}_{stamp}.txt",
            "csv": f"{patient_id}_review_{period_key}_{stamp}.csv",
            "questionnaires": f"{patient_id}_questionnaires_{period_key}_{stamp}.csv"}


def session_choices(store: SessionStore, patient_id: str) -> List[Tuple[int, str]]:
    from src.ptlog import views
    return [(r["id"], f"#{r['id']} · {r['date']} · {r['exercises']} · {r['total_reps']} reps · {r['status']}")
            for r in views.session_table_rows(store, patient_id)]
