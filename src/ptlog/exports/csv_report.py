"""CSV report export (contracts/exports.md §3), the layout SessionTracker._save_csv produced."""

from __future__ import annotations

import csv
import io
from typing import Optional

from ..models import Patient, Session
from ..views import legacy_flags, set_summary
from ._common import parse_ts, session_end_time


def to_csv_report(session: Session, patient: Optional[Patient] = None) -> str:
    start = parse_ts(session.start_time)
    end = parse_ts(session_end_time(session))
    # The legacy tracker kept HH:MM:SS strings, so the duration ignored sub-second parts.
    duration_min = (end.replace(microsecond=0) - start.replace(microsecond=0)).seconds / 60
    stats = [(es, set_summary(es)) for es in session.sets]
    overall = sum(st["avg_form_score"] for _, st in stats) / len(stats) if stats else 0.0

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["PT Session Report"])
    w.writerow(["Session ID", f"{session.patient_id}_{start:%Y%m%d_%H%M%S}"])
    w.writerow(["Patient ID", session.patient_id])
    w.writerow(["Date", start.strftime("%Y-%m-%d")])
    w.writerow(["Duration (min)", f"{duration_min:.1f}"])
    w.writerow(["Overall Form Score", f"{overall:.1f}%"])
    w.writerow([])
    w.writerow(["Exercise", "Reps", "Target", "Form Score", "ROM Min", "ROM Max", "ROM Range", "Avg Rep Time"])
    for es, st in stats:
        w.writerow([es.exercise_name, st["reps"], st["target_reps"], f"{st['avg_form_score']:.1f}%",
                    f"{st['min_angle']:.1f}°", f"{st['max_angle']:.1f}°", f"{st['rom_range']:.1f}°",
                    f"{st['avg_duration']:.2f}s"])
    w.writerow([])
    flags = legacy_flags(session)
    if flags:
        w.writerow(["Flags for Review"])
        for flag in flags:
            w.writerow([flag])
        w.writerow([])
    notes = patient.notes if patient is not None else None
    if notes:
        w.writerow(["Therapist Notes"])
        w.writerow([notes])
    return buf.getvalue()
