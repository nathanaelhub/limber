"""Feature 021 N3: the progress report, a printable page under Review. Every section renders from existing rules, an
empty section says so, patient-written free text never appears, and only the patient's therapist can open it."""

import re
from datetime import datetime

import pytest

from src.clinic import report
from src.portal import accounts
from src.ptlog.store import SessionStore
from tests.clinic_helpers import client, seed, sign_in
from tests.test_clinic_records import Clock

REPS = [(80, 50, 2.0), (70, 45, 2.5), (60, 40, 3.0)]
SECRET = "Call me on 615 555 0142"


@pytest.fixture
def world(tmp_db, make_session):
    clock = Clock(datetime(2026, 3, 1, 9, 0))
    made = seed(tmp_db, clock)
    with SessionStore(tmp_db, clock=clock).open() as s:
        make_session(s, clock, "P-001", "Knee Extension", datetime(2026, 3, 16, 9, 0), REPS)
        make_session(s, clock, "P-001", "Knee Extension", datetime(2026, 3, 20, 9, 0), REPS[:2])
        make_session(s, clock, "P-001", "Knee Extension", datetime(2026, 1, 5, 9, 0), REPS)      # outside 12 weeks
        for n, (pain, day) in enumerate([(2, 10), (3, 14), (8, 22)]):
            s.entry_add("P-001", "checkin", {"pain": pain, "note": SECRET if n == 2 else ""},
                        float(pain), f"2026-03-{day}T08:00:00", f"c-{n}", "standalone", None, n == 2, False)
        s.set_goal("P-001", "Knee Extension", target_rom=90, target_reps=12)
        s.assign_program("P-001", "knee_basic", "Knee basics", ["knee_extension"], 3, start_date="2026-03-02")
        clock.set(datetime(2026, 3, 22, 10, 0))
        s.therapist_note_add("P-001", "Weekly summary: range improving.", True, False, made["therapist"].id)
        s.therapist_note_add("P-001", "Hand-written note.", False, False, made["therapist"].id)
        accounts.add_patient(s, made["therapist"], "P-003")                                       # no data at all
    clock.set(datetime(2026, 3, 23, 9, 15))
    with client(tmp_db, clock) as c:
        sign_in(c)
        yield c, tmp_db, clock


def test_every_section_renders_prints_and_obeys_the_policy(world):
    c, *_ = world
    from tests.test_clinic_static import _checked
    r = c.get("/therapist/review/P-001/report?period=12w")
    assert r.status_code == 200
    page = r.text
    _checked(page, "report")
    for heading in ("Plan of care", "Program", "Trends", "Pain", "Goals", "Adherence", "Questionnaires", "Notes"):
        assert f"<h2>{heading}</h2>" in page, heading
    assert "P-001" in page and "Last 12 weeks" in page and "data-print" in page and "Print or save as PDF" in page
    assert 'class="lb app report-page' in page or "report-page" in page
    charts = page.count('role="img"')
    assert charts >= 2 and page.count("<table") >= charts            # every chart has its table
    assert "avg ROM (degrees)" in page                                # units from METRIC_DEFINITIONS


def test_patient_written_text_never_appears(world):
    c, *_ = world
    page = c.get("/therapist/review/P-001/report?period=all").text
    assert SECRET not in page and "615" not in page
    assert re.search(r">\s*8\s*<", page)                               # the pain score itself is there


def test_saved_notes_show_their_ai_label_and_author(world):
    c, *_ = world
    page = c.get("/therapist/review/P-001/report").text
    assert "Weekly summary: range improving." in page and "AI-drafted" in page
    assert "Hand-written note." in page and "Therapist" in page


def test_the_period_limits_sessions_and_notes(world):
    c, db, clock = world
    four = c.get("/therapist/review/P-001/report?period=4w").text
    everything = c.get("/therapist/review/P-001/report?period=all").text
    assert "5 Jan" not in four and "5 Jan" in everything
    with SessionStore(db, clock=clock).open() as s:
        now = clock()
        assert report.since_for(s, "P-001", "all", now) is None
        assert (now - report.since_for(s, "P-001", "4w", now)).days == 28
        assert (now - report.since_for(s, "P-001", "12w", now)).days == 84
        plan = s.current_plan("P-001")
        assert report.since_for(s, "P-001", "plan", now).date().isoformat() == plan.start_date
    assert report.period_key("nonsense") == "12w" and report.period_key("plan") == "plan"


def test_an_empty_patient_still_prints_with_plain_lines(world):
    c, *_ = world
    page = c.get("/therapist/review/P-003/report").text
    assert "No sessions in this period." in page and "No goals set." in page
    assert "No program assigned." in page and "No questionnaires answered in this period." in page
    assert "No saved notes in this period." in page


def test_review_links_the_report_and_others_cannot_open_it(world):
    c, *_ = world
    assert 'href="/therapist/review/P-001/report"' in c.get("/therapist/review/P-001/trends").text
    assert c.get("/therapist/review/P-002/report").status_code == 404          # rivera's patient


def test_questionnaire_section_shows_scores_and_change_only():
    group = {"name": "Knee score", "unit": "points", "direction": "a higher score is better", "meaning": "Function.",
             "series": [("2026-03-01", 40.0), ("2026-03-20", 55.0)], "change": "First to latest: 40 → 55 (+15 points).",
             "rows": [{"when": "2026-03-20 08:00", "total": 55.0, "missing": 0, "subscales": []},
                      {"when": "2026-03-01 08:00", "total": 40.0, "missing": 0, "subscales": []}],
             "subscale_names": [], "version_note": None, "notice": None, "key": "k", "answers": []}
    from src.clinic import report_view
    html = report_view.questionnaires([group])
    assert "Knee score" in html and "+15 points" in html and 'role="img"' in html and "<table" in html


def test_the_printed_title_carries_no_needs_you_count(world):
    c, *_ = world
    page = c.get("/therapist/review/P-001/report").text
    assert "<title>Limber · Progress report · P-001</title>" in page
