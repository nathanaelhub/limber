"""The clinic Tracker page's rules (feature 019 slice 5c, T027): the caseload at a glance, the work queue, adherence,
discharged patients, the roster export, and the installation's attention thresholds. Moved from the Streamlit page
and tested without a server.

New here: each work-queue item links to where it is dealt with, and changing the installation thresholds (which
apply to every caseload) needs an admin. Any therapist can read them.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import quote

from src.ptlog import thresholds as ptthresholds

SECTIONS = (("roster", "Roster"), ("queue", "Work queue"), ("adherence", "Adherence"), ("discharged", "Discharged"),
            ("export", "Export"), ("settings", "Settings"))
SECTION_KEYS = {k for k, _ in SECTIONS}
SORTS = (("attention", "Needs attention first"), ("id", "Patient code"))
WARN_KINDS = ("attention_flag", "practice_gap")


def target_href(target: str) -> Optional[str]:
    """Where a queue item is dealt with. Tokens come from src/ptlog/tracker.py: session:N, flags:P, uploads:P,
    questionnaires:P, inbox:P, adherence:P."""
    kind, _, value = target.partition(":")
    if not value:
        return None
    v = quote(value, safe="")
    return {"session": f"/therapist/review/{{pid}}/session?session={v}",
            "flags": f"/therapist/review/{v}/flags",
            "uploads": f"/therapist/review/{v}/from-patient",
            "questionnaires": f"/therapist/review/{v}/from-patient",
            "inbox": f"/therapist/inbox/{v}",
            "adherence": f"/therapist/tracker/adherence?patient={v}"}.get(kind)


def item_href(item) -> Optional[str]:
    href = target_href(item.target)
    return href.replace("{pid}", quote(item.patient_id, safe="")) if href else None


def adherence_footer_lines(lines: List[str]) -> List[str]:
    """From views.adherence_lines, the lines the week table does not already show."""
    keep = ("Adherence:", "First week", "Starts", "Superseded")
    return [line for line in lines[1:] if line.startswith(keep)]


def installation_to_store(entered: Dict[str, int], stored: Dict[str, int]) -> Dict[str, int]:
    """Store a value when it differs from the built-in default, or when the installation already set it."""
    return {k: int(v) for k, v in entered.items() if int(v) != ptthresholds.THRESHOLDS[k].default or k in stored}


def program_filters(programs) -> List[tuple]:
    return [("all", "All programs")] + [(p.id, p.name) for p in programs] + [("custom", "Custom programs")]
