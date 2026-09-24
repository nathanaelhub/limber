"""Feature 012 T006 — logging exercise done without the camera, and the medication and sleep logs.

The rules live in src/portal/diary.py and src/ptlog/entries.py; this file holds them to the spec
before either exists, then to the HTTP routes the phone uses.
"""

from datetime import date, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.portal import access
from src.ptlog.models import EntryValidationError, PortalError
from src.ptlog.origin import DIARY
from src.ptlog.store import SessionStore

KEY = b"k" * 32
ORIGIN = "http://testserver"
NOW = datetime(2026, 9, 24, 18, 0, 0)
GOOD = {"exercise": "squat", "reps": 12, "sets": 2, "effort": 3}


@pytest.fixture
def store(tmp_db):
    from tests.conftest import FakeClock
    with SessionStore(tmp_db, clock=FakeClock(NOW)).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-018")
        s.assign_program("P-017", "custom", "Knee Home Program", ["knee_extension", "squat"], 3,
                         NOW.date() - timedelta(days=10))
        yield s


class TestOptions:
    def test_what_the_patient_may_log(self, store):
        from src.portal import diary
        opts = diary.options(store, "P-017", now=NOW)
        assert opts["enabled"] is True and "self-reported" in opts["notice"]
        keys = [e["key"] for e in opts["exercises"]]
        assert keys[:2] == ["knee_extension", "squat"]                      # the program first, in order
        assert opts["exercises"][0]["in_program"] is True
        assert len(keys) > 2 and len(set(keys)) == len(keys)                # then the rest of the configuration
        assert all(e["in_program"] is False for e in opts["exercises"][2:])
        assert opts["reps"] == {"minimum": 1, "maximum": 200} and opts["sets"] == {"minimum": 1, "maximum": 20}
        assert [w for _, w in opts["effort"]] == ["very easy", "easy", "moderate", "hard", "very hard"]
        assert opts["days_back"] == 7 and opts["note_max"] == 200

    def test_a_patient_with_no_program_may_still_log(self, store):
        from src.portal import diary
        opts = diary.options(store, "P-018", now=NOW)
        assert opts["enabled"] is True and opts["exercises"] and all(e["in_program"] is False for e in opts["exercises"])

    def test_off_when_the_therapist_turns_it_off(self, store):
        from src.portal import diary
        store.set_diary_enabled("P-017", False)
        assert diary.options(store, "P-017", now=NOW)["enabled"] is False


