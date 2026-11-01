"""
Export adapters: pure functions from a loaded Session to a legacy file format, plus
write_export(), which names the files with the pseudonymous ID and start time only and
records them so a patient deletion can remove them (FR-017, FR-023).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..store import REPO_ROOT, SessionStore
from .csv_report import to_csv_report
from .observation_json import to_observation_dict, to_observation_json
from .pta_log import to_pta_log_text
from .review_csv import to_review_csv
from .review_report import to_review_report
from .text_log import to_text_log

# format name -> (file extension, renderer(store, session) -> str | list[str])
FORMATS: Dict[str, tuple] = {
    "pta_log": ("txt", lambda store, s: to_pta_log_text(s, ordinal=store.session_ordinal(s.id))),
    "observation_json": ("json", lambda store, s: to_observation_json(s)),
    "csv_report": ("csv", lambda store, s: to_csv_report(s, store.get_patient(s.patient_id))),
    "text_log": ("log", lambda store, s: to_text_log(s)),
}


def default_export_dir() -> Path:
    return REPO_ROOT / "exports"


def write_export(store: SessionStore, session_id: int, fmt: str, out_dir: Optional[Path] = None) -> List[Path]:
    """Write one export (several files for text_log) and record each path. Returns the paths."""
    if fmt not in FORMATS:
        raise ValueError(f"Unknown export format '{fmt}'; choose from {', '.join(FORMATS)}")
    session = store.load_session(session_id)
    ext, render = FORMATS[fmt]
    out = Path(out_dir) if out_dir else default_export_dir()
    out.mkdir(parents=True, exist_ok=True)
    base = f"{session.patient_id}_{datetime.fromisoformat(session.start_time):%Y%m%d_%H%M%S}"
    content = render(store, session)
    parts = content if isinstance(content, list) else [content]
    paths: List[Path] = []
    for i, text in enumerate(parts, 1):
        name = f"{base}_{i:02d}.{ext}" if fmt == "text_log" else f"{base}.{ext}"
        path = out / name
        path.write_bytes(text.encode("utf-8"))
        store.record_export(session_id, fmt, path)
        paths.append(path)
    return paths


# review summary exports (feature 002): format name -> (extension, renderer(summary) -> str)
REVIEW_FORMATS: Dict[str, tuple] = {
    "review_report": ("txt", to_review_report),
    "review_csv": ("csv", to_review_csv),
}


def write_review_export(store: SessionStore, patient_id: str, period: str, fmt: str,
                        out_dir: Optional[Path] = None, now: Optional[datetime] = None) -> Path:
    """Write a review summary export named by pseudonymous ID, period, and time; record it (FR-022)."""
    from ..review import review_summary
    if fmt not in REVIEW_FORMATS:
        raise ValueError(f"Unknown review export format '{fmt}'; choose from {', '.join(REVIEW_FORMATS)}")
    now = now or datetime.now()
    summary = review_summary(store, patient_id, period, now=now)
    ext, render = REVIEW_FORMATS[fmt]
    out = Path(out_dir) if out_dir else default_export_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{patient_id}_review_{period}_{now:%Y%m%d_%H%M%S}.{ext}"
    path.write_bytes(render(summary).encode("utf-8"))
    store.record_review_export(patient_id, fmt, period, path)
    return path


from .roster_csv import to_roster_csv, write_roster_export  # noqa: E402  (after default_export_dir exists)

__all__ = ["FORMATS", "REVIEW_FORMATS", "write_export", "write_review_export", "default_export_dir",
           "to_roster_csv", "write_roster_export",
           "to_pta_log_text", "to_observation_dict", "to_observation_json", "to_csv_report", "to_text_log",
           "to_review_report", "to_review_csv"]
