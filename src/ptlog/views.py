"""
Presentation helpers shared by the CLI and the web app.

Every number shown to a clinician carries its unit (constitution V, FR-012). Interface
files call these functions and only render what they return.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import METRIC_DEFINITIONS, ExerciseSet, Session
from .store import SessionStore

NOT_AVAILABLE = "not available"


def metric_label(field: str) -> str:
    """'rom' -> 'ROM (degrees)'; the unit always comes from METRIC_DEFINITIONS."""
    unit = METRIC_DEFINITIONS[field]["unit"]
    pretty = {"rom": "ROM", "avg_rom": "avg ROM", "avg_form_score": "avg form score", "adherence_pct": "adherence"}.get(field, field.replace("_", " "))
    return f"{pretty} ({unit})"


def metric_definition(field: str) -> str:
    return METRIC_DEFINITIONS[field]["definition"]


def clock_time(ts: Optional[str]) -> str:
    """HH:MM:SS from an ISO timestamp."""
    if not ts:
        return "--:--:--"
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except ValueError:
        return ts[11:19]


def date_minute(ts: Optional[str]) -> str:
    """'2026-03-23 09:15' from an ISO timestamp."""
    return (ts or "")[:16].replace("T", " ")


def fmt_form(value: Optional[float]) -> str:
    return NOT_AVAILABLE if value is None else f"{value:.1f}/100"


def fmt_rom(value: Optional[float]) -> str:
    return NOT_AVAILABLE if value is None else f"{value:.1f}°"


def fmt_seconds(value: Optional[float]) -> str:
    return NOT_AVAILABLE if value is None else f"{value:.1f} s"


# ------------------------------------------------------------------ set-level statistics

def set_summary(es: ExerciseSet) -> Dict[str, Any]:
    """Per-set numbers over reps not flagged out of range (shared with the CSV export)."""
    reps = [r for r in es.reps if not r.out_of_range]
    n = len(reps)
    if n == 0:
        return {"reps": 0, "target_reps": es.target_reps, "avg_form_score": 0.0, "min_angle": 0.0,
                "max_angle": 0.0, "rom_range": 0.0, "avg_duration": 0.0, "avg_rom": 0.0}
    min_angle = min(r.min_angle for r in reps)
    max_angle = max(r.max_angle for r in reps)
    return {
        "reps": n,
        "target_reps": es.target_reps,
        "avg_form_score": sum(r.form_score for r in reps) / n,
        "min_angle": min_angle,
        "max_angle": max_angle,
        "rom_range": max_angle - min_angle,
        "avg_duration": sum(r.duration_seconds for r in reps) / n,
        "avg_rom": sum(r.rom for r in reps) / n,
    }


def legacy_flags(session: Session) -> List[str]:
    """The review flags the retired session tracker generated, plus the interrupted flag."""
    flags: List[str] = []
    for es in session.sets:
        st = set_summary(es)
        if st["avg_form_score"] < 60:
            flags.append(f"{es.exercise_name}: Low form score ({st['avg_form_score']:.0f}%)")
        if st["reps"] < st["target_reps"] * 0.5:
            flags.append(f"{es.exercise_name}: Completed only {st['reps']}/{st['target_reps']} reps")
    if session.status == "interrupted":
        flags.append("Session interrupted")
    return flags


# ------------------------------------------------------------------ rendering

def session_header_lines(session: Session) -> List[str]:
    src = f"{session.source} ({session.source_ref})" if session.source_ref else session.source
    lines = [
        f"Session {session.id} | patient {session.patient_id} | {src}",
        f"Started {date_minute(session.start_time)} | Ended {date_minute(session.end_time) or NOT_AVAILABLE} | "
        f"Duration {fmt_seconds(session.duration_seconds)}",
        f"Total reps {session.total_reps if session.total_reps is not None else 0} | "
        f"avg form {fmt_form(session.avg_form_score)} | avg ROM {fmt_rom(session.avg_rom)}",
        f"STATUS: {session.status}",
    ]
    return lines


def event_log_lines(store: SessionStore, session_id: int) -> List[str]:
    """One human-readable line per event, every metric with its unit; ends with STATUS."""
    session = store.load_session(session_id)
    lines: List[str] = []
    for row in store.event_log(session_id):
        d, t = row.data, clock_time(row.timestamp)
        if row.type == "session_start":
            lines.append(f"[{t}] SESSION START | {d['exercise']} ({d['side']}) | target {d['target_reps']} | {d['source']} {d['source_ref']}")
        elif row.type == "rep":
            flag = " | OUT OF RANGE" if d.get("out_of_range") else ""
            lines.append(f"[{t}] REP {d['rep_number']} | ROM {d['rom']:.1f}° | form {d['form_score']:.0f}/100 | "
                         f"{d['duration_seconds']:.1f} s | {d['min_angle']:.1f}°–{d['max_angle']:.1f}°{flag}")
        elif row.type == "partial_rep":
            lines.append(f"[{t}] PARTIAL REP | {d['reason']} | ROM {d['rom']:.1f}° | "
                         f"{d['min_angle']:.1f}°–{d['max_angle']:.1f}° | {d['duration_seconds']:.1f} s")
        elif row.type == "form":
            lines.append(f"[{t}] FORM {d['severity']} | {d['message']}")
        elif row.type == "switch":
            lines.append(f"[{t}] SWITCH | {d['from_exercise']} -> {d['to_exercise']}")
        elif row.type == "reset":
            lines.append(f"[{t}] RESET | {d['exercise']} | count {d['rep_count_at_reset']}")
        elif row.type == "session_end":
            label = "SESSION INTERRUPTED" if d.get("status") == "interrupted" else "SESSION END"
            lines.append(f"[{t}] {label} | {d['total_reps']} reps | avg form {fmt_form(d['avg_form_score'])} | "
                         f"avg ROM {fmt_rom(d['avg_rom'])} | {fmt_seconds(d['duration_seconds'])}")
    lines.append(f"STATUS: {session.status}")
    return lines


def session_table_rows(store: SessionStore, patient_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Rows for a history table, newest first."""
    return [
        {
            "id": r.id,
            "date": date_minute(r.start_time),
            "patient_id": r.patient_id,
            "source": r.source,
            "origin": r.origin,
            "exercises": ", ".join(r.exercises),
            "total_reps": r.total_reps if r.total_reps is not None else 0,
            "avg_form_score": fmt_form(r.avg_form_score),
            "status": r.status,
        }
        for r in store.list_sessions(patient_id)
    ]