class TestLog:
    def test_a_logged_session_is_self_reported_and_counts(self, store):
        from src.portal import diary
        from src.ptlog import adherence, origin
        from src.portal import viewmodels as vm
        session = diary.log(store, "P-017", GOOD, now=NOW)
        assert session.source == "diary" and origin.capture_origin(session) == DIARY
        assert session.status == "completed" and session.total_reps == 24
        assert session.avg_rom is None and session.avg_form_score is None and session.duration_seconds is None
        stored = store.load_session(session.id).sets[0]
        assert (stored.exercise_key, stored.reported_reps, stored.reported_sets, stored.effort) == ("squat", 12, 2, 3)
        assert stored.reps == [] and stored.partial_reps == []
        today = vm.today_view(store, "P-017", now=NOW)
        assert [e["done_today"] for e in today["exercises"]] == [False, True] and today["week"]["done"] == 1

    def test_the_time_it_was_done_may_be_back_dated_seven_days(self, store):
        from src.portal import diary
        done = (NOW - timedelta(days=3)).isoformat()
        session = diary.log(store, "P-017", {**GOOD, "done_at": done}, now=NOW)
        assert session.start_time == done and session.end_time == done
        with pytest.raises(EntryValidationError):
            diary.log(store, "P-017", {**GOOD, "done_at": (NOW - timedelta(days=8)).isoformat()}, now=NOW)
        with pytest.raises(EntryValidationError):
            diary.log(store, "P-017", {**GOOD, "done_at": (NOW + timedelta(hours=2)).isoformat()}, now=NOW)
        with pytest.raises(EntryValidationError):
            diary.log(store, "P-017", {**GOOD, "done_at": "tuesday"}, now=NOW)

    def test_the_same_exercise_twice_in_a_day_is_kept_twice(self, store):
        from src.portal import diary
        from src.portal import viewmodels as vm
        first = diary.log(store, "P-017", GOOD, now=NOW)
        second = diary.log(store, "P-017", {**GOOD, "reps": 8, "sets": 1}, now=NOW)
        assert first.id != second.id and first.status == "completed"        # the second must not interrupt the first
        today = vm.today_view(store, "P-017", now=NOW)
        assert sum(1 for e in today["exercises"] if e["done_today"]) == 1 and today["week"]["done"] == 2

    @pytest.mark.parametrize("bad", [
        {**GOOD, "exercise": "moon_walk"}, {**GOOD, "exercise": ""}, {**GOOD, "exercise": None},
        {**GOOD, "reps": 0}, {**GOOD, "reps": 201}, {**GOOD, "reps": 1.5}, {**GOOD, "reps": "lots"}, {**GOOD, "reps": True},
        {**GOOD, "sets": 0}, {**GOOD, "sets": 21}, {**GOOD, "effort": 0}, {**GOOD, "effort": 6}, {**GOOD, "effort": None},
        {**GOOD, "note": "x" * 201}, {**GOOD, "extra": 1}, {"reps": 10}, "not a dict", None,
    ])
    def test_refusals(self, store, bad):
        from src.portal import diary
        with pytest.raises(EntryValidationError):
            diary.log(store, "P-017", bad, now=NOW)
        assert store.sessions_in_period("P-017", None) == []

    def test_a_note_goes_through_the_privacy_check(self, store):
        from src.portal import diary
        from src.portal.messages import NeedsConfirmation
        with pytest.raises(NeedsConfirmation):
            diary.log(store, "P-017", {**GOOD, "note": "Did these with Jane Smith"}, now=NOW)
        assert store.sessions_in_period("P-017", None) == []
        session = diary.log(store, "P-017", {**GOOD, "note": "Did these with Jane Smith"}, now=NOW, confirm=True)
        stored = store.load_session(session.id)                            # the note belongs to the session
        assert stored.source_extras["note"] == "Did these with Jane Smith" and stored.source_extras["note_warned"] is True

    def test_refused_when_off_or_discharged(self, store):
        from src.portal import diary
        store.set_diary_enabled("P-017", False)
        with pytest.raises(PortalError) as err:
            diary.log(store, "P-017", GOOD, now=NOW)
        assert "therapist" in str(err.value).lower()
        store.set_diary_enabled("P-017", True)
        store.discharge("P-018", reason="finished")
        with pytest.raises(PortalError):
            diary.log(store, "P-018", GOOD, now=NOW)

    def test_entries_already_made_stay_when_it_is_turned_off(self, store):
        from src.portal import diary
        session = diary.log(store, "P-017", GOOD, now=NOW)
        store.set_diary_enabled("P-017", False)
        assert store.load_session(session.id).total_reps == 24


class TestMedicationAndSleepKinds:
    def test_the_kinds_carry_units_and_meanings(self):
        from src.ptlog import entries
        for kind in ("medication", "sleep"):
            k = entries.ENTRY_KINDS[kind]
            for f in k.fields:
                assert f.label and f.unit and len(f.meaning) > 15, (kind, f.key)
        assert [f.key for f in entries.ENTRY_KINDS["medication"].fields] == ["item", "note"]
        assert [f.key for f in entries.ENTRY_KINDS["sleep"].fields] == ["hours", "quality", "note"]
        assert entries.definitions("sleep")["hours"]["unit"] == "hours"
        assert entries.definitions("sleep")["quality"]["unit"] == "1-5"

    def test_medication_is_chosen_from_the_therapists_list(self):
        from src.ptlog import entries
        allowed = {"item": ["ibuprofen 400 mg", "paracetamol"]}
        payload, score = entries.validate("medication", {"item": "paracetamol", "note": ""}, choices=allowed)
        assert payload == {"item": "paracetamol", "note": ""} and score is None
        for bad in ({"item": "whisky"}, {"item": ""}, {"item": "paracetamol", "note": "x" * 501}):
            with pytest.raises(EntryValidationError):
                entries.validate("medication", bad, choices=allowed)
        with pytest.raises(EntryValidationError):
            entries.validate("medication", {"item": "paracetamol"}, choices={"item": []})

    def test_sleep_hours_come_in_halves(self):
        from src.ptlog import entries
        payload, score = entries.validate("sleep", {"hours": "7.5", "quality": 4, "note": ""})
        assert payload == {"hours": 7.5, "quality": 4, "note": ""} and score == 4.0
        assert entries.validate("sleep", {"hours": 0, "quality": 1})[0]["hours"] == 0.0
        for bad in ({"hours": 7.2, "quality": 4}, {"hours": 14.5, "quality": 4}, {"hours": -1, "quality": 4},
                    {"hours": 7, "quality": 0}, {"hours": 7, "quality": 6}, {"hours": "seven", "quality": 4},
                    {"quality": 4}, {"hours": 7}):
            with pytest.raises(EntryValidationError):
                entries.validate("sleep", bad)

    def test_the_latest_entry_for_a_night_wins(self, store):
        from src.ptlog import entries
        for hours, quality, at in ((6.0, 2, "2026-09-23T07:00:00"), (7.5, 4, "2026-09-23T09:30:00"),
                                   (5.0, 3, "2026-09-22T07:00:00")):
            store.entry_add("P-017", "sleep", {"hours": hours, "quality": quality, "note": ""}, float(quality),
                            at, f"c{at}{hours}", "standalone", None, False, False)
        nights = entries.nightly(store.entries("P-017", "sleep", newest_first=True, limit=50))
        assert [(n["night"], n["hours"], n["quality"]) for n in nights] == [("2026-09-23", 7.5, 4), ("2026-09-22", 5.0, 3)]


