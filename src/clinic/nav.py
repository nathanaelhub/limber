"""The clinic app's top bar (feature 019, FR-006): main links, the Tools menu and the Me menu, by role.

Pages go online slice by slice; a page that is not online yet still has its link and says so plainly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.ptlog.models import Account


@dataclass(frozen=True)
class Page:
    key: str
    label: str
    path: str
    need: str            # see src/clinic/signin.py
    online: bool = False

    @property
    def href(self) -> str:
        return "/therapist" + self.path


PAGES = (
    Page("inbox", "Inbox", "/inbox", "therapist", online=True),
    Page("patients", "Patients", "/patients", "therapist"),
    Page("schedule", "Schedule", "/schedule", "therapist"),
    Page("dashboard", "Dashboard", "/dashboard", "therapist"),
    Page("live", "Live session", "/live", "therapist"),
    Page("video", "Video analysis", "/video", "therapist"),
    Page("sessions", "Sessions", "/sessions", "therapist"),
    Page("logs", "Observation logs", "/logs", "therapist"),
    Page("review", "Review", "/review", "therapist"),
    Page("tracker", "Tracker", "/tracker", "therapist"),
    Page("how", "How it works", "/how-it-works", "therapist"),
    Page("people", "People", "/people", "admin"),
    Page("settings", "My settings", "/settings", "any", online=True),
)
BY_KEY = {p.key: p for p in PAGES}
MAIN = ("inbox", "patients", "schedule")
ADMIN_MAIN = ("people", "settings")             # an admin who is not a therapist
TOOLS = ("dashboard", "live", "video", "sessions", "logs", "review", "tracker", "how")
ME = ("settings", "people")


def allowed(account: Optional[Account], page: Page) -> bool:
    from src.clinic.signin import require
    return require(account, page.need) is None


def _pick(account: Optional[Account], keys) -> List[Page]:
    return [BY_KEY[k] for k in keys if allowed(account, BY_KEY[k])]


def main_items(account: Optional[Account]) -> List[Page]:
    if account is None:
        return []
    return _pick(account, MAIN if account.role == "therapist" else ADMIN_MAIN)


def tools_items(account: Optional[Account]) -> List[Page]:
    return _pick(account, TOOLS) if account is not None else []


def me_items(account: Optional[Account]) -> List[Page]:
    return _pick(account, ME) if account is not None else []


def home(account: Optional[Account]) -> str:
    """Where a staff member lands after signing in."""
    if account is not None and account.role == "therapist":
        return BY_KEY["inbox"].href
    return BY_KEY["people"].href if account is not None and account.is_admin else BY_KEY["settings"].href


def online(account: Optional[Account]) -> List[Page]:
    """The pages this person can use today."""
    return [p for p in PAGES if p.online and allowed(account, p)]


def role_text(account: Account) -> str:
    if account.role == "therapist":
        return "Therapist and admin" if account.is_admin else "Therapist"
    return "Admin"