# ------------------------------------------------------------------ web-app adapters

from dataclasses import dataclass  # noqa: E402


@dataclass
class SessionRef:
    """A session handle with the path-like attributes the web pages used for legacy files."""
    id: int
    patient_id: str
    start_time: str
    source: str
    status: str
    exercises: List[str]
    total_reps: Optional[int]
    avg_form_score: Optional[float]

    @property
    def stem(self) -> str:
        return f"session_{self.id}"

    @property
    def name(self) -> str:
        return f"session_{self.id}"

    def __str__(self) -> str:
        return str(self.id)


def session_refs(store: SessionStore, patient_id: Optional[str] = None) -> List[SessionRef]:
    """Sessions newest first as SessionRef handles."""
    return [SessionRef(r.id, r.patient_id, r.start_time, r.source, r.status, r.exercises, r.total_reps, r.avg_form_score)
            for r in store.list_sessions(patient_id)]


def observation_dict(store: SessionStore, session_id: int) -> Dict[str, Any]:
    """The legacy observation-log dict for a session (feeds session_summary and the pages)."""
    from .exports.observation_json import to_observation_dict  # local import avoids a module cycle
    return to_observation_dict(store.load_session(session_id))


# ------------------------------------------------------------------ review over time (feature 002)

MEASURE_ORDER = ("reps_completed", "avg_form", "avg_rom", "avg_duration", "tempo_sd", "partial_share")
MEASURE_SHORT = {"reps_completed": "reps", "avg_form": "avg form", "avg_rom": "avg ROM",
                 "avg_duration": "avg rep", "tempo_sd": "tempo sd", "partial_share": "partial"}
PERIOD_LABELS = {"14d": "last 2 weeks", "30d": "last month", "90d": "last 3 months", "all": "all time"}


def fmt_measure(name: str, value, target=None) -> str:
    """Format one measure with its unit; None becomes 'not available'."""
    if value is None:
        return NOT_AVAILABLE
    if name == "reps_completed":
        return f"{int(value)}/{int(target)}" if target is not None else str(int(value))
    if name == "avg_form":
        return f"{value:.1f}/100"
    if name == "avg_rom":
        return f"{value:.1f}°"
    if name in ("avg_duration", "tempo_sd"):
        return f"{value:.2f} s"
    if name == "partial_share":
        return f"{value:.1f}%"
    return str(value)


