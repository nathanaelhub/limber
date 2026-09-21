"""
Attention rules over per-session measures (FR-014, FR-015). Pure functions.

Each rule returns a Flag with the sessions and values that triggered it, None when the
rule was evaluated and did not fire, or NotEvaluated when there are not enough sessions.
Threshold values come from a `Thresholds` set resolved per patient (feature 005); every rule
defaults to the built-in values, and each raised flag states the threshold that applied. The
number of sessions a rule looks at is part of the rule and is fixed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence, Union

from .models import Flag, FlagResult, Goal, NotEvaluated, SessionMeasure
from .thresholds import THRESHOLDS, Thresholds

FORM_WINDOW = 4                 # sessions considered by the form rule
ROM_WINDOW = 4                  # sessions considered by the ROM rules
PARTIAL_WINDOW = 4              # sessions considered by the partial-rep rule
DEFAULTS = Thresholds.defaults()


def _stated(key: str, value: int) -> str:
    return f"threshold {value} {THRESHOLDS[key].unit}"


def _exercise(series: Sequence[SessionMeasure]) -> Optional[str]:
    return series[0].exercise_name if series else None


def _ids(ms: Sequence[SessionMeasure]) -> List[int]:
    return [m.session_id for m in ms]


def _g(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def form_declining(series: Sequence[SessionMeasure], thresholds: Thresholds = DEFAULTS):
    """Form declining: over the four most recent sessions of the exercise, each session's average
    form score is lower than the previous one, or the most recent is at least `form_drop` points
    (default 10) below the highest of the other three (FR-014)."""
    ex = _exercise(series)
    valid = [m for m in series if m.avg_form is not None]
    if len(valid) < FORM_WINDOW:
        return NotEvaluated("form_declining", ex, FORM_WINDOW, len(valid))
    w = valid[-FORM_WINDOW:]
    scores = [m.avg_form for m in w]
    each_lower = all(scores[i] < scores[i - 1] for i in range(1, len(scores)))
    drop = round(max(scores[:-1]) - scores[-1], 1)
    limit = thresholds.form_drop
    if each_lower or drop >= limit:
        pairs = ", ".join(f"{m.session_id}: {_g(m.avg_form)}" for m in w)
        return Flag("form_declining", ex, _ids(w), {"scores": scores, "drop_from_best": drop, "threshold": limit},
                    f"{ex}: form score fell across sessions {', '.join(map(str, _ids(w)))} ({pairs}); "
                    f"latest is {_g(drop)} points below the best of the other three ({_stated('form_drop', limit)}).")
    return None


def rom_regression(series: Sequence[SessionMeasure], thresholds: Thresholds = DEFAULTS):
    """Range of motion regression: the most recent session's average range of motion is at least
    `rom_regression` degrees (default 10) below the highest of the previous three sessions (FR-014)."""
    ex = _exercise(series)
    valid = [m for m in series if m.avg_rom is not None]
    if len(valid) < ROM_WINDOW:
        return NotEvaluated("rom_regression", ex, ROM_WINDOW, len(valid))
    w = valid[-ROM_WINDOW:]
    best = max(w[:-1], key=lambda m: m.avg_rom)
    drop = round(best.avg_rom - w[-1].avg_rom, 1)
    limit = thresholds.rom_regression
    if drop >= limit:
        return Flag("rom_regression", ex, _ids(w),
                    {"latest": w[-1].avg_rom, "best_previous": best.avg_rom, "drop": drop, "threshold": limit},
                    f"{ex}: average ROM {_g(w[-1].avg_rom)}° in session {w[-1].session_id} is {_g(drop)}° below the best of "
                    f"the previous three ({_g(best.avg_rom)}° in session {best.session_id}; {_stated('rom_regression', limit)}).")
    return None


def rom_plateau(series: Sequence[SessionMeasure], goal: Optional[Goal], thresholds: Thresholds = DEFAULTS):
    """Range of motion plateau: a goal range of motion is set, the latest average range of motion
    is below it, and across the four most recent sessions the average range of motion changed by
    less than `rom_plateau` degrees (default 3) between the earliest and the latest of them (FR-014)."""
    ex = _exercise(series)
    if goal is None or not goal.target_rom:
        return None
    valid = [m for m in series if m.avg_rom is not None]
    if len(valid) < ROM_WINDOW:
        return NotEvaluated("rom_plateau", ex, ROM_WINDOW, len(valid))
    w = valid[-ROM_WINDOW:]
    latest = w[-1].avg_rom
    if latest >= goal.target_rom:
        return None
    change = round(abs(latest - w[0].avg_rom), 1)
    limit = thresholds.rom_plateau
    if change < limit:
        roms = [m.avg_rom for m in w]
        return Flag("rom_plateau", ex, _ids(w),
                    {"roms": roms, "change": change, "goal_rom": goal.target_rom, "threshold": limit},
                    f"{ex}: average ROM stayed within {_g(change)}° across sessions {', '.join(map(str, _ids(w)))} "
                    f"({', '.join(_g(r) for r in roms)}) while below the goal of {_g(goal.target_rom)}° ({_stated('rom_plateau', limit)}).")
    return None


def target_reps_not_reached(series: Sequence[SessionMeasure], thresholds: Thresholds = DEFAULTS):
    """Target reps not reached: in each of the `target_reps_sessions` (default three) most recent
    sessions, reps completed were below the target (FR-014)."""
    ex = _exercise(series)
    count = thresholds.target_reps_sessions
    if len(series) < count:
        return NotEvaluated("target_reps_not_reached", ex, count, len(series))
    w = list(series)[-count:]
    if all(m.reps_completed < m.target_reps for m in w):
        reps = [m.reps_completed for m in w]
        targets = [m.target_reps for m in w]
        return Flag("target_reps_not_reached", ex, _ids(w), {"reps": reps, "targets": targets, "threshold": count},
                    f"{ex}: fewer reps than the target of {'/'.join(map(str, sorted(set(targets))))} in the last {count} "
                    f"sessions {', '.join(map(str, _ids(w)))} ({', '.join(f'{r}/{t}' for r, t in zip(reps, targets))}; "
                    f"{_stated('target_reps_sessions', count)}).")
    return None


def rising_partial_reps(series: Sequence[SessionMeasure], thresholds: Thresholds = DEFAULTS):
    """Rising partial reps: the most recent session's partial-rep share is at least `partial_share` percent (default 25)
    and at least `partial_rise` points (default 10) above the average share of the previous three sessions (FR-014). A missing share counts as 0."""
    ex = _exercise(series)
    if len(series) < PARTIAL_WINDOW:
        return NotEvaluated("rising_partial_reps", ex, PARTIAL_WINDOW, len(series))
    w = list(series)[-PARTIAL_WINDOW:]
    shares = [m.partial_share if m.partial_share is not None else 0.0 for m in w]
    latest = shares[-1]
    prev_mean = round(sum(shares[:-1]) / (PARTIAL_WINDOW - 1), 1)
    share, rise = thresholds.partial_share, thresholds.partial_rise
    if latest >= share and latest >= prev_mean + rise:
        return Flag("rising_partial_reps", ex, _ids(w),
                    {"latest": latest, "previous_mean": prev_mean,
                     "threshold": {"partial_share": share, "partial_rise": rise}},
                    f"{ex}: partial reps were {_g(latest)}% of attempts in session {w[-1].session_id}, up from an average "
                    f"of {_g(prev_mean)}% over sessions {', '.join(map(str, _ids(w[:-1])))} "
                    f"({_stated('partial_share', share)}, rise {rise} {THRESHOLDS['partial_rise'].unit}).")
    return None


def safety_stops(series: Sequence[SessionMeasure]) -> List[Flag]:
    """Safety stop: any form event with severity "stop" in any session in the period (FR-014)."""
    result: List[Flag] = []
    for m in series:
        for ts, message in m.safety_stops:
            result.append(Flag("safety_stop", m.exercise_name, [m.session_id], {"timestamp": ts, "message": message},
                               f"{m.exercise_name}: safety stop in session {m.session_id} at {ts[11:19]}: {message}"))
    return result


def practice_gap(session_starts: Sequence[Union[str, tuple]], gap_days: int, now: datetime) -> List[Flag]:
    """Practice gap: more days than the patient's gap threshold between consecutive sessions in the
    period, or between the most recent session and today (FR-014)."""
    items = []
    for item in session_starts:
        sid, start = (item if isinstance(item, tuple) else (None, item))
        items.append((datetime.fromisoformat(start), sid))
    items.sort(key=lambda x: x[0])
    result: List[Flag] = []
    for (a, ida), (b, idb) in zip(items, items[1:]):
        days = (b - a).days
        if days > gap_days:
            ids = [i for i in (ida, idb) if i is not None]
            result.append(Flag("practice_gap", None, ids, {"days": days, "threshold": gap_days},
                               f"{days} days between sessions on {a:%Y-%m-%d} and {b:%Y-%m-%d} (threshold {gap_days} days)."))
    if items:
        last, last_id = items[-1]
        days = (now - last).days
        if days > gap_days:
            result.append(Flag("practice_gap", None, [last_id] if last_id is not None else [], {"days": days, "threshold": gap_days},
                               f"{days} days since the last session on {last:%Y-%m-%d} (threshold {gap_days} days)."))
    return result


def evaluate(series_by_exercise: Dict[str, List[SessionMeasure]], goals: Dict[str, Goal],
             session_starts: Sequence[Union[str, tuple]], thresholds: Union[Thresholds, int],
             now: datetime) -> FlagResult:
    """Run every rule per exercise, then the patient-level practice-gap rule.

    `thresholds` is the patient's effective set; a bare int is accepted as the practice-gap
    value with built-in defaults for the rest (the pre-feature-005 call shape)."""
    if not isinstance(thresholds, Thresholds):
        from .thresholds import resolve
        thresholds = resolve({"practice_gap": int(thresholds)})
    t = thresholds
    result = FlagResult()

    def take(outcome):
        if isinstance(outcome, Flag):
            result.flags.append(outcome)
        elif isinstance(outcome, NotEvaluated):
            result.not_evaluated.append(outcome)
        return outcome

    for exercise, series in series_by_exercise.items():
        take(form_declining(series, t))
        regression = take(rom_regression(series, t))
        if not isinstance(regression, Flag):
            take(rom_plateau(series, goals.get(exercise), t))
        take(target_reps_not_reached(series, t))
        take(rising_partial_reps(series, t))
        result.flags.extend(safety_stops(series))
    result.flags.extend(practice_gap(session_starts, t.practice_gap, now))
    return result
