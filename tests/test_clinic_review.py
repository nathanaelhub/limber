"""Feature 019 slice 5b (T026): the Review page in the clinic app. Re-expresses what tests/test_app_pages.py pinned
for Streamlit's Review, plus the three fixes (compare from sets, goal 0 removes a target, questionnaire chart with
a missing total) and the ownership checks on every id."""

from datetime import datetime

import pytest

from src.clinic import review
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in
from tests.test_clinic_records import Clock

REPS = [(80, 50, 2.0), (70, 45, 2.5), (60, 40, 3.0)]


@pytest.fixture
def world(tmp_db, make_session):
    clock = Clock(datetime(2026, 3, 1, 9, 0))
    seed(tmp_db, clock)
    with SessionStore(tmp_db, clock=clock).open() as s:
        a = make_session(s, clock, "P-001", "Knee Extension", datetime(2026, 3, 16, 9, 0), REPS)
        b = make_session(s, clock, "P-001", "Knee Extension", datetime(2026, 3, 20, 9, 0), REPS[:2],
                         extra_sets=[{"exercise": "Squat", "reps": REPS}])
        theirs = make_session(s, clock, "P-002", "Squat", datetime(2026, 3, 21, 9, 0), REPS)
        for n, (pain, day) in enumerate([(2, 10), (3, 14), (2, 17), (8, 22)]):
            s.entry_add("P-001", "checkin", {"pain": pain, "note": "Call me on 615 555 0142" if n == 3 else ""},
                        float(pain), f"2026-03-{day}T08:00:00", f"c-{n}", "standalone", None, n == 3, False)
    clock.set(datetime(2026, 3, 23, 9, 15))
    with client(tmp_db, clock) as c:
        sign_in(c)
        yield c, tmp_db, clock, a, b, theirs


def post(c, path, body=None):
    return c.post("/therapist/api/review/P-001" + path, json=body or {}, headers=H)


def test_every_section_renders_and_obeys_the_policy(world):
    c, *_ = world
    from tests.test_clinic_static import _checked
    assert "P-001" in c.get("/therapist/review").text
    for key, label in review.SECTIONS:
        r = c.get(f"/therapist/review/P-001/{key}")
        assert r.status_code == 200, key
        _checked(r.text, key)
    assert c.get("/therapist/review/P-001/nothing").status_code == 404


def test_trends_table_charts_and_first_to_latest(world):
    c, *_ = world
    page = c.get("/therapist/review/P-001/trends?exercise=Knee+Extension").text
    assert "avg ROM (degrees)" in page and "First to latest" in page and 'role="img"' in page


def test_session_review_is_saved_for_this_patients_session_only(world):
    c, db, clock, a, b, theirs = world
    page = c.get(f"/therapist/review/P-001/session?session={a}").text
    assert "REVIEW: pending" in page and "Mark reviewed" in page
    assert post(c, f"/sessions/{a}/review", {"next_step": "progress", "notes": "Good"}).status_code == 200
    assert "next step: progress" in c.get(f"/therapist/review/P-001/session?session={a}").text
    assert post(c, f"/sessions/{a}/review", {"next_step": "sideways"}).status_code == 400
    assert post(c, f"/sessions/{theirs}/review", {"next_step": "hold"}).status_code == 404
    assert c.get(f"/therapist/review/P-001/session?session={theirs}").status_code == 404


def test_flags_and_compare_from_the_sets(world):
    c, db, clock, a, b, theirs = world
    assert "Not evaluated yet" in c.get("/therapist/review/P-001/flags").text or "Nothing needs attention" in \
        c.get("/therapist/review/P-001/flags").text
    with SessionStore(db, clock=clock).open() as s:
        assert review.shared_exercises(s, a, b) == ["Knee Extension"]
    page = c.get(f"/therapist/review/P-001/compare?a={a}&b={b}").text
    assert f"Session {a}" in page and "Better when" in page
    assert c.get(f"/therapist/review/P-001/compare?a={a}&b={theirs}").status_code == 404


