"""Review summary CSV (contracts/exports.md): one row per session per exercise, newest first.

The last column repeats the attention thresholds in use, so the file stays one table (feature 005)."""

from __future__ import annotations

import csv
import io

from ..models import ReviewSummary

HEADER = ["date", "session_id", "exercise", "reps_completed", "target_reps", "avg_form_score_0_100",
          "avg_rom_degrees", "avg_rep_duration_seconds", "tempo_consistency_seconds",
          "partial_rep_share_percent", "interrupted", "review_status", "next_step", "reviewed_at",
          "thresholds_in_use", "recorded"]


def _one(value) -> str:
    return "" if value is None else f"{value:.1f}"


def _two(value) -> str:
    if value is None:
        return ""
    text = f"{value:.2f}"
    return text[:-1] if text.endswith("0") else text


def thresholds_cell(effective) -> str:
    """`key=value` for every threshold, in registry order; non-default values name their origin."""
    from ..thresholds import THRESHOLDS, Thresholds
    effective = effective or Thresholds.defaults()
    return "; ".join(
        f"{key}={effective.value(key)}" + ("" if effective.origin(key) == "default" else f" ({effective.origin(key)})")
        for key in THRESHOLDS)


def to_review_csv(summary: ReviewSummary) -> str:
    in_use = thresholds_cell(summary.thresholds)
    by_exercise = {name: thresholds_cell(t) for name, t in (summary.exercise_thresholds or {}).items()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    for entry in summary.sessions:
        s, review = entry["session"], entry["review"]
        for name, m in entry["measures"].items():
            w.writerow([
                s.start_time[:10], s.id, name, m.reps_completed, m.target_reps, _one(m.avg_form), _one(m.avg_rom),
                _two(m.avg_duration), _two(m.tempo_sd), _one(m.partial_share),
                "true" if m.interrupted else "false",
                "reviewed" if review else "pending",
                review.next_step if review else "",
                review.reviewed_at if review else "",
                by_exercise.get(name, in_use),
                m.origin,
            ])
    return buf.getvalue()


QUESTIONNAIRE_HEADER = ["date", "instrument", "version", "total", "unit", "missing", "subscales", "direction"]


def to_questionnaire_csv(summary: ReviewSummary) -> str:
    """One row per completed questionnaire (feature 013 FR-012).

    A separate file from the per-session review CSV, because a questionnaire is not a session and
    forcing both into one table would leave most of every row empty."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(QUESTIONNAIRE_HEADER)
    for q in summary.questionnaires:
        names = q.get("subscale_names") or {}
        scores = q.get("subscales") or {}
        cells = "; ".join(f"{names.get(key, key)}={'' if value is None else value}".lower()
                          for key, value in scores.items())
        w.writerow([q["recorded_at"][:10], q.get("name") or q["instrument"], q.get("version"), q.get("total"),
                    q.get("unit", ""), q.get("missing", 0), cells, q.get("direction", "")])
    return buf.getvalue()
