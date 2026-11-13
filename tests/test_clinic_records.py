"""Feature 019 slice 5a (T024, T025, FR-010, FR-011): the Dashboard (the therapist's home page), Sessions and
Observation logs, read from the record and limited to the caseload. Exports use the standard library only; the
rep CSV matches the old pandas export byte for byte."""

from datetime import datetime

from pathlib import Path

import pytest

from src.clinic import records
from src.ptlog.store import SessionStore
from tests.clinic_helpers import client, seed, sign_in

REPS = [(80, 50, 2.0), (70, 45, 2.5), (55, 40, 3.0)]


class Clock:
    """Settable, as make_session needs, and peekable, as the clinic's rules need."""

    def __init__(self, now):
        self.now = now

    def set(self, now):
        self.now = now

    def peek(self):
        return self.now

    def __call__(self):
        return self.now


@pytest.fixture
def world(tmp_db, make_session):
    fake_clock = Clock(datetime(2026, 3, 1, 9, 0))
    seed(tmp_db, fake_clock)
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        first = make_session(s, fake_clock, "P-001", "Knee Extension", datetime(2026, 3, 16, 9, 0), REPS)
        second = make_session(s, fake_clock, "P-001", "Squat", datetime(2026, 3, 22, 9, 0), REPS[:2])
        theirs = make_session(s, fake_clock, "P-002", "Squat", datetime(2026, 3, 22, 10, 0), REPS)
    fake_clock.set(datetime(2026, 3, 23, 9, 15))
    return tmp_db, fake_clock, first, second, theirs


def test_activity_by_week_and_period(world):
    db, clock, first, second, theirs = world
    from src.portal import accounts
    with SessionStore(db, clock=clock).open() as s:
        accounts.restrict(s, s.account_by_username("therapist"))
        act = records.activity(s, clock.peek(), 30)
        assert act["sessions"] == 2 and act["reps"] == 5                 # rivera's session is not counted
        assert [w for w, _ in act["form_by_week"]] == ["16 Mar"]           # both sessions fall in the week of 16 Mar
        assert records.activity(s, clock.peek(), 7)["sessions"] == 1
    assert records.period("90") == 90 and records.period("365") == 30 and records.period(None) == 30


GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden" / "rep_csv_from_pandas.csv"


def test_rep_csv_matches_the_old_pandas_export(world):
    """The file was written by the Streamlit page's pandas export (DataFrame(reps).to_csv(index=False)) for this
    session before pandas was removed (019 slice 8); the stdlib export must stay byte for byte the same."""
    db, clock, first, *_ = world
    with SessionStore(db, clock=clock).open() as s:
        reps = records.log_data(s, first)["reps"]
    assert records.rep_csv(reps) == GOLDEN.read_text()


def test_timeline_lines_say_their_units():
    t, label, detail = records.timeline_line({"type": "rep", "timestamp": "2026-03-16T09:00:05", "rep_number": 1,
                                              "exercise": "Squat", "rom": 50.0, "form_score": 80.0,
                                              "duration_seconds": 2.0})
    assert (t, label) == ("09:00:05", "Rep complete") and "50.0°" in detail and "of 100" in detail and "2.0 s" in detail


@pytest.fixture
def signed(world):
    db, clock, *_ = world
    with client(db, clock) as c:
        sign_in(c)
        yield c, world


def test_the_dashboard_is_home_and_shows_today_and_activity(signed):
    c, (db, clock, first, second, theirs) = signed
    page = c.get("/therapist/dashboard").text
    for part in ("Needs you", "Visits today", "Patients to look at", "Activity", "Recent sessions"):
        assert part in page, part
    assert "<b>2 sessions</b> with <b>5 reps</b>" in page
    assert f'href="/therapist/logs/{first}"' in page and f'href="/therapist/logs/{theirs}"' not in page
    assert "<b>1 session</b>" in c.get("/therapist/dashboard?days=7").text
    from tests.test_clinic_static import _checked
    _checked(page, "dashboard")


def test_sessions_list_detail_and_exports(signed):
    c, (db, clock, first, second, theirs) = signed
    page = c.get("/therapist/sessions").text
    assert "2 sessions" in page and f'/therapist/sessions/{theirs}"' not in page
    assert "2 sessions for P-001" in c.get("/therapist/sessions?patient=P-001").text
    detail = c.get(f"/therapist/sessions/{first}").text
    assert "Event log" in detail and "REP 1" in detail
    for fmt in records.EXPORTS:
        r = c.get(f"/therapist/sessions/{first}/export/{fmt}")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"], fmt
    assert c.get(f"/therapist/sessions/{first}/export/nope").status_code == 404
    assert c.get("/therapist/sessions?patient=P-002").status_code == 404


def test_observation_log_charts_table_and_downloads(signed):
    c, (db, clock, first, *_rest) = signed
    page = c.get(f"/therapist/logs/{first}").text
    assert "Form score per rep, 0 to 100" in page and 'class="bar low"' in page    # rep 3 scored 55
    assert "Show as table" in page and "Rep by rep" in page and "Event timeline" in page
    csv = c.get(f"/therapist/logs/{first}/reps.csv")
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("type,timestamp,rep_number")
    assert c.get(f"/therapist/logs/{first}/log.json").json()["summary"]["total_reps"] == 3
    assert "Pick a session" in c.get("/therapist/logs").text
    from tests.test_clinic_static import _checked
    _checked(page, "log")


def test_another_caseloads_sessions_are_not_found(signed):
    c, (db, clock, first, second, theirs) = signed
    for path in (f"/therapist/sessions/{theirs}", f"/therapist/logs/{theirs}", f"/therapist/logs/{theirs}/reps.csv",
                 f"/therapist/sessions/{theirs}/export/csv_report"):
        assert c.get(path).status_code == 404, path
