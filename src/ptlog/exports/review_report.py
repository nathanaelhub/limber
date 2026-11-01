"""Review summary text report (contracts/exports.md). Pure function of a ReviewSummary."""

from __future__ import annotations

from datetime import datetime
from typing import List

from ..models import PERIODS, ReviewSummary
from ..views import MEASURE_ORDER, MEASURE_SHORT, fmt_change, fmt_measure

_ROW = "  {date:<11} {sid:<8} {reps:<12} {form:<17} {rom:<14} {dur:<12} {sd:<13} {partial:<12} {status}"
_HEADER = _ROW.format(date="date", sid="session", reps="reps/target", form="avg form (0-100)", rom="avg ROM (deg)",
                      dur="avg rep (s)", sd="tempo sd (s)", partial="partial (%)", status="status")


def _plain(name, value):
    """Numbers without unit suffixes for the table columns (units live in the header)."""
    if value is None:
        return "n/a"
    if name in ("avg_duration", "tempo_sd"):
        return f"{value:.2f}"
    return f"{value:.1f}"


def _period_line(summary: ReviewSummary) -> str:
    days = PERIODS.get(summary.period)
    if days is None:
        return "Period: all time"
    start = datetime.fromisoformat(summary.period_start)
    end = datetime.fromisoformat(summary.generated_at)
    return f"Period: last {days} days ({start:%Y-%m-%d} to {end:%Y-%m-%d})"


def _measures_phrase(measures) -> str:
    return ", ".join(f"{name} {m.reps_completed}/{m.target_reps}" for name, m in measures.items())


_ORIGIN_TEXT = {"patient": "patient override", "installation": "installation value"}


def _exercise_lines(by_exercise) -> List[str]:
    from ..thresholds import THRESHOLDS
    return [f"{name}: {THRESHOLDS[key].name} {t.value(key)} {THRESHOLDS[key].unit} (exercise override)"
            for name, t in sorted((by_exercise or {}).items())
            for key in THRESHOLDS if t.origin(key) == "exercise"]


def _threshold_lines(effective, by_exercise=None) -> List[str]:
    """Every threshold with its unit; values that are not the built-in default say where they come
    from; then one line per exercise-specific value."""
    from ..thresholds import THRESHOLDS, Thresholds
    effective = effective or Thresholds.defaults()
    exercise_lines = _exercise_lines(by_exercise)
    if not effective.overridden():
        if exercise_lines:
            return ["Built-in defaults were used for every threshold, except:"] + exercise_lines
        return ["Built-in defaults were used for every threshold."]
    lines = []
    for key, d in THRESHOLDS.items():
        line = f"{d.name}: {effective.value(key)} {d.unit}"
        if effective.origin(key) != "default":
            line += f" ({_ORIGIN_TEXT[effective.origin(key)]}; built-in default {d.default})"
        lines.append(line)
    return lines + exercise_lines


def _trend_block(lines: List[str], name: str, t, goal, label: str) -> None:
    lines.append(f"{name} — {len(t.points)} {label}")
    lines.append(_HEADER)
    for m in t.points:
        lines.append(_ROW.format(
            date=m.start_time[:10], sid=m.session_id, reps=f"{m.reps_completed}/{m.target_reps}",
            form=_plain("avg_form", m.avg_form), rom=_plain("avg_rom", m.avg_rom),
            dur=_plain("avg_duration", m.avg_duration), sd=_plain("tempo_sd", m.tempo_sd),
            partial=_plain("partial_share", m.partial_share),
            status=m.status + (" (interrupted)" if m.interrupted and m.status != "interrupted" else "")))
    if t.enough_for_trend:
        changes = ", ".join(f"{MEASURE_SHORT[n]} {fmt_change(n, t.summary[n]['change'])}" for n in MEASURE_ORDER if n in t.summary)
        lines.append(f"  change first→latest: {changes}")
    else:
        lines.append("  a trend needs at least two sessions")
    if goal:
        parts = []
        if goal.target_rom:
            latest = next((p.avg_rom for p in reversed(t.points) if p.avg_rom is not None), None)
            latest_txt = f"latest {latest:.1f}°, {t.rom_progress_pct}% of goal" if latest is not None else "no ROM recorded yet"
            parts.append(f"ROM {goal.target_rom:g}° ({latest_txt})")
        if goal.target_reps:
            parts.append(f"reps {goal.target_reps}")
        lines.append("  goal: " + ", ".join(parts))


