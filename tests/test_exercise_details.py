"""Feature 021 N1: per-exercise details. The therapist sets sets, reps, hold, how often and a note for each exercise;
a change edits the program in place, adding or removing an exercise starts a new one today (D2), the patient reads
the details on Today and in the live session, the target is the prescription first (D1), and the AI extracts carry it.
Spec 021 User Story 1, scenarios 1 to 7, and FR-001 to FR-005, FR-015."""

from datetime import date, datetime

import pytest

from src.assist import coach, extract
from src.portal import viewmodels
from src.ptlog import prescription
from src.ptlog.models import AssignmentValidationError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore
from tests.clinic_helpers import H, client, seed, sign_in
from tests.test_clinic_records import Clock

KNEE = {"sets": 3, "reps": 10, "frequency": "daily", "note": "Keep your knee soft at the top."}


# ---- the rules -------------------------------------------------------------------------------------------------

def test_the_sentence_reads_plainly():
    assert prescription.dose({"sets": 3, "reps": 10, "frequency": "daily"}) == "3 sets of 10 · Every day"
    assert prescription.dose({"sets": 3, "reps": 10, "hold_seconds": 5, "frequency": "daily"}) == \
        "3 sets of 10 · 5-second hold · Every day"
    assert prescription.dose({"reps": 12, "frequency": "per_week", "days": 3}) == "12 reps · 3 days a week"
    assert prescription.dose({"sets": 1, "reps": 1}) == "1 set of 1"
    assert prescription.dose({}) == "" and prescription.dose(None) == ""


@pytest.mark.parametrize("bad", [{"reps": 0}, {"reps": 101}, {"sets": 11}, {"sets": 0}, {"hold_seconds": 121},
                                 {"hold_seconds": -1}, {"reps": 2.5}, {"reps": "ten"}, {"frequency": "hourly"},
                                 {"frequency": "per_week"}, {"frequency": "per_week", "days": 8},
                                 {"note": "x" * 201}, {"reps": True}])
def test_out_of_range_values_are_refused_plainly(bad):
    with pytest.raises(AssignmentValidationError) as err:
        prescription.clean(bad)
    assert str(err.value).endswith(".") and "Traceback" not in str(err.value)


def test_cleaning_keeps_only_what_is_set():
    assert prescription.clean({"sets": None, "reps": "10", "hold_seconds": 0, "frequency": "", "days": 4,
                               "note": "  Slow   down  "}) == {"reps": 10, "hold_seconds": 0, "note": "Slow down"}
    assert prescription.clean({"frequency": "per_week", "days": 3}) == {"frequency": "per_week", "days": 3}


def test_the_target_is_the_prescription_then_the_goal_then_the_default():
    assert prescription.target({"reps": 12}, 8, 10) == 12
    assert prescription.target({"sets": 3}, 8, 10) == 8
    assert prescription.target({}, None, 10) == 10


# ---- the store --------------------------------------------------------------------------------------------------

@pytest.fixture
def store(tmp_db):
    clock = Clock(datetime(2026, 3, 2, 9, 0))
    with SessionStore(tmp_db, clock=clock).open() as s:
        s.add_patient("P-001")
        s.assign_program("P-001", "knee_rehab", "Knee Rehabilitation", ["squat", "knee_extension"], 3,
                         start_date="2026-02-02")
        yield s, clock


def test_v19_adds_the_three_columns(store):
    s, _ = store
    assert SCHEMA_VERSION == 19 and [v for v, _ in MIGRATIONS][-1] == 19
    cols = lambda t: {r[1] for r in s.conn.execute(f"PRAGMA table_info({t})")}
    assert "exercise_details" in cols("assignments")
    assert "requested_starts_at" in cols("appointments")
    assert "account_id" in cols("admin_audit")


