"""
Capture origin (feature 007, FR-020): where a session was recorded.

`home` sessions come from the patient portal, where the patient's browser finds the body points
with a different pose model than the clinic's. The two models agree on rep counts and form scores
but not on range of motion (specs/007-online-patient-view/research.md, D2), so numbers are never
compared across origins. Derived from the session, never stored.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from .models import Session

CLINIC = "clinic"
HOME = "home"
DIARY = "self-reported"          # the patient logged it without the camera (feature 012)
ORIGINS = (CLINIC, HOME, DIARY)
MEASURED_ORIGINS = (CLINIC, HOME)   # only these carry angles, so only these are ever compared


def capture_origin(session: Session) -> str:
    if session.source == "diary":
        return DIARY
    extras = session.source_extras or {}
    return HOME if extras.get("origin") == "portal" else CLINIC


def split_by_origin(sessions: Iterable[Session]) -> Dict[str, List[Session]]:
    """Sessions grouped by origin, clinic first; origins without sessions are left out."""
    grouped: Dict[str, List[Session]] = {}
    for s in sessions:
        grouped.setdefault(capture_origin(s), []).append(s)
    return {o: grouped[o] for o in ORIGINS if o in grouped}
