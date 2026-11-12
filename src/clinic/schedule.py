"""The Schedule page's rules (feature 019 slice 4, T021), moved from the Streamlit page: every visit on the
therapist's caseload in clinic time, reschedule requests first, then upcoming, then past and cancelled."""

from __future__ import annotations

from typing import Dict, List

from src.portal import plans as ptplans
from src.ptlog.store import SessionStore


def visits(store: SessionStore) -> Dict[str, List[dict]]:
    """{"requests", "upcoming", "rest"}; each visit carries its patient and plan title. Upcoming are soonest first;
    past and cancelled are newest first."""
    rows: List[dict] = []
    for p in store.list_patients():
        if p.is_builtin:
            continue
        titles = {pl.id: pl.title for pl in store.plans(p.id)}
        rows += [ptplans.appointment_json(store, a) | {"patient_id": a.patient_id, "plan": titles.get(a.plan_id, "")}
                 for a in store.appointments(p.id)]
    rows.sort(key=lambda v: v["starts_local"])
    return {"requests": [v for v in rows if v["reschedule_requested"] and v["state"] == "upcoming"],
            "upcoming": [v for v in rows if v["state"] == "upcoming"],
            "rest": [v for v in reversed(rows) if v["state"] != "upcoming"]}