# ----------------------------------------------------------------------------- over HTTP


@pytest.fixture
def client(tmp_db, store):
    store.set_medication_list("P-017", ["ibuprofen 400 mg", "paracetamol"])
    codes = {pid: access.issue_code(store, KEY, pid)[0] for pid in ("P-017", "P-018")}
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN])
    with TestClient(app, base_url=ORIGIN) as c:
        c.post("/api/login", json={"code": codes["P-017"]}, headers={"Origin": ORIGIN})
        yield c, codes


def post(client, path, body):
    return client.post(path, json=body, headers={"Origin": ORIGIN})


class TestRoutes:
    def test_today_carries_the_diary_and_the_logs(self, client, store):
        body = client[0].get("/api/today").json()
        assert body["diary"]["enabled"] is True and body["diary"]["exercises"][0]["key"] == "knee_extension"
        assert body["logs"]["medications"] == ["ibuprofen 400 mg", "paracetamol"] and body["logs"]["sleep"] is True
        store.set_diary_enabled("P-017", False)
        store.set_medication_list("P-017", [])
        body = client[0].get("/api/today").json()
        assert body["diary"]["enabled"] is False and body["logs"]["medications"] == []

    def test_logging_a_session_over_http(self, client, store):
        r = post(client[0], "/api/diary", GOOD)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["origin"] == DIARY and body["total_reps"] == 24 and body["week"]["done"] == 1
        assert store.load_session(body["session_id"]).source == "diary"

    def test_http_refusals(self, client, store):
        assert post(client[0], "/api/diary", {**GOOD, "reps": 500}).status_code == 400
        assert post(client[0], "/api/diary", {**GOOD, "note": "call me on 555 010 0123"}).status_code == 409
        store.set_diary_enabled("P-017", False)
        assert post(client[0], "/api/diary", GOOD).status_code == 403
        assert client[0].post("/api/diary", json=GOOD, headers={"Origin": "http://evil.test"}).status_code == 403

    def test_medication_and_sleep_over_http(self, client, store):
        ok = post(client[0], "/api/entries", {"kind": "medication", "client_id": "m1",
                                             "data": {"item": "paracetamol", "note": ""}})
        assert ok.status_code == 201 and ok.json()["payload"]["item"] == "paracetamol"
        refused = post(client[0], "/api/entries", {"kind": "medication", "client_id": "m2",
                                                   "data": {"item": "whisky", "note": ""}})
        assert refused.status_code == 400 and "ibuprofen 400 mg" in refused.json()["error"]
        sleep = post(client[0], "/api/entries", {"kind": "sleep", "client_id": "s1",
                                                 "data": {"hours": 7.5, "quality": 4, "note": ""}})
        assert sleep.status_code == 201 and sleep.json()["score"] == 4.0
        assert {e.kind for e in store.entries("P-017")} == {"medication", "sleep"}

    def test_the_pages_are_served(self, client):
        for path in ("/diary", "/log"):
            r = client[0].get(path)
            assert r.status_code == 200 and "text/html" in r.headers["content-type"]
            assert "self-reported" in r.text.lower()

    def test_no_other_patients_data_on_the_new_routes(self, client, store):
        store.set_medication_list("P-018", ["something of the other patient"])
        store.entry_add("P-018", "sleep", {"hours": 3.0, "quality": 1, "note": "other patient's night"}, 1.0,
                        "2026-09-23T07:00:00", "x", "standalone", None, False, False)
        for route in ("/api/today", "/api/entries", "/diary", "/log"):
            text = client[0].get(route).text
            assert "P-018" not in text and "other patient" not in text and "something of" not in text, route
