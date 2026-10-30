"""
Accounts (feature 016): one per person, with a role of admin, therapist, or patient; invitations an admin
hands out as a single-use link; onboarding from that link; which therapist each patient belongs to; and
each person's accessibility preferences. Pure rules plus calls into SessionStore; no web framework here.

Nothing is sent anywhere: an invite is a link the admin copies. A display name is stored only on the
account and is never written to a log line, the audit history, or an export.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Set, Tuple

from src.portal import access
from src.portal.access import AccessDenied, LockedOut, LoginLimiter, token_hash
from src.ptlog.models import Account, Invitation, PortalError
from src.ptlog.privacy import validate_patient_id
from src.ptlog.store import SessionStore

ROLES = ("admin", "therapist", "patient")
INVITE_LIFETIME = timedelta(days=7)
MIN_PASSWORD, MAX_PASSWORD = 12, 256
MAX_NAME = 60
USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{2,31}")
PREFS = ("larger_text", "high_contrast", "reduced_motion")
PREF_CLASSES = {"larger_text": "a11y-large", "high_contrast": "a11y-contrast", "reduced_motion": "a11y-calm"}
DENIED = "That username and password did not work."
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


class NotAllowed(PortalError):
    """The signed-in person's role does not permit this."""

    def __init__(self, message: str = "Only an admin can do that."):
        super().__init__(message)


class InviteInvalid(PortalError):
    """An invite link that cannot be used. A revoked link reads the same as an expired one."""

    MESSAGES = {
        "used": "This invite link has already been used. Sign in on the Limber front page instead.",
        "expired": "This invite link has expired. Ask whoever sent it for a new one.",
    }

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(self.MESSAGES["used" if reason == "used" else "expired"])


# ----------------------------------------------------------------------------- validation and hashing

def _hash(password: str, salt: bytes) -> str:
    import hashlib
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT).hex()


def hash_password(password: Optional[str]) -> Tuple[str, str]:
    """(salt hex, hash hex) for a password that meets the rules; raises PortalError otherwise."""
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD or not password.strip():
        raise PortalError(f"A password needs {MIN_PASSWORD} to {MAX_PASSWORD} characters")
    salt = secrets.token_bytes(16)
    return salt.hex(), _hash(password, salt)


def password_matches(store: SessionStore, account_id: int, password: Optional[str]) -> bool:
    import hmac
    secret = store.account_secret(account_id)
    if secret is None or not isinstance(password, str) or not password or len(password) > MAX_PASSWORD:
        return False
    return hmac.compare_digest(_hash(password, bytes.fromhex(secret[0])), secret[1])


def clean_username(username: Optional[str]) -> str:
    text = (username or "").strip().lower() if isinstance(username, str) else ""
    if not USERNAME.fullmatch(text):
        raise PortalError("A username has 3 to 32 letters, digits, dots, dashes, or underscores, "
                          "and starts with a letter or digit")
    return text


def clean_name(name: Optional[str]) -> str:
    text = name.strip() if isinstance(name, str) else ""
    if not text or len(text) > MAX_NAME or any(ch in text for ch in "\r\n\t"):
        raise PortalError(f"A name needs 1 to {MAX_NAME} characters on one line")
    return text


# ----------------------------------------------------------------------------- accounts

def create_account(store: SessionStore, *, username: Optional[str], display_name: Optional[str],
                   password: Optional[str], role: str, is_admin: bool = False, patient_id: Optional[str] = None,
                   actor: Optional[Account] = None) -> Account:
    """Make an account directly (the command line, onboarding). An admin role is always an admin."""
    if role not in ROLES:
        raise PortalError(f"A role is one of {', '.join(ROLES)}")
    name, user = clean_name(display_name), clean_username(username)
    salt, digest = hash_password(password)
    if store.account_by_username(user) is not None:
        raise PortalError("That username is taken. Choose another.")
    if role == "patient":
        if patient_id is None or store.account_by_patient(patient_id) is not None:
            raise PortalError("That patient already has an account")
    account = store.account_create(user, name, role, role == "admin" or (is_admin and role == "therapist"),
                                   patient_id if role == "patient" else None, salt, digest)
    store.account_audit_add("account_created", actor.id if actor else None, f"{role}:{account.id}")
    return account


def authenticate(store: SessionStore, username: Optional[str], password: Optional[str], client: str,
                 limiter: LoginLimiter, roles: Tuple[str, ...] = ROLES) -> Account:
    """The account for this username and password, or AccessDenied / LockedOut. Failures are counted per
    client and per username, so one username cannot be guessed at from many places."""
    user = (username or "").strip().lower() if isinstance(username, str) else ""
    keyed = "user:" + user
    wait = max(limiter.retry_after(client), limiter.retry_after(keyed))
    if wait:
        raise LockedOut(wait)
    account = store.account_by_username(user) if user else None
    if (account is None or account.status != "active" or account.role not in roles
            or not password_matches(store, account.id, password)):
        limiter.failure(client)
        limiter.failure(keyed)
        raise AccessDenied(DENIED)
    limiter.success(client)
    limiter.success(keyed)
    return account


