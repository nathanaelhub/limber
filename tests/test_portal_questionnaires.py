"""Feature 013 T008/T010 — a patient answering an assigned questionnaire from their phone.

The answer set goes through the existing entries route, so the offline queue replays it unchanged.
Everything the page shows comes from the server: the items, their choices, and what is due.
"""

from datetime import date, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from interfaces.patient_portal import create_app
from src.portal import access
from src.ptlog import instruments
from src.ptlog.store import SessionStore

KEY = b"k" * 32
ORIGIN = "http://testserver"
NOW = datetime(2026, 9, 24, 18, 0, 0)
DEMO = "demo_knee_function"
FULL = {"stairs_up": 4, "stairs_down": 3, "rising": 4, "standing": 2, "walking": 3,
        "kneeling": 1, "squatting": 2, "twisting": 3, "pain_moving": 1, "pain_night": 0}
# 4+3+4+2+3+1+2+3 = 22 from the activity items, plus the two reversed pain items (4-1=3, 4-0=4) = 29


@pytest.fixture
def store(tmp_db):
    from tests.conftest import FakeClock
    instruments.forget()
    with SessionStore(tmp_db, clock=FakeClock(NOW)).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-018")
        s.assign_instrument("P-017", DEMO, "fortnightly", NOW.date() - timedelta(days=1))
        yield s


@pytest.fixture
def client(tmp_db, store):
    codes = {pid: access.issue_code(store, KEY, pid)[0] for pid in ("P-017", "P-018")}
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN])
    with TestClient(app, base_url=ORIGIN) as c:
        c.post("/api/login", json={"code": codes["P-017"]}, headers={"Origin": ORIGIN})
        yield c, codes


def post(client, path, body):
    return client.post(path, json=body, headers={"Origin": ORIGIN})


def send(client, answers, client_id="q1", **extra):
    return post(client, "/api/entries", {"kind": "questionnaire", "client_id": client_id,
                                         "data": {"instrument": DEMO, "answers": answers, **extra}})


class TestWhatIsDue:
    def test_the_questionnaire_route_carries_the_items_and_their_choices(self, client):
        body = client[0].get("/api/questionnaires").json()
        assert body["patient_id"] == "P-017" and len(body["due"]) == 1
        due = body["due"][0]
        assert due["instrument"] == DEMO and due["name"] == "Demo Knee Function" and due["due_on"] is not None
        assert due["unit"] == "points (0-40)" and due["direction"] == "higher_is_better"
        assert "not a validated" in due["notice"].lower() and len(due["meaning"]) > 15
        assert [i["key"] for i in due["items"]][:2] == ["stairs_up", "stairs_down"]
        assert due["items"][0]["choices"][0] == {"text": "Not at all", "value": 0}
        assert due["items"][-1]["text"].startswith("How much pain")
        assert due["minimum_answered"] == 8 and due["item_count"] == 10
        assert "reversed" not in str(due["items"][0])                    # the patient is not shown the scoring

    def test_today_offers_what_is_due_and_then_shows_it_done(self, client, store):
        body = client[0].get("/api/today").json()
        assert body["questionnaires"]["due"] == 1 and body["questionnaires"]["next_due_on"] is not None
        assert send(client[0], FULL).status_code == 201
        body = client[0].get("/api/today").json()
        assert body["questionnaires"]["due"] == 0
        assert body["questionnaires"]["next_due_on"] == (NOW.date() + timedelta(days=14)).isoformat()

    def test_a_patient_with_nothing_assigned_sees_nothing_due(self, client, seeded_other=None):
        client[0].post("/api/logout", json={}, headers={"Origin": ORIGIN})
        client[0].post("/api/login", json={"code": client[1]["P-018"]}, headers={"Origin": ORIGIN})
        assert client[0].get("/api/questionnaires").json()["due"] == []
        assert client[0].get("/api/today").json()["questionnaires"]["due"] == 0


class TestAnswering:
    def test_a_finished_questionnaire_is_stored_once_and_scored(self, client, store):
        r = send(client[0], FULL)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["score"] == 29 and body["kind"] == "questionnaire"
        (entry,) = store.entries("P-017", "questionnaire")
        assert entry.score == 29.0
        assert entry.payload["instrument"] == DEMO and entry.payload["version"] == 1
        assert entry.payload["answers"] == FULL
        assert entry.payload["total"] == 29 and entry.payload["missing"] == 0
        assert entry.payload["subscales"] == {"pain": 7, "activity": 22}
        assert [i["key"] for i in entry.payload["snapshot"]["items"]][0] == "stairs_up"
        assert send(client[0], FULL).status_code == 200                  # the same client id sends nothing twice
        assert len(store.entries("P-017", "questionnaire")) == 1

    def test_the_answered_time_may_be_back_dated_like_any_entry(self, client, store):
        when = (NOW - timedelta(days=2)).isoformat()
        assert post(client[0], "/api/entries", {"kind": "questionnaire", "client_id": "q9", "recorded_at": when,
                                               "data": {"instrument": DEMO, "answers": FULL}}).status_code == 201
        assert store.entries("P-017", "questionnaire")[0].recorded_at == when

    def test_missing_items_within_the_rule_are_accepted_and_counted(self, client, store):
        answers = {k: v for k, v in list(FULL.items())[:8]}              # eight of ten, the rule's minimum
        assert send(client[0], answers).status_code == 201
        entry = store.entries("P-017", "questionnaire")[0]
        assert entry.payload["missing"] == 2 and entry.payload["answered"] == 8
        assert entry.payload["subscales"]["pain"] is None                # neither pain item was answered

    @pytest.mark.parametrize("answers, code", [
        ({k: v for k, v in list(FULL.items())[:7]}, 400),                # below the minimum answered
        ({**FULL, "stairs_up": 9}, 400),                                 # not one of the choices
        ({**FULL, "elbow": 1}, 400),                                     # not an item
        ({}, 400),
        ("not a mapping", 400),
    ])
    def test_refusals(self, client, store, answers, code):
        assert send(client[0], answers).status_code == code
        assert store.entries("P-017", "questionnaire") == []

    def test_an_instrument_that_is_not_assigned_is_refused(self, client, store):
        r = post(client[0], "/api/entries", {"kind": "questionnaire", "client_id": "q2",
                                             "data": {"instrument": "something_else", "answers": FULL}})
        assert r.status_code == 400 and "assigned" in r.json()["error"].lower()
        store.end_assignment(store.assignments("P-017")[0].id)
        assert send(client[0], FULL, client_id="q3").status_code == 400
        assert store.entries("P-017", "questionnaire") == []

    def test_a_discharged_patient_cannot_answer(self, client, store):
        store.discharge("P-017", reason="finished")
        assert send(client[0], FULL).status_code == 401

    def test_no_other_patients_questionnaire_on_the_new_routes(self, client, store):
        store.assign_instrument("P-018", DEMO, "weekly", NOW.date())
        store.entry_add("P-018", "questionnaire", {"instrument": DEMO, "answers": FULL, "total": 29,
                                                   "note": "the other patient's answers"}, 29.0,
                        "2026-09-20T09:00:00", "x", "standalone", None, False, False)
        for route in ("/api/questionnaires", "/api/today", "/api/entries", "/questionnaire"):
            text = client[0].get(route).text
            assert "P-018" not in text and "other patient" not in text, route

    def test_the_page_is_served(self, client):
        r = client[0].get("/questionnaire")
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
