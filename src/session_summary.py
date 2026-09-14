"""
Session Summary Generator for AI Physical Therapy Assistant
============================================================

Analyzes a session observation log and produces a structured clinical summary,
including key flags (long pauses, declining form, exercise switches, ROM
anomalies) and aggregate metrics.

Usage:
    from src.session_summary import generate_session_summary
    from src.ptlog.exports import to_observation_dict  # feeds this module the legacy dict shape

    data = load_observation_log("observation_logs/session_2026-03-23_234321.json")
    summary = generate_session_summary(data)

    print(summary["summary_text"])      # human-readable bullets
    for flag in summary["key_flags"]:
        print(flag["severity"], flag["message"])
    print(summary["metrics"])
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────
# Thresholds (seconds / percentage points)
# ─────────────────────────────────────────────
LONG_PAUSE_SEC = 20          # gap between reps that triggers a "long pause" flag
REST_PERIOD_SEC = 15         # gap that counts as any rest period
FORM_DECLINE_THRESHOLD = 8   # % drop (first half avg → second half avg) → fatigue flag
ROM_ANOMALY_SIGMA = 1.2      # standard deviations from mean → notable ROM flag


# =============================================================================
# PUBLIC API
# =============================================================================

def generate_session_summary(log_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyse a session log dict and return a clinical summary.

    Args:
        log_data: A session log dictionary as produced by ObservationLogger.

    Returns:
        {
            "summary_text": str  — newline-separated bullet points,
            "key_flags":   list  — list of flag dicts (severity, category, message),
            "metrics":     dict  — aggregate session metrics,
        }
    """
    events = log_data.get("events", [])
    rep_events = [e for e in events if e.get("type") == "rep"]
    exercise_changes = [e for e in events if e.get("type") == "exercise_change"]

    # ── Basic metrics ──────────────────────────────────────────────────────────
    metrics = _compute_metrics(log_data, rep_events)

    # ── Detect observations ────────────────────────────────────────────────────
    flags: List[Dict[str, Any]] = []
    flags += _detect_long_pauses(rep_events)
    flags += _detect_exercise_switches(exercise_changes, rep_events)
    flags += _detect_form_decline(rep_events)
    flags += _detect_rom_anomalies(rep_events)
    flags += _detect_rest_periods(rep_events)
    flags += _detect_consistent_form(rep_events)

    # ── Build human-readable summary text ─────────────────────────────────────
    summary_text = _build_summary_text(metrics, flags)

    return {
        "summary_text": summary_text,
        "key_flags": flags,
        "metrics": metrics,
    }


# =============================================================================
# METRICS
# =============================================================================

