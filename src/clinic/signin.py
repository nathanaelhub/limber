"""Who is signed in to the clinic app, and what they may reach (feature 019, FR-002 to FR-004).

Staff arrive by the portal's Therapist door with a single-use pass, or sign in on the clinic's own sign-in page.
Either way the sign-in lives in the `limber_staff` cookie, scoped to /therapist. Every route names what it needs:

    public     anyone (the sign-in page, health, static files)
    any        any signed-in, active staff account
    therapist  a therapist: clinical pages; an admin who is not a therapist sees no clinical data
    admin      an admin: People
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable, Optional

from src.portal import admin
from src.ptlog.models import Account
from src.ptlog.store import SessionStore

COOKIE = "limber_staff"
PREFIX = "/therapist"
NEEDS = ("public", "any", "therapist", "admin")
LIFETIME_SECONDS = int(admin.SIGN_IN_LIFETIME.total_seconds())


def account_for(store: SessionStore, token: Optional[str],
                clock: Callable[[], datetime] = datetime.now) -> Optional[Account]:
    """The active staff account this cookie signs in, or None."""
    if not token or not isinstance(token, str) or len(token) > 200:
        return None
    account = admin.signed_in(store, token, clock)
    if account is None or account.status != "active" or account.role not in admin.STAFF:
        return None
    return account


def require(account: Optional[Account], need: str) -> Optional[int]:
    """None when the account may reach a route that needs this; otherwise the refusal: 401 or 403."""
    if need not in NEEDS:
        raise ValueError(f"Unknown need {need!r}; a route needs one of {', '.join(NEEDS)}")
    if need == "public":
        return None
    if account is None:
        return 401
    if need == "therapist" and account.role != "therapist":
        return 403
    if need == "admin" and not account.is_admin:
        return 403
    return None


_SAFE = re.compile(r"/therapist(/[A-Za-z0-9._~/-]*)?(\?[A-Za-z0-9._~=&%-]*)?")


def safe_next(value: Optional[str]) -> Optional[str]:
    """Where to go after signing in: only a plain path inside the clinic app, never another site."""
    if not value or not isinstance(value, str) or len(value) > 300:
        return None
    if "//" in value or "\\" in value or not _SAFE.fullmatch(value):
        return None
    if value.startswith(PREFIX + "/signin") or value.startswith(PREFIX + "/api/"):
        return None
    return value
