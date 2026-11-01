"""Helpers shared by the export adapters (ordering, timestamps, set lookup)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Tuple

from ..models import Session
from ..store import SessionStore, _ts_key

# Rank of rows sharing a timestamp and frame, mirroring the legacy loop order.
RANK = {"sample": 0, "rep": 1, "partial_rep": 2, "form": 3, "switch": 4, "reset": 5}


def parse_ts(iso: Optional[str]) -> datetime:
    return datetime.fromisoformat(iso) if iso else datetime.min


def sort_key(timestamp: str, frame_num: int, kind: str) -> Tuple[Any, int, int]:
    return (_ts_key(timestamp), frame_num, RANK.get(kind, 8))


def set_open_at(session: Session, timestamp: str, closing: Optional[str] = None):
    return SessionStore._set_open_at(session, timestamp, closing)


def session_end_time(session: Session) -> str:
    """The end time to print: stored end_time, else the last event, else the start."""
    if session.end_time:
        return session.end_time
    latest = session.start_time
    for es in session.sets:
        for coll in (es.reps, es.partial_reps, es.form_events, es.samples):
            for x in coll:
                if _ts_key(x.timestamp) > _ts_key(latest):
                    latest = x.timestamp
    for c in session.control_events:
        if _ts_key(c.timestamp) > _ts_key(latest):
            latest = c.timestamp
    return latest


def summary_numbers(session: Session) -> Tuple[int, float, float]:
    """(total_reps, avg_form_score, avg_rom) with the legacy 0.0 defaults for missing averages."""
    return (int(session.total_reps or 0),
            round(float(session.avg_form_score if session.avg_form_score is not None else 0.0), 1),
            round(float(session.avg_rom if session.avg_rom is not None else 0.0), 1))


def merged_events(session: Session) -> List[Tuple[str, str, int, Any, Any]]:
    """Every event as (kind, timestamp, frame_num, set, obj), sorted like the legacy loops wrote them."""
    rows = []
    for es in session.sets:
        rows += [("rep", r.timestamp, r.frame_num, es, r) for r in es.reps]
        rows += [("partial_rep", p.timestamp, p.frame_num, es, p) for p in es.partial_reps]
        rows += [("form", f.timestamp, f.frame_num, es, f) for f in es.form_events]
    for c in session.control_events:
        es = set_open_at(session, c.timestamp, c.from_exercise if c.kind == "switch" else None)
        rows.append((c.kind, c.timestamp, c.frame_num, es, c))
    rows.sort(key=lambda r: sort_key(r[1], r[2], r[0]))
    return rows
