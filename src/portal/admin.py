"""
Therapist sign-in (feature 007, US6): one password per installation, single-use passes that hand a
therapist over from the front page to the therapist app, and therapist sign-ins.

The password is set only from the command line on the machine itself and is stored as a salted
scrypt hash. Nothing here knows about web frameworks.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from src.portal.access import DENIED_ADMIN_MESSAGE, AccessDenied, LockedOut, LoginLimiter, token_hash
from src.ptlog.models import PortalError
from src.ptlog.store import SessionStore, _ts_key

MIN_LENGTH, MAX_LENGTH = 12, 256
PASS_LIFETIME = timedelta(seconds=60)
SIGN_IN_LIFETIME = timedelta(hours=8)
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


class NotConfigured(PortalError):
    def __init__(self):
        super().__init__("Therapist sign-in has not been set up on this installation. "
                         "Set a password with: python interfaces/cli.py portal admin set-password")


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT).hex()


def password_is_set(store: SessionStore) -> bool:
    return store.admin_get() is not None


def set_password(store: SessionStore, password: Optional[str]) -> None:
    if not isinstance(password, str) or not MIN_LENGTH <= len(password) <= MAX_LENGTH or not password.strip():
        raise PortalError(f"The therapist password needs {MIN_LENGTH} to {MAX_LENGTH} characters")
    salt = secrets.token_bytes(16)
    store.admin_set(salt.hex(), _hash(password, salt))
    store.admin_audit_add("password_set")


def clear_password(store: SessionStore) -> bool:
    cleared = store.admin_clear()
    if cleared:
        store.admin_audit_add("password_cleared")
    return cleared


def verify_password(store: SessionStore, password: Optional[str]) -> bool:
    row = store.admin_get()
    if row is None or not isinstance(password, str) or not password or len(password) > MAX_LENGTH:
        return False
    salt, stored, _ = row
    return hmac.compare_digest(_hash(password, bytes.fromhex(salt)), stored)


def _new_token(store: SessionStore, kind: str, lifetime: timedelta, clock: Callable[[], datetime]) -> str:
    token = secrets.token_urlsafe(32)
    store.admin_token_add(token_hash(token), kind, clock() + lifetime)
    return token


def _valid(store: SessionStore, token: Optional[str], kind: str, clock: Callable[[], datetime]) -> bool:
    if not token or not isinstance(token, str):
        return False
    row = store.admin_token_get(token_hash(token))
    if row is None or row[0] != kind:
        return False
    if _ts_key(row[1]) <= _ts_key(clock().isoformat()):
        store.admin_token_delete(token_hash(token))
        return False
    return True


def check_password(store: SessionStore, password: Optional[str], client: str, limiter: LoginLimiter) -> None:
    """Raise NotConfigured, LockedOut, or AccessDenied; return normally when the password is right."""
    if not password_is_set(store):
        raise NotConfigured()
    wait = limiter.retry_after(client)
    if wait:
        store.admin_audit_add("locked_out", client)
        raise LockedOut(wait)
    if not verify_password(store, password):
        limiter.failure(client)
        store.admin_audit_add("login_failed", client)
        raise AccessDenied(DENIED_ADMIN_MESSAGE)
    limiter.success(client)
    store.admin_audit_add("login_ok", client)


def issue_pass(store: SessionStore, clock: Callable[[], datetime] = datetime.now) -> str:
    """A single-use pass, valid one minute, that the front page hands to the therapist app."""
    return _new_token(store, "pass", PASS_LIFETIME, clock)


def redeem_pass(store: SessionStore, a_pass: Optional[str], clock: Callable[[], datetime] = datetime.now) -> Optional[str]:
    """Exchange a valid pass for a therapist sign-in token; the pass stops working."""
    if not _valid(store, a_pass, "pass", clock):
        return None
    if not store.admin_token_delete(token_hash(a_pass)):
        return None
    return _new_token(store, "signin", SIGN_IN_LIFETIME, clock)


def sign_in(store: SessionStore, password: Optional[str], client: str, limiter: LoginLimiter,
            clock: Callable[[], datetime] = datetime.now) -> str:
    check_password(store, password, client, limiter)
    return _new_token(store, "signin", SIGN_IN_LIFETIME, clock)


def signed_in(store: SessionStore, token: Optional[str], clock: Callable[[], datetime] = datetime.now) -> bool:
    return _valid(store, token, "signin", clock)


def sign_out(store: SessionStore, token: Optional[str], client: Optional[str] = None) -> None:
    if token and store.admin_token_delete(token_hash(token)):
        store.admin_audit_add("logout", client)


def history(store: SessionStore, limit: int = 200) -> List[dict]:
    return store.admin_audit_list(limit)