def test_thresholds_store_only_what_differs_and_reset(world):
    c, db, clock, *_ = world
    page = c.get("/therapist/review/P-001/goals").text
    assert "Attention thresholds" in page and "Whole patient" in page
    with SessionStore(db, clock=clock).open() as s:
        eff, inh, ovr, keys = review.threshold_context(s, "P-001", None)
        values = {k: eff.value(k) for k in (keys or [r for r in __import__("src.ptlog.thresholds", fromlist=["x"]).THRESHOLDS])}
    key = next(iter(values))
    values[key] = values[key] + 1
    r = post(c, "/thresholds", {"scope": "Whole patient", **values})
    assert r.json()["notice"] == "Thresholds saved."
    with SessionStore(db, clock=clock).open() as s:
        assert s.get_patient_thresholds("P-001") == {key: values[key]}
    assert post(c, "/thresholds", {"scope": "Whole patient", **{key: 10 ** 6}}).status_code == 400
    assert post(c, "/thresholds", {"scope": "Nope", **values}).status_code == 400
    assert post(c, "/thresholds/reset", {"scope": "Whole patient"}).status_code == 200
    with SessionStore(db, clock=clock).open() as s:
        assert s.get_patient_thresholds("P-001") == {}
    assert "Change history" in c.get("/therapist/review/P-001/goals").text


def test_a_goal_target_at_zero_is_removed(world):
    c, db, clock, *_ = world
    assert post(c, "/goals", {"exercise": "Knee Extension", "target_rom": 110, "target_reps": 12}).status_code == 200
    assert post(c, "/goals", {"exercise": "Knee Extension", "target_rom": 0, "target_reps": 12}).status_code == 200
    with SessionStore(db, clock=clock).open() as s:
        g = s.list_goals("P-001")[0]
        assert g.target_rom is None and g.target_reps == 12
    assert post(c, "/goals", {"exercise": "Knee Extension", "target_rom": 0, "target_reps": 0}).status_code == 200
    with SessionStore(db, clock=clock).open() as s:
        assert s.list_goals("P-001") == []
    assert post(c, "/goals", {"exercise": "Never Recorded", "target_rom": 90}).status_code == 400


def test_from_the_patient_pain_flag_and_note_removal(world):
    c, db, clock, *_ = world
    page = c.get("/therapist/review/P-001/from-patient").text
    assert "Pain at check-in, 0 to 10" in page and "sent after a privacy warning" in page
    assert "Pain high" in page or "Pain rising" in page
    with SessionStore(db, clock=clock).open() as s:
        entry = [e for e in s.entries("P-001", "checkin") if e.payload.get("note")][0]
    assert post(c, f"/checkins/{entry.id}/remove-note").status_code == 200
    assert "(note removed)" in c.get("/therapist/review/P-001/from-patient").text
    assert c.post(f"/therapist/api/review/P-002/checkins/{entry.id}/remove-note", json={}, headers=H).status_code == 404


def test_export_downloads(world):
    c, *_ = world
    assert "Review report (text)" in c.get("/therapist/review/P-001/export").text
    for kind in ("report", "csv"):
        r = c.get(f"/therapist/review/P-001/export/{kind}?period=all")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"], kind
    assert c.get("/therapist/review/P-001/export/zip").status_code == 404


def test_questionnaire_chart_keeps_dates_and_totals_paired():
    class E:
        def __init__(self, i, day, total):
            self.id, self.recorded_at, self.time_adjusted = i, f"2026-03-{day}T09:00:00", False
            self.payload = {"instrument": "k", "total": total, "snapshot": {"name": "Knee", "direction": "higher_is_better",
                                                                             "unit": "points"}}
    groups = review.questionnaire_groups([E(3, 20, 29), E(2, 15, None), E(1, 10, 21)], {})
    assert groups[0]["series"] == [("2026-03-10", 21), ("2026-03-20", 29)]
    assert "21 → 29 (+8 points), the direction you want" in groups[0]["change"]


def test_rivera_cannot_review_the_lead_therapists_patient(world):
    c, *_ = world
    c.post("/therapist/api/logout", json={}, headers=H)
    sign_in(c, "rivera")
    assert c.get("/therapist/review/P-001/trends").status_code == 404
    assert post(c, "/goals", {"exercise": "Knee Extension", "target_rom": 90}).status_code == 404
