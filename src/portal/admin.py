"""
Therapist sign-in (feature 007, US6; per account since feature 016): the staff door on the front page,
single-use passes that hand a signed-in person over to the therapist app, and their sign-ins.

The installation password of feature 007 is now the password of the first admin-therapist account
(username "therapist"); setting it from the command line still works, and a door that is given no
username checks it, so a one-therapist installation signs in exactly as before. Nothing here knows
about web frameworks.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, List, Optional

from src.portal import accounts
from src.portal.access import DENIED_ADMIN_MESSAGE, AccessDenied, LockedOut, LoginLimiter, token_hash
from src.ptlog.models import Account, PortalError
from src.ptlog.store import SessionStore, _ts_key

MIN_LENGTH, MAX_LENGTH = accounts.MIN_PASSWORD, accounts.MAX_PASSWORD
PASS_LIFETIME = timedelta(seconds=60)
SIGN_IN_LIFETIME = timedelta(hours=8)
STAFF = ("admin", "therapist")


class NotConfigured(PortalError):
    def __init__(self):
        super().__init__("Therapist sign-in has not been set up on this installation. "
                         "Set a password with: python interfaces/cli.py portal admin set-password")


def password_is_set(store: SessionStore) -> bool:
    return store.staff_password_exists()


def set_password(store: SessionStore, password: Optional[str]) -> Account:
    """Set the installation account's password, creating that account the first time."""
    salt, digest = accounts.hash_password(password)
    account = store.installation_account()
    if account is None:
        account = accounts.create_account(store, username="therapist", display_name="Therapist",
                                          password=password, role="therapist", is_admin=True)
    else:
        store.account_set_password(account.id, salt, digest)
    store.admin_audit_add("password_set")
    return account


def clear_password(store: SessionStore) -> bool:
    account = store.installation_account()
    if account is None or not account.has_password:
        return False
    store.account_set_password(account.id, None, None)
    store.admin_audit_add("password_cleared")
    return True


def verify_password(store: SessionStore, password: Optional[str]) -> bool:
    account = store.installation_account()
    return account is not None and accounts.password_matches(store, account.id, password)


def check_password(store: SessionStore, password: Optional[str], client: str, limiter: LoginLimiter,
                   username: Optional[str] = None) -> Account:
    """The staff account signing in. Raise NotConfigured, LockedOut, or AccessDenied."""
    if not password_is_set(store):
        raise NotConfigured()
    if not username:
        installation = store.installation_account()
        username = installation.username if installation and installation.has_password else "-"
    try:
        account = accounts.authenticate(store, username, password, client, limiter, roles=STAFF)
    except LockedOut:
        store.admin_audit_add("locked_out", client)
        raise
    except AccessDenied:
        store.admin_audit_add("login_failed", client)
        raise AccessDenied(DENIED_ADMIN_MESSAGE)
    store.admin_audit_add("login_ok", client)
    return account


def _new_token(store: SessionStore, kind: str, lifetime: timedelta, account_id: int,
               clock: Callable[[], datetime]) -> str:
    import secrets
    token = secrets.token_urlsafe(32)
    store.admin_token_add(token_hash(token), kind, clock() + lifetime, account_id)
    return token


def _valid(store: SessionStore, token: Optional[str], kind: str, clock: Callable[[], datetime]) -> Optional[Account]:
    if not token or not isinstance(token, str):
        return None
    row = store.admin_token_get(token_hash(token))
    if row is None or row[0] != kind:
        return None
    account = store.account_get(row[2])
    if _ts_key(row[1]) <= _ts_key(clock().isoformat()) or account is None or account.status != "active":
        store.admin_token_delete(token_hash(token))
        return None
    return account


def issue_pass(store: SessionStore, account_id: Optional[int] = None,
               clock: Callable[[], datetime] = datetime.now) -> str:
    """A single-use pass, valid one minute, that the front page hands to the therapist app."""
    if account_id is None:
        account_id = store.installation_account().id
    return _new_token(store, "pass", PASS_LIFETIME, account_id, clock)


def redeem_pass(store: SessionStore, a_pass: Optional[str], clock: Callable[[], datetime] = datetime.now) -> Optional[str]:
    """Exchange a valid pass for a sign-in token of the same account; the pass stops working."""
    account = _valid(store, a_pass, "pass", clock)
    if account is None or not store.admin_token_delete(token_hash(a_pass)):
        return None
    return _new_token(store, "signin", SIGN_IN_LIFETIME, account.id, clock)


def sign_in(store: SessionStore, password: Optional[str], client: str, limiter: LoginLimiter,
            clock: Callable[[], datetime] = datetime.now, username: Optional[str] = None) -> str:
    account = check_password(store, password, client, limiter, username=username)
    return _new_token(store, "signin", SIGN_IN_LIFETIME, account.id, clock)


def signed_in(store: SessionStore, token: Optional[str], clock: Callable[[], datetime] = datetime.now) -> Optional[Account]:
    """The signed-in staff account for this token, or None."""
    return _valid(store, token, "signin", clock)


def sign_out(store: SessionStore, token: Optional[str], client: Optional[str] = None) -> None:
    if token and store.admin_token_delete(token_hash(token)):
        store.admin_audit_add("logout", client)


def history(store: SessionStore, limit: int = 200) -> List[dict]:
    return store.admin_audit_list(limit)