def _require_admin(actor: Optional[Account]) -> None:
    if actor is None or not actor.is_admin or actor.status != "active":
        raise NotAllowed()


def set_status(store: SessionStore, actor: Account, account_id: int, status: str) -> Account:
    """Disable or re-enable an account. Disabling ends its sign-ins; the last active admin stays."""
    _require_admin(actor)
    if status not in ("active", "disabled"):
        raise PortalError("Status is active or disabled")
    target = store.account_get(account_id)
    if target is None:
        raise PortalError("No such account")
    if status == "disabled" and target.is_admin:
        others = [a for a in store.account_list() if a.is_admin and a.status == "active" and a.id != target.id]
        if not others:
            raise PortalError("This is the last active admin, so it cannot be disabled")
    store.account_set_status(account_id, status)
    store.account_audit_add("account_disabled" if status == "disabled" else "account_enabled", actor.id,
                            f"{target.role}:{target.id}")
    return store.account_get(account_id)


def people(store: SessionStore, actor: Account) -> List[dict]:
    """Everyone with an account, then every invite still waiting, for the admin's People page."""
    _require_admin(actor)
    by_id = {a.id: a for a in store.account_list()}
    rows = []
    for a in by_id.values():
        therapist = by_id.get(store.caseload_of(a.patient_id)) if a.patient_id else None
        rows.append({"id": a.id, "display_name": a.display_name, "username": a.username,
                     "role": "admin + therapist" if a.is_admin and a.is_therapist else a.role,
                     "patient_id": a.patient_id, "therapist": therapist.username if therapist else None,
                     "status": a.status, "since": a.created_at, "invite_id": None})
    for inv in store.invite_list():
        if inv.state != "invited":
            continue
        therapist = by_id.get(inv.therapist_id)
        rows.append({"id": None, "display_name": None, "username": None,
                     "role": "admin + therapist" if inv.make_admin and inv.role == "therapist" else inv.role,
                     "patient_id": inv.patient_id, "therapist": therapist.username if therapist else None,
                     "status": "invited", "since": inv.expires_at, "invite_id": inv.id})
    return rows


def history(store: SessionStore, limit: int = 200) -> List[dict]:
    return store.account_audit_list(limit)


# ----------------------------------------------------------------------------- invitations

def create_invite(store: SessionStore, actor: Account, role: str, *, therapist_id: Optional[int] = None,
                  patient_id: Optional[str] = None, make_admin: bool = False,
                  clock: Callable[[], datetime] = datetime.now) -> Tuple[str, Invitation]:
    """A single-use invite, valid seven days. Returns the token (shown once, as a link) and the invite.
    A patient invite names the patient's pseudonymous ID and their therapist; the record is created now
    if it does not exist yet."""
    _require_admin(actor)
    if role not in ROLES:
        raise PortalError(f"A role is one of {', '.join(ROLES)}")
    if role == "patient":
        therapist = store.account_get(therapist_id) if therapist_id is not None else None
        if therapist is None or not therapist.is_therapist or therapist.status != "active":
            raise PortalError("Choose the patient's therapist")
        pid = validate_patient_id(patient_id)
        if store.account_by_patient(pid) is not None:
            raise PortalError(f"{pid} already has an account")
        if store.get_patient(pid) is None:
            add_patient(store, therapist, pid)
    else:
        therapist_id, pid = None, None
    token = secrets.token_urlsafe(24)
    invite = store.invite_add(token_hash(token), role, bool(make_admin) and role == "therapist", therapist_id, pid,
                              actor.id, clock() + INVITE_LIFETIME)
    store.account_audit_add("invite_created", actor.id, f"{role}:invite:{invite.id}")
    return token, invite


def check_invite(store: SessionStore, token: Optional[str], clock: Callable[[], datetime] = datetime.now) -> Invitation:
    invite = store.invite_by_token(token_hash(token), clock().isoformat()) if isinstance(token, str) and token else None
    if invite is None:
        raise InviteInvalid("unknown")
    if invite.state != "invited":
        raise InviteInvalid(invite.state)
    return invite


def revoke_invite(store: SessionStore, actor: Account, invite_id: int) -> bool:
    _require_admin(actor)
    revoked = store.invite_revoke(invite_id)
    if revoked:
        store.account_audit_add("invite_revoked", actor.id, f"invite:{invite_id}")
    return revoked