def _compute_metrics(
    log_data: Dict[str, Any],
    rep_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate session-level metrics from the log."""

    start_time_str = log_data.get("start_time")
    end_time_str = log_data.get("end_time")

    session_start_dt = _parse_ts(start_time_str)
    session_end_dt = _parse_ts(end_time_str)

    # Prefer wall-clock duration from start/end; fall back to rep timestamps
    if session_start_dt and session_end_dt:
        session_duration_sec = (session_end_dt - session_start_dt).total_seconds()
    elif rep_events:
        first_ts = _parse_ts(rep_events[0].get("timestamp"))
        last_ts = _parse_ts(rep_events[-1].get("timestamp"))
        session_duration_sec = (
            (last_ts - first_ts).total_seconds() if first_ts and last_ts else 0.0
        )
    else:
        session_duration_sec = 0.0

    # Per-exercise breakdown
    reps_per_exercise: Dict[str, int] = {}
    for rep in rep_events:
        ex = rep.get("exercise", "Unknown")
        reps_per_exercise[ex] = reps_per_exercise.get(ex, 0) + 1

    form_scores = [r.get("form_score", 0) for r in rep_events if r.get("form_score") is not None]
    roms = [r.get("rom", 0) for r in rep_events if r.get("rom") is not None]

    avg_form = round(sum(form_scores) / len(form_scores), 1) if form_scores else 0.0
    avg_rom = round(sum(roms) / len(roms), 1) if roms else 0.0

    # Count rest periods (gaps > REST_PERIOD_SEC)
    rest_count = 0
    total_rest_sec = 0.0
    for i in range(1, len(rep_events)):
        gap = _gap_seconds(rep_events[i - 1], rep_events[i])
        if gap is not None and gap > REST_PERIOD_SEC:
            rest_count += 1
            total_rest_sec += gap

    # Active time = session duration minus all rest time
    active_time_sec = max(0.0, session_duration_sec - total_rest_sec)

    return {
        "session_id": log_data.get("session_id", ""),
        "source": log_data.get("source", "unknown"),
        "start_time": start_time_str,
        "end_time": end_time_str,
        "session_duration_seconds": round(session_duration_sec, 1),
        "active_time_seconds": round(active_time_sec, 1),
        "total_reps": len(rep_events),
        "exercises_performed": list(reps_per_exercise.keys()),
        "reps_per_exercise": reps_per_exercise,
        "avg_form_score": avg_form,
        "avg_rom": avg_rom,
        "rest_period_count": rest_count,
        "total_rest_seconds": round(total_rest_sec, 1),
    }


# =============================================================================
# FLAG DETECTORS
# =============================================================================

def _detect_long_pauses(rep_events: List[Dict]) -> List[Dict]:
    """Flag gaps between consecutive reps that exceed LONG_PAUSE_SEC."""
    flags = []
    for i in range(1, len(rep_events)):
        prev = rep_events[i - 1]
        curr = rep_events[i]
        gap = _gap_seconds(prev, curr)
        if gap is not None and gap >= LONG_PAUSE_SEC:
            prev_ex = prev.get("exercise", "?")
            curr_ex = curr.get("exercise", "?")
            prev_rep = prev.get("rep_number", i)
            curr_rep = curr.get("rep_number", i + 1)
            gap_int = int(round(gap))
            # Label exercise name for context
            if prev_ex == curr_ex:
                label = f"{prev_ex} rep {prev_rep} and rep {curr_rep}"
            else:
                label = f"{prev_ex} rep {prev_rep} and {curr_ex} rep {curr_rep}"
            flags.append({
                "severity": "warning",
                "category": "long_pause",
                "message": (
                    f"⚠️ {gap_int}-second pause between {label} — "
                    "patient may need encouragement or rest"
                ),
                "gap_seconds": gap_int,
                "between_reps": (prev_rep, curr_rep),
                "exercises": (prev_ex, curr_ex),
            })
    return flags


def _detect_exercise_switches(
    exercise_changes: List[Dict],
    rep_events: List[Dict],
) -> List[Dict]:
    """Flag exercise switches with context about which rep they followed."""
    flags = []
    for change in exercise_changes:
        from_ex = change.get("from_exercise", "?")
        to_ex = change.get("to_exercise", "?")
        ts = _parse_ts(change.get("timestamp"))

        # Count reps of from_exercise completed before this change
        reps_before = sum(
            1 for r in rep_events
            if r.get("exercise") == from_ex
            and (_parse_ts(r.get("timestamp")) or datetime.min) <= (ts or datetime.min)
        )

        # Elapsed time into session at switch
        elapsed_label = ""
        if ts and rep_events:
            first_ts = _parse_ts(rep_events[0].get("timestamp"))
            if first_ts:
                elapsed = (ts - first_ts).total_seconds()
                elapsed_label = f" at {_fmt_duration(elapsed)}"

        flags.append({
            "severity": "info",
            "category": "exercise_switch",
            "message": (
                f"🔄 Switched from {from_ex} to {to_ex} "
                f"after {reps_before} rep{'s' if reps_before != 1 else ''}{elapsed_label}"
            ),
            "from_exercise": from_ex,
            "to_exercise": to_ex,
            "reps_completed": reps_before,
        })
    return flags


def _detect_form_decline(rep_events: List[Dict]) -> List[Dict]:
    """
    Flag if form score drops significantly across the session.
    Uses a simple first-half vs second-half average comparison.
    """
    flags = []
    if len(rep_events) < 4:
        return flags

    scores = [r.get("form_score") for r in rep_events if r.get("form_score") is not None]
    if len(scores) < 4:
        return flags

    mid = len(scores) // 2
    first_half_avg = sum(scores[:mid]) / mid
    second_half_avg = sum(scores[mid:]) / (len(scores) - mid)
    drop = first_half_avg - second_half_avg

    if drop >= FORM_DECLINE_THRESHOLD:
        first_score = scores[0]
        last_score = scores[-1]
        flags.append({
            "severity": "warning",
            "category": "form_decline",
            "message": (
                f"📉 Form score dropped from {first_score:.0f}% (rep 1) "
                f"to {last_score:.0f}% (rep {len(scores)}) — "
                f"possible fatigue ({drop:.0f}% average decline mid-session)"
            ),
            "first_score": first_score,
            "last_score": last_score,
            "decline": round(drop, 1),
        })
    elif drop < -5:
        # Form actually improved
        flags.append({
            "severity": "success",
            "category": "form_improvement",
            "message": (
                f"✅ Form improved across the session — "
                f"average score rose {abs(drop):.0f}% in the second half"
            ),
            "improvement": round(abs(drop), 1),
        })

    return flags


def _detect_rom_anomalies(rep_events: List[Dict]) -> List[Dict]:
    """Flag individual reps whose ROM is notably above or below the session average."""
    flags = []
    roms = [r.get("rom") for r in rep_events if r.get("rom") is not None]
    if len(roms) < 3:
        return flags

    mean_rom = sum(roms) / len(roms)
    variance = sum((x - mean_rom) ** 2 for x in roms) / len(roms)
    std_rom = variance ** 0.5

    if std_rom < 1.0:
        # ROM is very consistent — that's a good thing
        flags.append({
            "severity": "success",
            "category": "consistent_rom",
            "message": (
                f"✅ ROM very consistent across all reps "
                f"(avg {mean_rom:.1f}°, std ±{std_rom:.1f}°)"
            ),
            "avg_rom": round(mean_rom, 1),
            "std_rom": round(std_rom, 1),
        })
        return flags

    for rep in rep_events:
        rom = rep.get("rom")
        if rom is None:
            continue
        z = (rom - mean_rom) / std_rom if std_rom > 0 else 0
        ex = rep.get("exercise", "?")
        rep_num = rep.get("rep_number", "?")
        if z < -ROM_ANOMALY_SIGMA:
            flags.append({
                "severity": "info",
                "category": "low_rom",
                "message": (
                    f"📐 {ex} rep {rep_num}: ROM {rom:.1f}° is below session avg "
                    f"({mean_rom:.1f}°) — patient may be guarding"
                ),
                "rep": rep_num,
                "rom": rom,
                "avg_rom": round(mean_rom, 1),
            })
        elif z > ROM_ANOMALY_SIGMA:
            flags.append({
                "severity": "info",
                "category": "high_rom",
                "message": (
                    f"📐 {ex} rep {rep_num}: ROM {rom:.1f}° is above session avg "
                    f"({mean_rom:.1f}°) — excellent range achieved"
                ),
                "rep": rep_num,
                "rom": rom,
                "avg_rom": round(mean_rom, 1),
            })

    return flags


def _detect_rest_periods(rep_events: List[Dict]) -> List[Dict]:
    """Summarise any rest periods (gaps > REST_PERIOD_SEC but < LONG_PAUSE_SEC)."""
    flags = []
    for i in range(1, len(rep_events)):
        gap = _gap_seconds(rep_events[i - 1], rep_events[i])
        if gap is not None and REST_PERIOD_SEC <= gap < LONG_PAUSE_SEC:
            prev_rep = rep_events[i - 1].get("rep_number", i)
            curr_rep = rep_events[i].get("rep_number", i + 1)
            ex = rep_events[i - 1].get("exercise", "?")
            flags.append({
                "severity": "info",
                "category": "rest_period",
                "message": (
                    f"⏸️ Rest period: {int(round(gap))}s between "
                    f"{ex} rep {prev_rep} and rep {curr_rep}"
                ),
                "gap_seconds": int(round(gap)),
            })
    return flags


def _detect_consistent_form(rep_events: List[Dict]) -> List[Dict]:
    """Flag positively when form scores are consistently high throughout."""
    flags = []
    scores = [r.get("form_score") for r in rep_events if r.get("form_score") is not None]
    if len(scores) < 3:
        return flags
    if min(scores) >= 80:
        avg = sum(scores) / len(scores)
        flags.append({
            "severity": "success",
            "category": "consistent_form",
            "message": (
                f"✅ Consistently strong form — all reps scored ≥80% "
                f"(session avg {avg:.0f}%)"
            ),
            "min_score": min(scores),
            "avg_score": round(avg, 1),
        })
    return flags


# =============================================================================
# SUMMARY TEXT
# =============================================================================

def _build_summary_text(metrics: Dict, flags: List[Dict]) -> str:
    """Build a human-readable bullet-point summary string."""
    lines = []

    dur = metrics.get("session_duration_seconds", 0)
    total = metrics.get("total_reps", 0)
    exercises = metrics.get("exercises_performed", [])
    avg_form = metrics.get("avg_form_score", 0)
    avg_rom = metrics.get("avg_rom", 0)
    rest_count = metrics.get("rest_period_count", 0)
    rpe = metrics.get("reps_per_exercise", {})

    lines.append(f"• Session duration: {_fmt_duration(dur)}")
    lines.append(f"• Total reps completed: {total}")

    ex_detail = ", ".join(f"{ex} ({rpe.get(ex, 0)} reps)" for ex in exercises)
    lines.append(f"• Exercises: {ex_detail}")
    lines.append(f"• Average form score: {avg_form:.0f}%")
    lines.append(f"• Average ROM: {avg_rom:.1f}°")

    if rest_count:
        total_rest = metrics.get("total_rest_seconds", 0)
        lines.append(
            f"• Rest periods: {rest_count} "
            f"(total {_fmt_duration(total_rest)} of rest)"
        )

    lines.append("")
    lines.append("Key observations:")
    if flags:
        for flag in flags:
            lines.append(f"  {flag['message']}")
    else:
        lines.append("  No significant observations — session within normal parameters.")

    return "\n".join(lines)


# =============================================================================
# HELPERS
# =============================================================================

def _parse_ts(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string to a datetime object."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def _gap_seconds(
    prev_event: Dict, curr_event: Dict
) -> Optional[float]:
    """Return the gap in seconds between two events, or None if unparseable."""
    prev_ts = _parse_ts(prev_event.get("timestamp"))
    curr_ts = _parse_ts(curr_event.get("timestamp"))
    if prev_ts is None or curr_ts is None:
        return None
    gap = (curr_ts - prev_ts).total_seconds()
    return gap if gap >= 0 else None


def _fmt_duration(seconds: float) -> str:
    """Format a number of seconds as 'm:ss' or 'Xs'."""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"