def to_review_report(summary: ReviewSummary) -> str:
    gen = datetime.fromisoformat(summary.generated_at)
    lines: List[str] = ["PT REVIEW SUMMARY", f"Patient: {summary.patient_id}", _period_line(summary),
                        f"Generated: {gen:%Y-%m-%d %H:%M}", "", "TRENDS"]

    if not summary.trends:
        lines.append("No sessions in this period.")
    for name, whole in summary.trends.items():
        parts = list((getattr(whole, "by_origin", {}) or {}).values())
        mixed = len(parts) > 1
        if mixed:
            lines.append(f"{name}: home and clinic sessions are listed apart; their numbers are not compared.")
        for t in (parts if mixed else [whole]):
            label = f"{t.origin} sessions" if mixed else "sessions"
            _trend_block(lines, name, t, whole.goal, label)

    lines += ["", "FLAGS"]
    if not summary.flags.flags:
        lines.append("No flags in this period.")
    for f in summary.flags.flags:
        lines.append(f"- [{f.rule}] {f.message}")
    if summary.flags.not_evaluated:
        lines.append("Not evaluated yet: " + "; ".join(
            f"{n.rule}{' for ' + n.exercise if n.exercise else ''} (needs {n.needed} sessions, has {n.have})"
            for n in summary.flags.not_evaluated))

    lines += ["", "THRESHOLDS IN USE"] + _threshold_lines(summary.thresholds, summary.exercise_thresholds)

    lines += ["", "GOALS"]
    if not summary.goals:
        lines.append("No goals set.")
    for g in summary.goals:
        goal = g["goal"]
        parts = []
        if goal.target_rom:
            latest = f"latest {g['latest_rom']:.1f}° ({g['progress_pct']}%)" if g["latest_rom"] is not None else "no ROM recorded yet"
            parts.append(f"ROM {goal.target_rom:g}° — {latest}")
        if goal.target_reps:
            latest = f"latest {g['latest_reps']}/{g['latest_target']}" if g["latest_reps"] is not None else "no reps recorded yet"
            parts.append(f"reps {goal.target_reps} — {latest}")
        lines.append(f"{goal.exercise_name}: " + "; ".join(parts))

    if summary.questionnaires:
        lines += ["", "QUESTIONNAIRES"]
        for q in summary.questionnaires:
            names, scores = q.get("subscale_names") or {}, q.get("subscales") or {}
            parts = [f"{names.get(k, k)} {'—' if v is None else v}" for k, v in scores.items()]
            missing = f", {q['missing']} question(s) not answered" if q.get("missing") else ""
            lines.append(f"- {q['recorded_at'][:10]} {q.get('name') or q['instrument']}: "
                         f"{q.get('total')} {q.get('unit', '')}"
                         + (f" ({'; '.join(parts)})" if parts else "") + missing)
        latest = summary.questionnaires[0]
        direction = "a higher score is better" if latest.get("direction") == "higher_is_better" else "a higher score is worse"
        lines.append(f"{latest.get('name')}: {latest.get('meaning', '')} Score in {latest.get('unit', '')}; {direction}.")
        if latest.get("notice"):
            lines.append(f"Note on this questionnaire: {latest['notice']}")
        lines.append(f"Answers given on {latest['recorded_at'][:10]}:")
        for item in (latest.get("snapshot") or {}).get("items", []):
            answer = item.get("answer") or "(not answered)"
            reversed_note = " [reversed]" if item.get("reversed") else ""
            lines.append(f"  - {item['text']}: {answer}{reversed_note}")

    lines += ["", "SESSIONS"]
    if not summary.sessions:
        lines.append("No sessions in this period.")
    for entry in summary.sessions:
        s, review = entry["session"], entry["review"]
        head = f"- {s.start_time[:10]} session {s.id} | {_measures_phrase(entry['measures']) or 'no exercise recorded'}"
        if s.status == "interrupted":
            head += " | interrupted"
        if review is None:
            lines.append(head + " | pending review")
        else:
            reviewed = datetime.fromisoformat(review.reviewed_at)
            lines.append(f"{head} | reviewed {reviewed:%Y-%m-%d %H:%M} | next step: {review.next_step} | notes: {review.notes or ''}")
    return "\n".join(lines) + "\n"