def accept_invite(store: SessionStore, token: Optional[str], *, display_name: Optional[str], username: Optional[str],
                  password: Optional[str], password_again: Optional[str], prefs: Optional[dict] = None,
                  clock: Callable[[], datetime] = datetime.now) -> Account:
    """Create the invited account. Any mistake leaves the link usable, so the person can fix it and retry."""
    invite = check_invite(store, token, clock)
    if password != password_again:
        raise PortalError("The two passwords do not match")
    account = create_account(store, username=username, display_name=display_name, password=password,
                             role=invite.role, is_admin=invite.make_admin, patient_id=invite.patient_id)
    if not store.invite_mark_used(invite.id, account.id):           # someone else used it a moment ago
        store.account_delete(account.id)
        raise InviteInvalid("used")
    if invite.role == "patient":
        store.caseload_set(invite.patient_id, invite.therapist_id)
    if prefs and invite.role == "patient":
        set_patient_prefs(store, invite.patient_id, prefs)
    elif prefs:
        set_prefs(store, account.id, prefs, audit=False)
    store.account_audit_add("invite_used", None, f"{invite.role}:{account.id}")
    return account


# ----------------------------------------------------------------------------- caseloads

def visible_patient_ids(store: SessionStore, account: Optional[Account]) -> Set[str]:
    """The patients this person may see. A therapist: their caseload, and if also an admin, every patient
    nobody has been given yet. An admin who is not a therapist sees no clinical data."""
    if account is None or account.role != "therapist" or account.status != "active":
        return set()
    ids = set(store.caseload_patients(account.id))
    if account.is_admin:
        ids |= set(store.unassigned_patients())
    return ids


def can_see(store: SessionStore, account: Optional[Account], patient_id: str) -> bool:
    return patient_id in visible_patient_ids(store, account)


def restrict(store: SessionStore, account: Optional[Account]) -> SessionStore:
    """Limit this store's reads to what the account may see."""
    return store.restrict(visible_patient_ids(store, account))


def assign(store: SessionStore, patient_id: str, therapist_id: int) -> None:
    therapist = store.account_get(therapist_id)
    if therapist is None or not therapist.is_therapist:
        raise PortalError("Choose a therapist")
    store.caseload_set(patient_id, therapist_id)


def add_patient(store: SessionStore, therapist: Optional[Account], patient_id: str, label: Optional[str] = None,
                notes: Optional[str] = None):
    """Register a patient and put them in this therapist's caseload (no account: an open installation)."""
    patient = store.add_patient(patient_id, label=label, notes=notes)
    if therapist is not None and therapist.is_therapist:
        store.caseload_set(patient.id, therapist.id)
        if store.visible is not None:
            store.visible.add(patient.id)
    return patient


def reassign(store: SessionStore, actor: Account, patient_id: str, therapist_id: int) -> None:
    _require_admin(actor)
    if not store.patient_exists(patient_id):
        raise PortalError(f"Patient '{patient_id}' not found")
    assign(store, patient_id, therapist_id)
    store.account_audit_add("patient_reassigned", actor.id, f"{patient_id}->{therapist_id}")


# ----------------------------------------------------------------------------- patients sign in with a password

def patient_sign_in(store: SessionStore, username: Optional[str], password: Optional[str], client: str,
                    limiter: LoginLimiter, clock: Callable[[], datetime] = datetime.now) -> str:
    """A browser sign-in to the portal from a patient account; the same limits as a code sign-in."""
    account = authenticate(store, username, password, client, limiter, roles=("patient",))
    if store.get_discharge(account.patient_id) is not None:
        store.portal_audit_add("login_failed", account.patient_id, client, "discharged")
        raise AccessDenied(DENIED)
    token = "a." + secrets.token_urlsafe(32)                       # "a.": an account, checked on every request
    store.portal_signin_create(token_hash(token), account.patient_id, clock() + access.ABSOLUTE_LIMIT,
                               keep=access.SIGN_INS_PER_PATIENT)
    store.portal_audit_add("login_ok", account.patient_id, client, "account")
    return token


# ----------------------------------------------------------------------------- preferences

def get_prefs(store: SessionStore, account_id: int) -> Dict[str, bool]:
    return _clean(store.account_prefs(account_id))


def set_prefs(store: SessionStore, account_id: int, prefs: Optional[dict], audit: bool = True) -> Dict[str, bool]:
    """Keep only the known settings, and only a real true turns one on."""
    clean = _clean(prefs)
    store.account_set_prefs(account_id, clean)
    if audit:
        store.account_audit_add("prefs_changed", account_id, None)
    return clean


def _clean(prefs: Optional[dict]) -> Dict[str, bool]:
    return {k: isinstance(prefs, dict) and prefs.get(k) is True for k in PREFS}


def get_patient_prefs(store: SessionStore, patient_id: str) -> Dict[str, bool]:
    """A patient's settings live with the patient, so a code-only patient has them too."""
    return _clean(store.patient_prefs(patient_id))


def set_patient_prefs(store: SessionStore, patient_id: str, prefs: Optional[dict]) -> Dict[str, bool]:
    clean = _clean(prefs)
    store.set_patient_prefs(patient_id, clean)
    return clean


def css_classes(prefs: Optional[dict]) -> str:
    return " ".join(PREF_CLASSES[k] for k in PREFS if prefs and prefs.get(k) is True)