def fmt_change(name: str, change) -> str:
    if change is None:
        return NOT_AVAILABLE
    if name == "reps_completed":
        return f"{int(change):+d}"
    if name == "avg_form":
        return f"{change:+.1f}"
    if name == "avg_rom":
        return f"{change:+.1f}°"
    if name in ("avg_duration", "tempo_sd"):
        return f"{change:+.2f} s"
    if name == "partial_share":
        return f"{change:+.1f} pts"
    return str(change)


def trend_table_rows(trend) -> List[Dict[str, Any]]:
    """One dict per session point, values formatted with units."""
    return [
        {
            "date": date_minute(m.start_time),
            "session_id": m.session_id,
            "reps": fmt_measure("reps_completed", m.reps_completed, m.target_reps),
            "avg_form": fmt_measure("avg_form", m.avg_form),
            "avg_rom": fmt_measure("avg_rom", m.avg_rom),
            "avg_duration": fmt_measure("avg_duration", m.avg_duration),
            "tempo_sd": fmt_measure("tempo_sd", m.tempo_sd),
            "partial_share": fmt_measure("partial_share", m.partial_share),
            "status": m.status,
            "origin": m.origin,
        }
        for m in trend.points
    ]


def goal_line(goal, rom_progress_pct) -> Optional[str]:
    if goal is None:
        return None
    parts = []
    if goal.target_rom:
        pct = f" ({rom_progress_pct}% of goal)" if rom_progress_pct is not None else ""
        parts.append(f"ROM {goal.target_rom:g}°{pct}")
    if goal.target_reps:
        parts.append(f"reps {goal.target_reps}")
    return "Goal: " + " | ".join(parts)


ORIGIN_NOTE = ("Home and clinic sessions use different pose models, so their numbers are not compared "
               "with each other.")


def trend_summary_lines(trend) -> List[str]:
    """First → latest (change) per measure, plus the goal line when a goal exists. When the period
    holds both clinic and home sessions, one block per origin: changes never cross origins."""
    parts = getattr(trend, "by_origin", {}) or {}
    if len(parts) > 1:
        lines = [ORIGIN_NOTE]
        for origin, part in parts.items():
            lines.append(f"{origin.capitalize()} sessions ({len(part.points)}):")
            lines += ["  " + line for line in _summary_lines(part.points, part.summary, part.enough_for_trend,
                                                           trend.goal, part.rom_progress_pct)]
        return lines
    return _summary_lines(trend.points, trend.summary, trend.enough_for_trend, trend.goal, trend.rom_progress_pct)


def _summary_lines(points, summary, enough, goal, rom_progress_pct) -> List[str]:
    from types import SimpleNamespace
    trend = SimpleNamespace(points=points, summary=summary, enough_for_trend=enough, goal=goal,
                            rom_progress_pct=rom_progress_pct)
    lines: List[str] = []
    if not trend.enough_for_trend:
        lines.append("A trend needs at least two sessions.")
    else:
        first_target = trend.points[0].target_reps
        latest_target = trend.points[-1].target_reps
        for name in MEASURE_ORDER:
            s = trend.summary.get(name)
            if not s:
                continue
            if name == "reps_completed":
                first = fmt_measure(name, s["first"], first_target)
                latest = fmt_measure(name, s["latest"], latest_target)
            else:
                first, latest = fmt_measure(name, s["first"]), fmt_measure(name, s["latest"])
            lines.append(f"{MEASURE_SHORT[name]}: {first} → {latest} ({fmt_change(name, s['change'])})")
    g = goal_line(trend.goal, trend.rom_progress_pct)
    if g:
        lines.append(g)
    return lines


def measure_line(name: str, m) -> str:
    return (f"{name}: {fmt_measure('reps_completed', m.reps_completed, m.target_reps)} reps | "
            f"avg form {fmt_measure('avg_form', m.avg_form)} | avg ROM {fmt_measure('avg_rom', m.avg_rom)} | "
            f"avg rep {fmt_measure('avg_duration', m.avg_duration)} | tempo sd {fmt_measure('tempo_sd', m.tempo_sd)} | "
            f"partial {fmt_measure('partial_share', m.partial_share)}")


def review_status_line(review) -> str:
    if review is None:
        return "REVIEW: pending"
    return (f"REVIEW: reviewed {date_minute(review.reviewed_at)} | next step: {review.next_step} | "
            f"notes: {review.notes or ''}")