def test_the_v19_upgrade_keeps_every_assignment(tmp_db):
    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, sql in MIGRATIONS[:18]:
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version VALUES (?, '2026-03-01T00:00:00')", (version,))
    conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES ('P-001', NULL, NULL, "
                 "'2026-03-01', 0)")
    conn.execute("INSERT INTO assignments (patient_id, program_id, program_name, exercise_keys, sessions_per_week, "
                 "start_date, created_at) VALUES ('P-001', 'knee_rehab', 'Knee', '[\"squat\"]', 3, '2026-02-02', "
                 "'2026-02-02')")
    conn.commit()
    conn.close()
    with SessionStore(tmp_db, clock=Clock(datetime(2026, 3, 2, 9, 0))).open() as s:
        a = s.active_assignment("P-001")
        assert a.exercise_keys == ["squat"] and a.exercise_details == {}


def test_a_detail_change_edits_the_program_in_place(store):
    s, _ = store
    before = s.active_assignment("P-001")
    s.set_exercise_detail("P-001", "squat", KNEE)
    s.set_exercise_detail("P-001", "squat", {**KNEE, "reps": 12})
    after = s.active_assignment("P-001")
    assert after.id == before.id and after.start_date == "2026-02-02"
    assert after.exercise_details == {"squat": {**KNEE, "reps": 12}}
    assert len(s.assignment_history("P-001")) == 1
    s.set_exercise_detail("P-001", "squat", {})                         # empty clears
    assert s.active_assignment("P-001").exercise_details == {}


def test_a_detail_for_an_exercise_outside_the_program_is_refused(store):
    s, _ = store
    with pytest.raises(AssignmentValidationError):
        s.set_exercise_detail("P-001", "pushup", KNEE)


def test_adding_or_removing_starts_a_new_program_today_and_carries_details(store):
    s, _ = store
    s.set_exercise_detail("P-001", "squat", KNEE)
    s.set_exercise_detail("P-001", "knee_extension", {"reps": 8})
    old = s.active_assignment("P-001")
    new = s.change_program_exercises("P-001", ["squat", "hip_abduction"])
    assert new.id != old.id and new.start_date == "2026-03-02"
    assert new.exercise_keys == ["squat", "hip_abduction"] and new.program_name == "Knee Rehabilitation"
    assert new.exercise_details == {"squat": KNEE}
    history = s.assignment_history("P-001")
    assert [h.end_date for h in history] == [None, "2026-03-01"]
    assert history[1].exercise_keys == ["squat", "knee_extension"]       # past weeks keep their list
    again = s.change_program_exercises("P-001", ["squat"])             # same day: changed in place
    assert again.id == new.id and len(s.assignment_history("P-001")) == 2


# ---- the patient side and the extracts -----------------------------------------------------------------------

def test_today_shows_the_details_and_the_target_follows_d1(store):
    s, clock = store
    s.set_goal("P-001", "Knee Extension", target_reps=7)
    s.set_exercise_detail("P-001", "squat", KNEE)
    shown = {e["key"]: e for e in viewmodels.today_view(s, "P-001", clock())["exercises"]}
    assert shown["squat"]["dose"] == "3 sets of 10 · Every day" and shown["squat"]["note"] == KNEE["note"]
    assert shown["squat"]["target_reps"] == 10
    assert shown["knee_extension"]["dose"] == "" and shown["knee_extension"]["target_reps"] == 7   # the goal
    s.set_exercise_detail("P-001", "squat", {**KNEE, "reps": 12})
    assert viewmodels.program_exercises(s, "P-001", date(2026, 3, 2))[0]["target_reps"] == 12


def test_the_extracts_carry_the_prescription(store):
    s, _ = store
    s.set_exercise_detail("P-001", "squat", KNEE)
    program = extract.build(s, "P-001").data["program"]
    assert program["prescription"] == [{"exercise": "Squat", "dose": "3 sets of 10 · Every day", "note": KNEE["note"]}]
    coached = coach.program_extract(s, "P-001")
    squat = next(e for e in coached["exercises"] if e["name"] == "Squat")
    assert squat["prescription"] == "3 sets of 10 · Every day" and squat["therapist_note"] == KNEE["note"]
    from src.assist import assistant
    assert "prescription" in assistant.DRAFT_SYSTEM and "Never contradict it" in assistant.DRAFT_SYSTEM


