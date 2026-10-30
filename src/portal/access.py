"""
Access to the patient portal (feature 007): therapist-issued codes, the keyed lookup hash, the
server key, the login limiter, and sign-ins. Pure logic plus calls into SessionStore; no web
framework here.

Nothing identifying is handled: a code belongs to a pseudonymous patient ID, the code itself is
never stored (only HMAC-SHA256 under the server key), and a visitor's address is kept only as a
short keyed hash.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.ptlog.models import AccessStatus, PortalError
from src.ptlog.store import SessionStore, _ts_key

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"     # Crockford base32: no I, L, O, U
CODE_LENGTH = 12                                  # 60 bits
DEFAULT_DAYS, MAX_DAYS = 90, 365
IDLE_LIMIT = timedelta(minutes=30)
ABSOLUTE_LIMIT = timedelta(hours=12)
DEVICE_LIMIT = timedelta(days=30)        # an installed patient app on the patient's own phone (feature 010)
SIGN_INS_PER_PATIENT = 3
DENIED_MESSAGE = "That code did not work. Check it, or ask your therapist for a new one."
DENIED_ADMIN_MESSAGE = "That password did not work."


class AccessDenied(PortalError):
    """Sign-in refused. The message is the same whatever the reason, so codes cannot be probed."""

    def __init__(self, message: str = DENIED_MESSAGE):
        super().__init__(message)


class LockedOut(PortalError):
    def __init__(self, retry_after: int):
        super().__init__(f"Too many attempts. Try again in {max(1, retry_after // 60)} minute(s).")
        self.retry_after = retry_after


# ----------------------------------------------------------------------------- codes

def generate_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i:i + 4] for i in range(0, CODE_LENGTH, 4))


def normalize(code: Optional[str]) -> str:
    """Upper-case, drop spaces and dashes, read O as 0 and I or L as 1. Raises PortalError when the
    result is not twelve characters of the code alphabet."""
    text = (code or "").upper().replace("-", "").replace(" ", "")
    text = text.replace("O", "0").replace("I", "1").replace("L", "1")
    if len(text) != CODE_LENGTH or any(ch not in ALPHABET for ch in text):
        raise PortalError("An access code has twelve letters and digits, like 7K3M-QX2P-9RTD")
    return text


def lookup_hash(key: bytes, normalized_code: str) -> str:
    return hmac.new(key, b"code:" + normalized_code.encode(), hashlib.sha256).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_marker(key: bytes, address: Optional[str]) -> str:
    """A short keyed hash standing in for a visitor's address in the access history."""
    return hmac.new(key, b"client:" + (address or "unknown").encode(), hashlib.sha256).hexdigest()[:16]


# ----------------------------------------------------------------------------- server key

def default_key_path(db_path: Path) -> Path:
    return Path(db_path).parent / "portal.key"


def load_key(path: Path) -> bytes:
    """The 32-byte server key: PTASSIST_PORTAL_KEY (64 hex characters) or a private file created on
    first use. It lives outside the database, so a leaked database does not expose usable hashes."""
    env = os.environ.get("PTASSIST_PORTAL_KEY")
    if env:
        try:
            key = bytes.fromhex(env.strip())
        except ValueError:
            key = b""
        if len(key) != 32:
            raise PortalError("PTASSIST_PORTAL_KEY must be 64 hexadecimal characters")
        return key
    path = Path(path)
    if path.exists():
        key = path.read_bytes()
        if len(key) != 32:
            raise PortalError(f"{path} is not a valid portal key file")
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    return key


# ----------------------------------------------------------------------------- login limiter

class LoginLimiter:
    """In-memory limits on failed sign-ins: per client (five per fifteen minutes, then a lock-out that
    doubles with each further failure) and overall (thirty failures per minute pause everyone)."""

    WINDOW = 15 * 60
    PER_CLIENT = 5
    BASE_LOCKOUT = 60
    GLOBAL_PER_MINUTE = 30

    def __init__(self, clock: Callable[[], datetime] = datetime.now):
        self.clock = clock
        self._failures: Dict[str, List[datetime]] = {}
        self._locked_until: Dict[str, datetime] = {}
        self._all: List[datetime] = []

    def _recent(self, client: str, now: datetime) -> List[datetime]:
        kept = [t for t in self._failures.get(client, []) if (now - t).total_seconds() < self.WINDOW]
        if kept:
            self._failures[client] = kept
        else:
            self._failures.pop(client, None)
        return kept

    def retry_after(self, client: str) -> int:
        """Seconds the client must wait; 0 when an attempt may be made."""
        now = self.clock()
        self._all = [t for t in self._all if (now - t).total_seconds() < 60]
        waits = [0]
        if len(self._all) >= self.GLOBAL_PER_MINUTE:
            waits.append(math.ceil(60 - (now - self._all[0]).total_seconds()))
        until = self._locked_until.get(client)
        if until is not None:
            if until > now and self._recent(client, now):
                waits.append(math.ceil((until - now).total_seconds()))
            elif until <= now and not self._recent(client, now):
                self._locked_until.pop(client, None)
        return max(waits)

    def failure(self, client: str) -> None:
        now = self.clock()
        self._all.append(now)
        recent = self._recent(client, now) + [now]
        self._failures[client] = recent
        over = len(recent) - self.PER_CLIENT
        if over >= 0:
            self._locked_until[client] = now + timedelta(seconds=self.BASE_LOCKOUT * (2 ** over))

    def success(self, client: str) -> None:
        self._failures.pop(client, None)
        self._locked_until.pop(client, None)