def review_lines(view: Dict[str, Any]) -> List[str]:
    """Review status, one measure line per exercise, and the per-session summary flags."""
    lines = [review_status_line(view.get("review"))]
    for name, m in view["measures"].items():
        lines.append(measure_line(name, m))
    summary = view.get("summary") or {}
    lines.append("Per-session summary:")
    flags = summary.get("key_flags") or []
    if not flags:
        lines.append("- no flags")
    for f in flags:
        lines.append(f"- [{f.get('severity', 'info')}] {f.get('message', '')}")
    for bullet in (summary.get("summary_text") or "").splitlines():
        if bullet.strip():
            lines.append(f"  {bullet.strip()}")
    return lines


def flag_lines(result) -> List[str]:
    """Flags with evidence, then the rules that could not be evaluated yet."""
    lines: List[str] = []
    if not result.flags:
        lines.append("Nothing needs attention.")
    for f in result.flags:
        lines.append(f"- [{f.rule}] {f.message}")
    if result.not_evaluated:
        lines.append("Not evaluated yet:")
        for n in result.not_evaluated:
            where = f" for {n.exercise}" if n.exercise else ""
            lines.append(f"  - {n.rule}{where} (needs {n.needed} sessions, has {n.have})")
    return lines


BETTER_TEXT = {"higher": "higher is better", "lower": "lower is better", "informational": "informational"}


def comparison_rows(comparison) -> List[Dict[str, Any]]:
    """One dict per measure with unit-formatted values, change, % change, and the better direction."""
    rows = []
    for r in comparison.rows:
        ta = comparison.a.target_reps if r.name == "reps_completed" else None
        tb = comparison.b.target_reps if r.name == "reps_completed" else None
        rows.append({
            "measure": metric_label(r.name),
            "a": fmt_measure(r.name, r.a, ta),
            "b": fmt_measure(r.name, r.b, tb),
            "change": fmt_change(r.name, r.change),
            "pct_change": NOT_AVAILABLE if r.pct_change is None else f"{r.pct_change:+.1f}%",
            "better": BETTER_TEXT[r.better],
        })
    return rows


# ------------------------------------------------------------------ tracker (feature 003)

def fmt_days(value) -> str:
    return "no sessions yet" if value is None else str(int(value))


def roster_columns() -> Dict[str, str]:
    return {
        "patient_id": "Patient", "label": "Label", "program": "Program", "program_status": "Program status",
        "days_since_last": "Days since last session (days)", "sessions_7d": "Sessions, last 7 days (count)",
        "sessions_30d": "Sessions, last 30 days (count)", "adherence": metric_label("adherence_pct"),
        "pending_reviews": "Pending reviews (count)", "open_flags": "Open flags (count)",
        "practice_gap": "Practice gap", "last_next_step": "Last next step", "needs_attention": "Needs attention",
    }


def roster_table_rows(rows) -> List[Dict[str, Any]]:
    return [{
        "patient_id": r.patient_id,
        "label": r.label or "",
        "program": r.program_name,
        "program_status": r.program_status,
        "days_since_last": fmt_days(r.days_since_last),
        "sessions_7d": r.sessions_7d,
        "sessions_30d": r.sessions_30d,
        "adherence": f"{r.adherence_pct}%" if r.adherence_pct is not None else r.adherence_note,
        "pending_reviews": r.pending_reviews,
        "open_flags": r.open_flags,
        "practice_gap": "yes" if r.practice_gap else "no",
        "last_next_step": r.last_next_step or "none",
        "needs_attention": "yes" if r.needs_attention else "no",
    } for r in rows]


def assignment_line(adh) -> str:
    a = adh.assignment
    span = f"from {a.start_date}" + (f" to {a.end_date}" if a.end_date else "")
    return f"{a.program_name} — {a.sessions_per_week} sessions/week {span} ({adh.status})"


def adherence_lines(adh) -> List[str]:
    """Assignment line, one line per week, and the percentage or note."""
    if adh.assignment is None:
        return ["No program assigned."]
    lines = [assignment_line(adh)]
    if adh.status == "superseded":
        return lines + ["Superseded by a later assignment; no adherence computed."]
    if adh.status == "scheduled":
        return lines + [f"Starts on {adh.assignment.start_date}; no adherence yet."]
    for w in adh.weeks:
        flag = "in progress" if w.in_progress else ("missed" if w.missed else "")
        parts = [f"week {w.index}", f"{w.start}..{w.end}", f"{w.recorded}/{w.planned}"] + ([flag] if flag else [])
        lines.append("  ".join(parts) + f" | performed: {', '.join(w.exercises_performed) or '—'} | "
                     f"missing: {', '.join(w.exercises_missing) or '—'}")
    complete = [w for w in adh.weeks if not w.in_progress]
    if adh.percentage is None:
        lines.append("First week in progress; adherence is computed after the first complete week.")
    else:
        suffix = f" ({adh.note})" if adh.note else ""
        lines.append(f"Adherence: {adh.percentage}% over {len(complete)} complete weeks{suffix}")
    return lines