# ---- the clinic Exercises tab ------------------------------------------------------------------------------------

@pytest.fixture
def clinic(tmp_db):
    clock = Clock(datetime(2026, 3, 2, 9, 0))
    seed(tmp_db, clock)
    with SessionStore(tmp_db, clock=clock).open() as s:
        s.assign_program("P-001", "knee_rehab", "Knee Rehabilitation", ["squat", "knee_extension"], 3,
                         start_date="2026-02-02")
        s.assign_program("P-002", "knee_rehab", "Knee Rehabilitation", ["squat"], 3, start_date="2026-02-02")
    with client(tmp_db, clock) as c:
        sign_in(c)
        yield c, tmp_db, clock


def _post(c, path, body):
    return c.post(f"/therapist/api/patients/{path}", json=body, headers=H)


def test_the_exercises_tab_shows_and_saves_details(clinic):
    c, db, clock = clinic
    from tests.test_clinic_static import _checked
    page = c.get("/therapist/patients/P-001/exercises").text
    _checked(page, "exercises")
    assert "Current program" in page and "Change details" in page and "Add an exercise" in page
    assert 'data-api="/api/patients/P-001/program/exercise"' in page
    r = _post(c, "P-001/program/exercise", {"key": "squat", "sets": 3, "reps": 10, "hold_seconds": None,
                                            "frequency": "daily", "days": None, "note": "Slow on the way down",
                                            "confirm": ""})
    assert r.status_code == 200, r.text
    assert "3 sets of 10 · Every day" in c.get("/therapist/patients/P-001/exercises").text


def test_bad_values_are_refused_with_a_plain_message(clinic):
    c, *_ = clinic
    r = _post(c, "P-001/program/exercise", {"key": "squat", "reps": 101})
    assert r.status_code == 400 and "Reps must be a whole number from 1 to 100." in r.json()["error"]


def test_a_note_that_looks_identifying_asks_first(clinic):
    c, db, clock = clinic
    body = {"key": "squat", "reps": 10, "note": "Call me on 615 555 0142", "confirm": ""}
    r = _post(c, "P-001/program/exercise", body)
    assert r.status_code == 409 and r.json()["needs_confirm"] is True and "phone number" in r.json()["reasons"]
    with SessionStore(db, clock=clock).open() as s:
        assert s.active_assignment("P-001").exercise_details == {}
    assert _post(c, "P-001/program/exercise", {**body, "confirm": "yes"}).status_code == 200


def test_add_and_remove_through_the_tab(clinic):
    c, db, clock = clinic
    assert _post(c, "P-001/program/add", {"key": "hip_abduction"}).status_code == 200
    assert _post(c, "P-001/program/remove", {"key": "knee_extension"}).status_code == 200
    with SessionStore(db, clock=clock).open() as s:
        assert s.active_assignment("P-001").exercise_keys == ["squat", "hip_abduction"]
        assert len(s.assignment_history("P-001")) == 2
    assert _post(c, "P-001/program/remove", {"key": "squat"}).status_code == 200
    r = _post(c, "P-001/program/remove", {"key": "hip_abduction"})
    assert r.status_code == 400 and "at least one exercise" in r.json()["error"]
    assert _post(c, "P-001/program/add", {"key": "not_an_exercise"}).status_code == 400


def test_another_caseload_is_not_found(clinic):
    c, *_ = clinic
    for path in ("program/exercise", "program/add", "program/remove"):
        assert _post(c, f"P-002/{path}", {"key": "squat", "reps": 5}).status_code == 404, path
