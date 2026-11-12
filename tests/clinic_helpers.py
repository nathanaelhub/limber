"""Shared set-up for the clinic app tests (feature 019)."""

from contextlib import contextmanager

from starlette.testclient import TestClient

from interfaces.clinic import create_app
from src.portal import accounts, admin
from src.ptlog.store import SessionStore

KEY = b"k" * 32
ORIGIN = "http://testserver"
H = {"Origin": ORIGIN}
PASSWORD = "correct horse battery"
STAFF = {   # username: (role, is_admin)
    "rivera": ("therapist", False),
    "sam": ("admin", True),
}


def seed(db, clock):
    """The installation account (therapist and admin), a second therapist, an admin who is not a therapist,
    and one patient on each therapist's caseload."""
    with SessionStore(db, clock=clock).open() as store:
        lead = admin.set_password(store, PASSWORD)
        made = {"therapist": lead}
        for username, (role, is_admin) in STAFF.items():
            made[username] = accounts.create_account(store, username=username, display_name=username.title(),
                                                     password=PASSWORD, role=role, is_admin=is_admin)
        accounts.add_patient(store, lead, "P-001")
        accounts.add_patient(store, made["rivera"], "P-002")
    return made


@contextmanager
def client(db, clock, secure=False, base=ORIGIN):
    app = create_app(db_path=db, key=KEY, allowed_origins=[ORIGIN], clock=clock, secure_cookie=secure)
    with TestClient(app, base_url=base) as c:
        yield c


def sign_in(c, username="therapist", password=PASSWORD):
    r = c.post("/therapist/api/login", json={"username": username, "password": password}, headers=H)
    assert r.status_code == 200, r.text
    return r
