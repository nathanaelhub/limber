"""Feature 018 T012: one live call each for a summary and a draft, against a synthetic record.

Skipped unless LIMBER_LIVE_AI=1, so the suite never touches the network by default. It reads the key from the
repository's gitignored .env (or LIMBER_ANTHROPIC_API_KEY) and never prints it.

    LIMBER_LIVE_AI=1 .venv/bin/python -m pytest -q -s tests/test_assist_live.py
"""

import os
import time
from datetime import datetime, timedelta

import pytest

from src.assist import assistant, config, extract
from src.portal import messages
from src.ptlog.store import SessionStore
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.skipif(os.environ.get("LIMBER_LIVE_AI") != "1", reason="live AI test: set LIMBER_LIVE_AI=1")


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv(config.ENV_FILE_ENV, str(REPO_ROOT / ".env"))
    if not config.available():
        pytest.skip("no LIMBER_ANTHROPIC_API_KEY configured")


def _record(db):
    now = datetime.now()
    with SessionStore(db).open() as s:
        s.add_patient("P-021")
        messages.set_enabled(s, "P-021", True)
        assistant.set_switch(s, "P-021", "summaries", True)
        for n, pain in enumerate((3, 3, 4, 6, 6)):
            at = (now - timedelta(days=6 - n)).isoformat(timespec="seconds")
            s.entry_add("P-021", "checkin", {"pain": pain, "note": "stairs harder" if pain == 6 else ""}, pain, at,
                        f"live-{n}", "standalone", None, False, False)
        messages.send(s, "P-021", "therapist", "How did the stairs feel this week?")
        messages.send(s, "P-021", "patient", "Harder on Thursday, knee felt tight. Should I keep doing heel slides?")


def test_live_summary_and_draft(live, tmp_db):
    _record(tmp_db)
    with SessionStore(tmp_db).open() as s:
        ids = extract.build(s, "P-021").ids
        t0 = time.monotonic()
        summary = assistant.weekly_summary(s, "P-021")
        t1 = time.monotonic()
        draft = assistant.draft_reply(s, "P-021")
        t2 = time.monotonic()
        calls = [dict(r) for r in s.conn.execute("SELECT purpose, model, input_tokens, output_tokens, outcome "
                                                  "FROM assist_calls ORDER BY id")]
    print(f"\nsummary {summary.state} in {t1 - t0:.1f}s; draft {draft.state} in {t2 - t1:.1f}s")
    for c in calls:
        print(c)
    print(summary.as_text() if summary.state == "ok" else "")
    print("DRAFT:", draft.text)
    assert summary.state == "ok" and draft.state == "ok"
    assert all(set(c.record_ids) <= ids for c in summary.sections + summary.next_steps)
    assert any("pain" in c.text.lower() for c in summary.sections)