# ----------------------------------------------------------------------------- issue, sign in, sign out

def issue_code(store: SessionStore, key: bytes, patient_id: str, days: int = DEFAULT_DAYS) -> Tuple[str, AccessStatus]:
    """Create the patient's access code. Returns the code (to be shown once) and the stored status."""
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= MAX_DAYS:
        raise PortalError(f"A code can be valid for 1 to {MAX_DAYS} days")
    code = generate_code()
    status = store.portal_set_code(patient_id, lookup_hash(key, normalize(code)), store.clock() + timedelta(days=days))
    store.portal_audit_add("code_created", patient_id, None, f"{days}d")
    return code, status


def revoke_code(store: SessionStore, patient_id: str) -> bool:
    revoked = store.portal_revoke(patient_id)
    if revoked:
        store.portal_audit_add("code_revoked", patient_id, None)
    return revoked


def sign_in(store: SessionStore, key: bytes, code: Optional[str], client: str, limiter: LoginLimiter,
            clock: Callable[[], datetime] = datetime.now, device: bool = False) -> str:
    """Check the code and open a sign-in. Returns the cookie token (only its hash is stored).
    A device sign-in (the installed app) lasts DEVICE_LIMIT with no idle limit; a browser sign-in
    keeps the idle and absolute limits. Raises LockedOut or AccessDenied; every refusal reads the
    same to the visitor."""
    wait = limiter.retry_after(client)
    if wait:
        store.portal_audit_add("locked_out", None, client)
        raise LockedOut(wait)

    def refuse(detail: str, patient_id: Optional[str] = None):
        limiter.failure(client)
        store.portal_audit_add("login_failed", patient_id, client, detail)
        raise AccessDenied()

    try:
        normalized = normalize(code)
    except PortalError:
        refuse("unknown_code")
    status = store.portal_lookup(lookup_hash(key, normalized))
    if status is None:
        refuse("unknown_code")
    if status.state != "active":
        refuse(status.state, status.patient_id)
    if store.get_discharge(status.patient_id) is not None:
        refuse("discharged", status.patient_id)

    limiter.success(client)
    token = ("d." if device else "b.") + secrets.token_urlsafe(32)      # the prefix says which rules apply
    store.portal_signin_create(token_hash(token), status.patient_id,
                               clock() + (DEVICE_LIMIT if device else ABSOLUTE_LIMIT), keep=SIGN_INS_PER_PATIENT)
    store.portal_touch(status.patient_id)
    store.portal_audit_add("login_ok", status.patient_id, client)
    return token


def current_patient(store: SessionStore, token: Optional[str],
                    clock: Callable[[], datetime] = datetime.now) -> Optional[str]:
    """The signed-in patient for this cookie token, or None. Enforces the idle and absolute limits,
    a still-active code, and that the patient is not discharged."""
    if not token:
        return None
    digest = token_hash(token)
    signin = store.portal_signin_get(digest)
    if signin is None:
        return None
    now = clock()
    idle = now - datetime.fromisoformat(signin.last_seen_at)
    expired = _ts_key(signin.expires_at) <= _ts_key(now.isoformat())
    if token.startswith("d."):
        idle = timedelta(0)                                              # a device sign-in has no idle limit
    if token.startswith("a."):                                           # a password account (feature 016)
        account = store.account_by_patient(signin.patient_id)
        allowed = account is not None and account.status == "active"
    else:
        allowed = store.portal_status(signin.patient_id).state == "active"
    if (idle > IDLE_LIMIT or expired or not allowed
            or store.get_discharge(signin.patient_id) is not None):
        store.portal_signin_delete(digest)
        return None
    store.portal_signin_touch(digest)
    return signin.patient_id


def sign_out(store: SessionStore, token: Optional[str], client: Optional[str] = None) -> None:
    if not token:
        return
    digest = token_hash(token)
    signin = store.portal_signin_get(digest)
    store.portal_signin_delete(digest)
    if signin is not None:
        store.portal_audit_add("logout", signin.patient_id, client)
