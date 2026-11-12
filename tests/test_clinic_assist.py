"""Feature 019 slice 3b (T019, T020, FR-008): session notes and the AI on a patient's page.

No key, no AI control anywhere; a summary is shown, never saved or sent on its own, and a saved one keeps its
AI-drafted label (and says when it was edited); the coach log is read-only; model text is never markup."""

import pytest

from src.assist import assistant, config
from src.clinic import assist_view
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, client, seed, sign_in


def test_citations_and_states():
    assert assist_view.cited(["S-12", "E-3", "M-4", "T-9", "X-1"]) == \
        "From: Session S-12 · Log E-3 · Message M-4 · Voice note T-9 · Record X-1"
    none = assist_view.summary_json(assistant.SummaryResult("no_records", window={"from": "2026-03-16", "to": "x"}), "P-001")
    assert none["state"] == "no_records" and "since 2026-03-16" in none["text"]
    assert assist_view.summary_json(assistant.SummaryResult("weird"), "P-001")["title"].startswith("The assistant isn't")
    assert assist_view.note_is_edited("a b", "a b ") is False and assist_view.note_is_edited("a c", "a b") is True
    assert assist_view.note_is_edited("a", None) is False


def test_a_summary_as_json():
    result = assistant.SummaryResult(
        "ok", sections=[assistant.Claim("Pain rose to 6/10.", ["E-3"], "Pain")],
        next_steps=[assistant.Claim("Ask about sleep.", ["E-4"])], dropped=1, record_count=9,
        window={"from": "2026-03-16", "to": "2026-03-23"})
    data = assist_view.summary_json(result, "P-001")
    assert data["sections"] == [{"heading": "Pain", "text": "Pain rose to 6/10.", "from": "From: Log E-3"}]
    assert data["next_steps"][0]["text"] == "Ask about sleep." and data["dropped"] == 1
    assert data["note"].startswith("Weekly summary 2026-03-16 to 2026-03-23 (AI-drafted)")


def test_coach_outcome_counts():
    turns = [{"kind": "answer"}, {"kind": "answer"}, {"kind": "emergency"}]
    assert assist_view.coach_outcome(turns) == "2 answered, 1 emergency card shown"


@pytest.fixture
def world(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        yield c, tmp_db, fake_clock


def post(c, path, body=None):
    return c.post("/therapist/api/patients" + path, json=body or {}, headers=H)


def test_no_key_no_ai_control(world):
    c, _, _ = world
    page = c.get("/therapist/patients/P-001").text
    assert "Weekly summary" not in page and "AI settings" not in page
    assert c.get("/therapist/patients/P-001/ai").status_code == 404
    assert post(c, "/P-001/summary").status_code == 404
    assert post(c, "/P-001/ai", {"which": "coach", "on": True}).status_code == 404
    assert "Session notes" in page                                     # notes need no key


def test_with_a_key_the_switches_and_the_summary(world, monkeypatch):
    c, db, clock = world
    monkeypatch.setattr(config, "available", lambda: True)
    page = c.get("/therapist/patients/P-001/ai").text
    assert "Weekly summaries and drafts" in page and "Patient exercise coach" in page
    assert assistant.NOTICE_COACH[:30] in page.replace("&#x27;", "'")
    assert "off for P-001" in c.get("/therapist/patients/P-001").text   # summaries start off
    assert post(c, "/P-001/ai", {"which": "summaries", "on": True}).status_code == 200
    assert post(c, "/P-001/ai", {"which": "everything", "on": True}).status_code == 400
    assert 'data-act="summarise"' in c.get("/therapist/patients/P-001").text
    made = assistant.SummaryResult("ok", sections=[assistant.Claim("<b>Pain</b> rose.", ["E-3"], "Pain")],
                                   record_count=3, window={"from": "2026-03-16", "to": "2026-03-23"})
    monkeypatch.setattr(assistant, "weekly_summary", lambda store, pid, account_id=None: made)
    data = post(c, "/P-001/summary").json()
    assert data["state"] == "ok" and data["sections"][0]["text"] == "<b>Pain</b> rose."   # text; drawn with textContent
    with SessionStore(db, clock=clock).open() as s:
        assert assistant.notes(s, "P-001") == []                       # a summary is never saved on its own
    assert post(c, "/P-001/notes", {"body": data["note"], "ai_drafted": True, "original": data["note"]}).status_code == 200
    assert post(c, "/P-001/notes", {"body": data["note"] + " Checked.", "ai_drafted": True,
                                    "original": data["note"]}).status_code == 200
    notes = c.get("/therapist/patients/P-001/notes").text
    assert notes.count('class="ai-label"') == 2 and "AI-drafted, then edited" in notes
    assert "&lt;b&gt;Pain&lt;/b&gt; rose." in notes and "<b>Pain</b>" not in notes


def test_a_plain_note(world):
    c, db, clock = world
    assert post(c, "/P-001/notes", {"body": "Hip flexion 85 degrees."}).status_code == 200
    assert post(c, "/P-001/notes", {"body": "   "}).status_code == 400
    page = c.get("/therapist/patients/P-001/notes").text
    assert "Hip flexion 85 degrees." in page and "AI-drafted" not in page


def test_the_coach_log_is_read_only_and_escaped(world, monkeypatch):
    from src.assist import coach
    c, _, _ = world
    monkeypatch.setattr(config, "available", lambda: True)
    monkeypatch.setattr(coach, "conversations", lambda store, pid: [{"day": "2026-03-22", "turns": [
        {"kind": "answer", "question": "How long <i>hold</i>?", "answer": "Five <script>x</script> seconds.",
         "asked_at": "2026-03-22T08:05:00", "exercise": "Quad sets"},
        {"kind": "emergency", "question": "Sharp chest pain", "answer": None, "asked_at": "2026-03-22T09:00:00",
         "exercise": None}]}])
    page = c.get("/therapist/patients/P-001/ai").text
    assert "Sun 22 Mar · 2 questions · 1 answered, 1 emergency card shown · emergency card" in page
    assert "How long &lt;i&gt;hold&lt;/i&gt;?" in page and "<script>x" not in page
    assert "Emergency card: call 911" in page
    from tests.test_clinic_static import _checked
    _checked(page, "ai")


def test_another_caseload_is_not_found(world, monkeypatch):
    c, _, _ = world
    monkeypatch.setattr(config, "available", lambda: True)
    c.post("/therapist/api/logout", json={}, headers=H)
    sign_in(c, "rivera")
    for path in ("/therapist/patients/P-001/notes", "/therapist/patients/P-001/ai"):
        assert c.get(path).status_code == 404
    assert post(c, "/P-001/notes", {"body": "x"}).status_code == 404
    assert post(c, "/P-001/summary").status_code == 404
