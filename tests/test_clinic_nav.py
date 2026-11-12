"""Feature 019 slice 1 (T004, T008): the top bar and its menus by role. Replaces the Streamlit sidebar tests at
cutover."""

from src.clinic import nav, signin
from tests.clinic_helpers import client, seed, sign_in


def keys(items):
    return [p.key for p in items]


def test_a_therapist_sees_daily_work_and_tools(tmp_db, fake_clock):
    made = seed(tmp_db, fake_clock)
    rivera = made["rivera"]
    assert keys(nav.main_items(rivera)) == ["dashboard", "inbox", "patients", "schedule"]
    assert "sessions" in keys(nav.tools_items(rivera)) and "how" in keys(nav.tools_items(rivera))
    assert keys(nav.me_items(rivera)) == ["settings"]                       # no People: not an admin
    assert nav.home(rivera) == "/therapist/dashboard"


def test_the_lead_therapist_is_also_an_admin(tmp_db, fake_clock):
    lead = seed(tmp_db, fake_clock)["therapist"]
    assert keys(nav.me_items(lead)) == ["settings", "people"]
    assert nav.role_text(lead) == "Therapist and admin"


def test_an_admin_who_is_not_a_therapist_sees_no_clinical_pages(tmp_db, fake_clock):
    sam = seed(tmp_db, fake_clock)["sam"]
    assert keys(nav.main_items(sam)) == ["people", "settings"]
    assert nav.tools_items(sam) == []
    assert nav.home(sam) == "/therapist/people"


def test_no_one_signed_in_gets_no_menu():
    assert nav.main_items(None) == nav.tools_items(None) == nav.me_items(None) == []


def test_every_page_needs_a_known_role_and_lives_under_the_prefix():
    for page in nav.PAGES:
        assert page.need in signin.NEEDS and page.href.startswith("/therapist/")


def test_the_top_bar_on_a_page(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c, "rivera")
        page = c.get("/therapist/settings").text
        assert '<nav class="nav" aria-label="Main"><a href="/therapist/dashboard">Dashboard</a><a href="/therapist/inbox">Inbox</a>' in page
        assert '<summary>Tools</summary>' in page and 'href="/therapist/people"' not in page
        assert 'href="/therapist/settings" aria-current="page"' in page
        assert "Signed in as <b>Rivera</b> · Therapist" in page


def test_safe_next():
    good = ["/therapist/settings", "/therapist/patients/P-001?tab=exercises"]
    bad = [None, "", "//evil.example", "https://evil.example/therapist", "/therapist//x", "/elsewhere",
           "/therapist\\x", "/therapist/signin", "/therapist/api/me", "/therapist/<script>"]
    assert [signin.safe_next(v) for v in good] == good
    assert [signin.safe_next(v) for v in bad] == [None] * len(bad)
