"""
Per-session, per-exercise measures derived from the canonical record (FR-001, FR-002).

Pure functions over loaded Session objects; nothing is stored (research D1). Values that
need at least one counted rep are None ("not available") when there are none.
"""

from __future__ import annotations

import statistics
from typing import Dict, List

from .origin import capture_origin
from .models import ExerciseSet, Session, SessionMeasure


def measures_for_session(session: Session) -> Dict[str, SessionMeasure]:
    """Measures keyed by exercise name, combining every set of that exercise in the session."""
    grouped: Dict[str, List[ExerciseSet]] = {}
    for es in session.sets:
        grouped.setdefault(es.exercise_name, []).append(es)

    result: Dict[str, SessionMeasure] = {}
    for name, sets in grouped.items():
        reps = [r for es in sets for r in es.reps if not r.out_of_range]
        partials = sum(len(es.partial_reps) for es in sets)
        stops = [(f.timestamp, f.message) for es in sets for f in es.form_events if f.severity == "stop"]
        n = len(reps)
        attempts = n + partials
        durations = [r.duration_seconds for r in reps]
        result[name] = SessionMeasure(
            session_id=session.id,
            patient_id=session.patient_id,
            start_time=session.start_time,
            status=session.status,
            interrupted=session.status == "interrupted",
            exercise_name=name,
            reps_completed=n,
            target_reps=int(sets[-1].target_reps),
            avg_rom=round(sum(r.rom for r in reps) / n, 1) if n else None,
            avg_form=round(sum(r.form_score for r in reps) / n, 1) if n else None,
            avg_duration=round(sum(durations) / n, 2) if n else None,
            tempo_sd=round(statistics.pstdev(durations), 2) if n else None,
            partial_count=partials,
            partial_share=round(partials / attempts * 100, 1) if attempts else None,
            safety_stops=stops,
            origin=capture_origin(session),
        )
    return result


def measure_series(sessions: List[Session], exercise: str) -> List[SessionMeasure]:
    """Measures for one exercise across sessions, oldest first, skipping sessions without it."""
    ordered = sorted(sessions, key=lambda s: (s.start_time, s.id))
    series: List[SessionMeasure] = []
    for session in ordered:
        m = measures_for_session(session).get(exercise)
        if m is not None:
            series.append(m)
    return series
