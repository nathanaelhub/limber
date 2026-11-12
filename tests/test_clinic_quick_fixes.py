"""Feature 019, quick fixes before the first showing (plan phase Q): patient search in the top bar, the Needs you
count on every page, and the count the page polls for. Owner's decision, 12 November 2026: the top bar may have
seven items (SC-001 amended)."""

import re

import pytest

from src.portal import messages
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in


@pytest.fixture
def world(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.update_patient("P-001", label="Knee")
        for pid in ("P-001", "P-002"):
            messages.set_enabled(s, pid, True)
            messages.send(s, pid, "patient", "A question", plan_id=s.plans(pid)[0].id)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        yield c, tmp_db, fake_clock


def top_bar(page):
    return re.search(r'<header class="top">.*?</header>', page, re.S).group(0)


def test_the_top_bar_has_seven_items_and_a_search(world):
    c, _, _ = world
    bar = top_bar(c.get("/therapist/dashboard").text)
    assert '<form class="find-form" method="get" action="/therapist/patients" role="search">' in bar
    assert 'name="q"' in bar and "Find a patient" in bar
    items = len(re.findall(r'<nav class="nav".*?</nav>', bar, re.S)[0].split("</a>")) - 1
    assert items == 4                                       # Dashboard, Inbox, Patients, Schedule
    assert bar.count('class="drop') == 2                    # Tools and Me: with search, seven items


def test_search_goes_straight_to_a_single_match(world):
    c, _, _ = world
    r = c.get("/therapist/patients?q=p-001", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/therapist/patients/P-001"
    assert c.get("/therapist/patients?q=knee", follow_redirects=False).headers["location"] == "/therapist/patients/P-001"
    page = c.get("/therapist/patients?q=zzz").text
    assert "No patient matches “zzz”" in page
    assert c.get("/therapist/patients?q=P-002", follow_redirects=False).status_code == 200   # rivera's: no match


def test_every_page_shows_the_needs_you_count(world):
    c, _, _ = world
    for path in ("/therapist/dashboard", "/therapist/patients", "/therapist/settings", "/therapist/schedule"):
        page = c.get(path).text
        assert '<a href="/therapist/inbox" data-badge>Inbox <span class="count" data-count>1<span class="vh"> need you' \
               '</span></span></a>' in page.replace(' aria-current="page"', ""), path
        assert "<title>(1) Limber" in page, path


def test_the_count_the_page_polls(world):
    c, db, clock = world
    assert c.get("/therapist/api/needs").json() == {"count": 1}
    with SessionStore(db, clock=clock).open() as s:
        plan = s.plans("P-001")[0].id
        s.messages_mark_read("P-001", from_sender="patient", plan_id=plan)
    assert c.get("/therapist/api/needs").json() == {"count": 0}
    assert "<title>Limber" in c.get("/therapist/dashboard").text


def test_admins_who_are_not_therapists_get_no_badge_or_search(world):
    c, _, _ = world
    c.post("/therapist/api/logout", json={}, headers=H)
    sign_in(c, "sam")
    bar = top_bar(c.get("/therapist/people").text)
    assert "data-count" not in bar and "find-form" not in bar
    assert c.get("/therapist/api/needs").status_code == 403