def adherence_table_rows(adh) -> List[Dict[str, Any]]:
    return [{
        "week": w.index, "from": w.start, "to": w.end, "recorded": f"{w.recorded}/{w.planned}",
        "status": "in progress" if w.in_progress else ("missed" if w.missed else "done"),
        "performed": ", ".join(w.exercises_performed) or "—", "missing": ", ".join(w.exercises_missing) or "—",
    } for w in adh.weeks]


QUEUE_LABELS = {"pending_review": "Pending reviews", "attention_flag": "Attention flags",
                "practice_gap": "Practice gaps", "low_adherence": "Low adherence",
                "unread_messages": "Unread messages"}


def queue_lines(result) -> List[str]:
    if result.count == 0:
        return ["Caseload is up to date."]
    lines: List[str] = []
    for kind, items in result.items.items():
        if not items:
            continue
        lines.append(f"{QUEUE_LABELS[kind]} ({len(items)})")
        for it in items:
            lines.append(f"- {it.patient_id} | {it.description} | {it.target}")
    return lines


def live_summary_line(session: Session) -> str:
    """The one-line result shown on the live-session page when a stream stops (equals the stored summary)."""
    line = (f"Session {session.id}: {session.total_reps or 0} reps, avg form {fmt_form(session.avg_form_score)}, "
            f"avg ROM {fmt_rom(session.avg_rom)}, duration {fmt_seconds(session.duration_seconds)}")
    if session.status != "completed":
        line += f" | STATUS: {session.status}"
    return line


# ----------------------------------------------------------------------------- attention thresholds (feature 005)

def _origin_text(origin: str, default: int, builtin_only: bool = False) -> str:
    return "default" if origin == "default" else f"{origin}; default {default}"


def threshold_rows(effective, inherited=None, keys=None) -> List[Dict[str, Any]]:
    """One row per threshold. `inherited` is the set that would apply without the overrides being
    edited (for a patient: installation, else built-in; for an exercise: the patient's effective
    set); when omitted the built-in default is shown. `keys` limits the rows (exercise level)."""
    from .thresholds import THRESHOLDS
    rows = []
    for key, d in THRESHOLDS.items():
        if keys is not None and key not in keys:
            continue
        default = inherited.value(key) if inherited is not None else d.default
        rows.append({"key": key, "name": d.name, "value": effective.value(key), "unit": d.unit,
                     "origin": effective.origin(key), "default": default, "meaning": d.meaning,
                     "minimum": d.minimum, "maximum": d.maximum})
    return rows


def threshold_lines(effective, inherited=None, keys=None) -> List[str]:
    return [f"{r['name']}: {r['value']} {r['unit']} ({_origin_text(r['origin'], r['default'])}) - {r['meaning']}"
            for r in threshold_rows(effective, inherited, keys)]


def history_rows(changes) -> List[Dict[str, Any]]:
    """Threshold changes, as given (newest first): when, what it applies to, which threshold, old → new."""
    from .thresholds import THRESHOLDS
    rows = []
    for c in changes:
        d = THRESHOLDS.get(c.key)
        show = lambda v: "default" if v is None else str(v)  # noqa: E731
        rows.append({
            "when": c.changed_at[:16].replace("T", " "),
            "applies_to": c.exercise_name if c.scope == "exercise" else c.scope,
            "threshold": d.name if d else c.key,
            "change": f"{show(c.old_value)} → {show(c.new_value)} {d.unit if d else ''}".rstrip(),
        })
    return rows


def history_lines(changes) -> List[str]:
    rows = history_rows(changes)
    if not rows:
        return ["No threshold changes recorded."]
    return [f"{r['when']} | {r['applies_to']} | {r['threshold']}: {r['change']}" for r in rows]


def adherence_threshold_line(effective) -> str:
    """The adherence threshold in use for a patient and where it comes from."""
    return f"Attention threshold: {effective.value('adherence')}% ({effective.origin('adherence')})"
