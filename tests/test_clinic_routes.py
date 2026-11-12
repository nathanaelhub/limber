"""Feature 019 slice 1 (T009, SC-004): the clinic app's route table.

Every route declares what it needs. An admin who is not a therapist is refused every clinical route, and a
therapist never reaches another therapist's patient on any route. This file grows with each slice: a route with
a patient in its path is checked here against `rivera`, who has P-002 only."""

import re

import pytest

from src.clinic import signin
from src.ptlog.store import SessionStore
from tests.clinic_helpers import client, seed, sign_in

# Paths that take a patient, plan, visit or file, with how to fill them for another therapist's patient. Each
# slice that adds such a route adds its pattern here; an unknown placeholder fails the walk below.
OTHERS = {"patient_id": "P-001"}


def _app(tmp_db, fake_clock):
    from interfaces.clinic import create_app
    return create_app(db_path=tmp_db, key=b"k" * 32, allowed_origins=["http://testserver"], clock=fake_clock)


def test_every_route_declares_a_known_need(tmp_db, fake_clock):
    app = _app(tmp_db, fake_clock)
    assert app.state.registry
    for route in app.state.registry:
        assert route.need in signin.NEEDS, route
        assert route.path.startswith("/therapist"), route


def test_only_the_sign_in_routes_health_and_files_are_public(tmp_db, fake_clock):
    public = {r.path for r in _app(tmp_db, fake_clock).state.registry if r.need == "public"}
    assert public == {"/therapist/", "/therapist/signin", "/therapist/api/login", "/therapist/api/health",
                      "/therapist/static"}


def test_a_route_without_a_known_need_cannot_be_added():
    with pytest.raises(ValueError):
        signin.require(None, "everyone")


def test_every_mounted_route_is_in_the_registry(tmp_db, fake_clock):
    app = _app(tmp_db, fake_clock)
    known = {r.path for r in app.state.registry} | {"/therapist"}            # the bare prefix redirects
    for route in app.routes:
        assert route.path in known, route.path


def _concrete(path):
    names = re.findall(r"{(\w+)(?::\w+)?}", path)
    unknown = [n for n in names if n not in OTHERS]
    assert not unknown, f"{path}: add {unknown} to OTHERS"
    return re.sub(r"{(\w+)(?::\w+)?}", lambda m: OTHERS[m.group(1)], path)


def test_an_admin_who_is_not_a_therapist_is_refused_every_clinical_route(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c, "sam")
        clinical = [r for r in c.app.state.registry if r.need == "therapist"]
        assert clinical
        for route in clinical:
            if "GET" not in route.methods:
                continue
            r = c.get(_concrete(route.path), follow_redirects=False)
            assert r.status_code == 403, route.path


def test_a_therapist_cannot_reach_another_therapists_patient(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c, "rivera")
        for route in c.app.state.registry:
            if "{" not in route.path or "GET" not in route.methods:
                continue
            assert c.get(_concrete(route.path)).status_code == 404, route.path


def test_every_request_store_is_limited_to_the_caseload(tmp_db, fake_clock):
    """The opener restricts before the handler: rivera's store sees P-002 and not P-001."""
    from src.clinic import signin as s
    from src.portal import accounts
    made = seed(tmp_db, fake_clock)
    with SessionStore(tmp_db, clock=fake_clock).open() as store:
        accounts.restrict(store, made["rivera"])
        assert "P-002" in store.visible and "P-001" not in store.visible
    assert s.require(made["sam"], "therapist") == 403 and s.require(made["sam"], "admin") is None


def test_unbuilt_pages_say_so_and_list_what_works(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        page = c.get("/therapist/inbox").text
        assert "not online yet" in page and 'href="/therapist/settings"' in page
