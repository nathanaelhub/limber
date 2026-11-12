"""The People page's rules (feature 019 slice 4, T022): accounts, invites, disabling, and which therapist each
patient belongs to. Admins only; refused for anyone else.

An admin who is not a therapist sees no clinical data, so their store is limited to no patients. People needs
every patient's code and caseload to reassign them, so this module alone lifts that limit while it reads, and
returns only codes, names, roles and statuses: never a clinical field.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import List, Optional, Tuple

from src.portal import accounts
from src.ptlog.models import Account
from src.ptlog.store import SessionStore


@contextmanager
def _every_patient(store: SessionStore):
    kept = store.visible
    store.restrict(None)
    try:
        yield store
    finally:
        store.visible = kept


def _require_admin(actor: Optional[Account]) -> None:
    if actor is None or not actor.is_admin or actor.status != "active":
        raise accounts.NotAllowed()


def staff(store: SessionStore, actor: Account) -> List[dict]:
    """Every staff account, with how many patients each therapist has."""
    _require_admin(actor)
    with _every_patient(store):
        out = []
        for a in store.account_list():
            if a.role == "patient":
                continue
            out.append({"id": a.id, "name": a.display_name or a.username, "username": a.username,
                        "role": ("Therapist and admin" if a.is_admin and a.is_therapist else
                                 "Therapist" if a.is_therapist else "Admin"),
                        "status": a.status, "patients": len(store.caseload_patients(a.id)) if a.is_therapist else None,
                        "you": a.id == actor.id})
        return out


def patient_accounts(store: SessionStore, actor: Account) -> List[dict]:
    """Patients with a username, and whose caseload they are on."""
    _require_admin(actor)
    with _every_patient(store):
        return [{"id": r["id"], "patient_id": r["patient_id"], "username": r["username"], "therapist": r["therapist"],
                 "status": r["status"]} for r in accounts.people(store, actor)
                if r["id"] is not None and r["role"] == "patient"]


def invites(store: SessionStore, actor: Account) -> List[dict]:
    _require_admin(actor)
    with _every_patient(store):
        return [{"id": r["invite_id"], "role": r["role"], "patient_id": r["patient_id"], "therapist": r["therapist"],
                 "expires": r["since"]} for r in accounts.people(store, actor) if r["status"] == "invited"]


def therapists(store: SessionStore) -> List[Account]:
    return [a for a in store.account_list() if a.is_therapist and a.status == "active"]


def patient_ids(store: SessionStore, actor: Account) -> List[Tuple[str, str]]:
    """(patient code, their therapist's name) for every patient, for reassigning."""
    _require_admin(actor)
    with _every_patient(store):
        names = {a.id: a.display_name or a.username for a in store.account_list()}
        return [(p.id, names.get(store.caseload_of(p.id), "nobody")) for p in store.list_patients() if not p.is_builtin]


def invite(store: SessionStore, actor: Account, role: str, therapist_id, patient_id, make_admin: bool,
           clock=datetime.now):
    with _every_patient(store):
        return accounts.create_invite(store, actor, role, therapist_id=therapist_id, patient_id=patient_id or None,
                                      make_admin=make_admin, clock=clock)


def revoke(store: SessionStore, actor: Account, invite_id: int) -> bool:
    return accounts.revoke_invite(store, actor, invite_id)


def set_status(store: SessionStore, actor: Account, account_id: int, status: str) -> Account:
    if account_id == actor.id:
        raise accounts.PortalError("You can't disable your own account here.")
    return accounts.set_status(store, actor, account_id, status)


def reassign(store: SessionStore, actor: Account, patient_id: str, therapist_id: int) -> None:
    with _every_patient(store):
        accounts.reassign(store, actor, patient_id, therapist_id)


def expires_words(iso: str, now: datetime) -> str:
    days = (datetime.fromisoformat(iso[:19]) - now).days
    return "Ends today" if days <= 0 else f"Ends in {days} day{'s' if days != 1 else ''}"
