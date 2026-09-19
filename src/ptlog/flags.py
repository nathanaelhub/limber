"""
Attention rules over per-session measures (FR-014, FR-015). Pure functions.

Each rule returns a Flag with the sessions and values that triggered it, None when the
rule was evaluated and did not fire, or NotEvaluated when there are not enough sessions.
Thresholds are the fixed defaults from the spec; only the practice-gap threshold is per
patient (FR-016).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence, Union

from .models import Flag, FlagResult, Goal, NotEvaluated, SessionMeasure

FORM_WINDOW = 4                 # sessions considered by the form rule
FORM_DROP_POINTS = 10           # latest at least this far below the best of the other three
ROM_WINDOW = 4                  # sessions considered by the ROM rules
ROM_REGRESSION_DEGREES = 10     # latest at least this far below the best of the previous three
ROM_PLATEAU_DEGREES = 3         # earliest-to-latest change smaller than this, while below goal
TARGET_REPS_SESSIONS = 3        # consecutive sessions below target
PARTIAL_WINDOW = 4              # sessions considered by the partial-rep rule
PARTIAL_SHARE_MIN = 25          # latest share at least this (percent)
PARTIAL_SHARE_RISE = 10         # and at least this many points above the previous three's mean


def _exercise(series: Sequence[SessionMeasure]) -> Optional[str]:
    return series[0].exercise_name if series else None


def _ids(ms: Sequence[SessionMeasure]) -> List[int]:
    return [m.session_id for m in ms]


def _g(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def form_declining(series: Sequence[SessionMeasure]):
    """Form declining: over the four most recent sessions of the exercise, each session's average
    form score is lower than the previous one, or the most recent is at least 10 points below the
    highest of the other three (FR-014)."""
    ex = _exercise(series)
    valid = [m for m in series if m.avg_form is not None]
    if len(valid) < FORM_WINDOW:
        return NotEvaluated("form_declining", ex, FORM_WINDOW, len(valid))
    w = valid[-FORM_WINDOW:]
    scores = [m.avg_form for m in w]
    each_lower = all(scores[i] < scores[i - 1] for i in range(1, len(scores)))
    drop = round(max(scores[:-1]) - scores[-1], 1)
    if each_lower or drop >= FORM_DROP_POINTS:
        pairs = ", ".join(f"{m.session_id}: {_g(m.avg_form)}" for m in w)
        return Flag("form_declining", ex, _ids(w), {"scores": scores, "drop_from_best": drop},
                    f"{ex}: form score fell across sessions {', '.join(map(str, _ids(w)))} ({pairs}); "
                    f"latest is {_g(drop)} points below the best of the other three.")
    return None


def rom_regression(series: Sequence[SessionMeasure]):
    """Range of motion regression: the most recent session's average range of motion is at least
    10 degrees below the highest of the previous three sessions (FR-014)."""
    ex = _exercise(series)
    valid = [m for m in series if m.avg_rom is not None]
    if len(valid) < ROM_WINDOW:
        return NotEvaluated("rom_regression", ex, ROM_WINDOW, len(valid))
    w = valid[-ROM_WINDOW:]
    best = max(w[:-1], key=lambda m: m.avg_rom)
    drop = round(best.avg_rom - w[-1].avg_rom, 1)
    if drop >= ROM_REGRESSION_DEGREES:
        return Flag("rom_regression", ex, _ids(w), {"latest": w[-1].avg_rom, "best_previous": best.avg_rom, "drop": drop},
                    f"{ex}: average ROM {_g(w[-1].avg_rom)}° in session {w[-1].session_id} is {_g(drop)}° below the best of "
                    f"the previous three ({_g(best.avg_rom)}° in session {best.session_id}).")
    return None


def rom_plateau(series: Sequence[SessionMeasure], goal: Optional[Goal]):
    """Range of motion plateau: a goal range of motion is set, the latest average range of motion
    is below it, and across the four most recent sessions the average range of motion changed by
    less than 3 degrees between the earliest and the latest of them (FR-014)."""
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
    if change < ROM_PLATEAU_DEGREES:
        roms = [m.avg_rom for m in w]
        return Flag("rom_plateau", ex, _ids(w), {"roms": roms, "change": change, "goal_rom": goal.target_rom},
                    f"{ex}: average ROM stayed within {_g(change)}° across sessions {', '.join(map(str, _ids(w)))} "
                    f"({', '.join(_g(r) for r in roms)}) while below the goal of {_g(goal.target_rom)}°.")
    return None


def target_reps_not_reached(series: Sequence[SessionMeasure]):
    """Target reps not reached: in each of the three most recent sessions, reps completed were below
    the target (FR-014)."""
    ex = _exercise(series)
    if len(series) < TARGET_REPS_SESSIONS:
        return NotEvaluated("target_reps_not_reached", ex, TARGET_REPS_SESSIONS, len(series))
    w = list(series)[-TARGET_REPS_SESSIONS:]
    if all(m.reps_completed < m.target_reps for m in w):
        reps = [m.reps_completed for m in w]
        targets = [m.target_reps for m in w]
        return Flag("target_reps_not_reached", ex, _ids(w), {"reps": reps, "targets": targets},
                    f"{ex}: fewer reps than the target of {'/'.join(map(str, sorted(set(targets))))} in the last three "
                    f"sessions {', '.join(map(str, _ids(w)))} ({', '.join(f'{r}/{t}' for r, t in zip(reps, targets))}).")
    return None


def rising_partial_reps(series: Sequence[SessionMeasure]):
    """Rising partial reps: the most recent session's partial-rep share is at least 25% and at least
    10 points above the average share of the previous three sessions (FR-014). A missing share counts as 0."""
    ex = _exercise(series)
    if len(series) < PARTIAL_WINDOW:
        return NotEvaluated("rising_partial_reps", ex, PARTIAL_WINDOW, len(series))
    w = list(series)[-PARTIAL_WINDOW:]
    shares = [m.partial_share if m.partial_share is not None else 0.0 for m in w]
    latest = shares[-1]
    prev_mean = round(sum(shares[:-1]) / (PARTIAL_WINDOW - 1), 1)
    if latest >= PARTIAL_SHARE_MIN and latest >= prev_mean + PARTIAL_SHARE_RISE:
        return Flag("rising_partial_reps", ex, _ids(w), {"latest": latest, "previous_mean": prev_mean},
                    f"{ex}: partial reps were {_g(latest)}% of attempts in session {w[-1].session_id}, up from an average "
                    f"of {_g(prev_mean)}% over sessions {', '.join(map(str, _ids(w[:-1])))}.")
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
                               f"{days} days between sessions on {a:%Y-%m-%d} and {b:%Y-%m-%d} (threshold {gap_days})."))
    if items:
        last, last_id = items[-1]
        days = (now - last).days
        if days > gap_days:
            result.append(Flag("practice_gap", None, [last_id] if last_id is not None else [], {"days": days, "threshold": gap_days},
                               f"{days} days since the last session on {last:%Y-%m-%d} (threshold {gap_days})."))
    return result


def evaluate(series_by_exercise: Dict[str, List[SessionMeasure]], goals: Dict[str, Goal],
             session_starts: Sequence[Union[str, tuple]], gap_days: int, now: datetime) -> FlagResult:
    """Run every rule per exercise, then the patient-level practice-gap rule."""
    result = FlagResult()

    def take(outcome):
        if isinstance(outcome, Flag):
            result.flags.append(outcome)
        elif isinstance(outcome, NotEvaluated):
            result.not_evaluated.append(outcome)
        return outcome

    for exercise, series in series_by_exercise.items():
        take(form_declining(series))
        regression = take(rom_regression(series))
        if not isinstance(regression, Flag):
            take(rom_plateau(series, goals.get(exercise)))
        take(target_reps_not_reached(series))
        take(rising_partial_reps(series))
        result.flags.extend(safety_stops(series))
    result.flags.extend(practice_gap(session_starts, gap_days, now))
    return result
