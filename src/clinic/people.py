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


# ----------------------------------------------------------------------------- History (feature 021 N4)

PAGE = 200
KINDS = (("all", "Everything"), ("accounts", "Account changes"), ("signins", "Staff sign-ins"))
_ACCOUNT_EVENTS = {
    "account_created": "Account created", "invite_created": "Invite created", "invite_used": "Invite used",
    "invite_revoked": "Invite revoked", "account_disabled": "Account disabled", "account_enabled": "Account re-enabled",
    "patient_reassigned": "Patient moved to another therapist", "prefs_changed": "Settings changed",
}
_SIGNIN_EVENTS = {
    "login_ok": "Signed in", "login_failed": "Sign-in failed", "locked_out": "Locked out after failed sign-ins",
    "logout": "Signed out", "password_set": "Installation password set", "password_cleared": "Installation password cleared",
}


def kind_key(value) -> str:
    return value if value in dict(KINDS) else "all"


def _name(store: SessionStore, account_id) -> str:
    if account_id is None:
        return "nobody recorded"
    account = store.account_get(int(account_id))
    if account is None:
        return "a removed account"
    if account.role == "patient":
        return account.patient_id or "a patient"         # a patient appears only by code
    return account.display_name or account.username


def _subject(store: SessionStore, subject: Optional[str]) -> str:
    """To whom or what, as names and patient codes only: "therapist:5" → the account's name, "invite:3" → "invite 3",
    "P-001->4" → "P-001 to <name>"."""
    if not subject:
        return ""
    if "->" in subject:
        pid, _, tid = subject.partition("->")
        return f"{pid} to {_name(store, tid) if tid.isdigit() else tid}"
    parts = subject.split(":")
    if parts[-2:-1] == ["invite"] or parts[0] == "invite":
        return f"{parts[0]} invite {parts[-1]}" if parts[0] != "invite" else f"invite {parts[-1]}"
    if len(parts) == 2 and parts[1].isdigit():
        return f"{_name(store, parts[1])} ({parts[0]})"
    return subject


def _signin_who(store: SessionStore, account_id) -> str:
    if account_id is None:
        return "account not recorded"                     # before v19
    if int(account_id) == store.UNKNOWN_USERNAME:
        return "unknown username"
    return _name(store, account_id)


def history(store: SessionStore, actor: Account, kind: str = "all", page: int = 0) -> dict:
    """Account changes and staff sign-in events, newest first, PAGE rows at a time, with names resolved. No clinical
    field and no patient access history (that stays on the patient's page). Admins only."""
    _require_admin(actor)
    kind, page = kind_key(kind), max(0, int(page or 0))
    want = (page + 1) * PAGE + 1                          # one more than shown, to know whether older rows exist
    rows: List[dict] = []
    with _every_patient(store):
        if kind in ("all", "accounts"):
            for r in store.account_audit_list(want):
                rows.append({"at": r["at"], "kind": "Account", "what": _ACCOUNT_EVENTS.get(r["event"], r["event"]),
                             "who": _name(store, r["actor"]) if r["actor"] is not None else "the system",
                             "subject": _subject(store, r["subject"])})
        if kind in ("all", "signins"):
            for r in store.admin_audit_list(want):
                rows.append({"at": r["at"], "kind": "Sign-in", "what": _SIGNIN_EVENTS.get(r["event"], r["event"]),
                             "who": _signin_who(store, r.get("account_id")), "subject": ""})
    rows.sort(key=lambda r: r["at"], reverse=True)
    shown = rows[page * PAGE:(page + 1) * PAGE]
    for r in shown:
        r["when"] = r["at"][:16].replace("T", " ")
    return {"kind": kind, "page": page, "rows": shown, "older": len(rows) > (page + 1) * PAGE}
