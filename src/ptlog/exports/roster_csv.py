"""Roster CSV export (contracts/exports.md): one row per active patient in attention order."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..models import RosterRow

HEADER = ["patient_id", "label", "program", "program_status", "days_since_last_session", "sessions_last_7_days",
          "sessions_last_30_days", "adherence_percent", "pending_reviews", "open_flags", "practice_gap", "last_next_step"]


def to_roster_csv(rows: List[RosterRow], generated_at: datetime) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    for r in rows:
        w.writerow([
            r.patient_id, r.label or "", r.program_name, r.program_status,
            "" if r.days_since_last is None else r.days_since_last, r.sessions_7d, r.sessions_30d,
            "" if r.adherence_pct is None else r.adherence_pct, r.pending_reviews, r.open_flags,
            "true" if r.practice_gap else "false", r.last_next_step or "",
        ])
    return buf.getvalue()


def write_roster_export(store, out_dir: Optional[Path] = None, now: Optional[datetime] = None) -> Path:
    """Write roster_<time>.csv for every active patient (the filter state never applies)."""
    from ..tracker import roster
    from . import default_export_dir
    now = now or datetime.now()
    out = Path(out_dir) if out_dir else default_export_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"roster_{now:%Y%m%d_%H%M%S}.csv"
    path.write_bytes(to_roster_csv(roster(store, now=now), now).encode("utf-8"))
    return path
