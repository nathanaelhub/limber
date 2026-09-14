"""T012 — an interrupted session keeps every committed event and is recoverable (FR-010, FR-011, SC-002)."""

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from src.ptlog.models import ExerciseSetInfo, RepEvent
from src.ptlog.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parent.parent
KNEE = ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0)


def _rep(n, ts):
    return RepEvent(rep_number=n, min_angle=10.0, max_angle=88.0, rom=78.0, duration_seconds=3.0,
                    form_score=90.0 + n, timestamp=ts, frame_num=60 * n)


class TestInProcessRecovery:
    def test_running_session_becomes_interrupted_on_next_open(self, tmp_db, fake_clock):
        store = SessionStore(tmp_db, clock=fake_clock).open()
        sid = store.start_session("unassigned", "webcam", "0")
        set_id = store.open_set(sid, KNEE)
        for n, ts in enumerate(["2026-03-23T09:15:08", "2026-03-23T09:15:15", "2026-03-23T09:15:22"], 1):
            store.add_rep(set_id, _rep(n, ts))
        store.close()  # never called end_session — simulates a crash

        with SessionStore(tmp_db, clock=fake_clock).open() as store2:
            row = store2.conn.execute(
                "SELECT status, end_time, interrupted_reason, total_reps, avg_form_score FROM sessions WHERE id = ?",
                (sid,)).fetchone()
            set_end = store2.conn.execute("SELECT end_time FROM exercise_sets WHERE id = ?", (set_id,)).fetchone()[0]
        assert row["status"] == "interrupted"
        assert row["end_time"] == "2026-03-23T09:15:22"
        assert row["interrupted_reason"] == "recovered_on_open"
        assert row["total_reps"] == 3
        assert row["avg_form_score"] == 92.0
        assert set_end == "2026-03-23T09:15:22"

    def test_running_session_with_no_events_ends_at_start_time(self, tmp_db, fake_clock):
        store = SessionStore(tmp_db, clock=fake_clock).open()
        sid = store.start_session("unassigned", "webcam", "0")
        store.close()
        with SessionStore(tmp_db, clock=fake_clock).open() as store2:
            row = store2.conn.execute("SELECT status, start_time, end_time, total_reps FROM sessions WHERE id = ?", (sid,)).fetchone()
        assert row["status"] == "interrupted"
        assert row["end_time"] == row["start_time"]
        assert row["total_reps"] == 0


WRITER_SCRIPT = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {repo!r})
    from src.ptlog.store import SessionStore
    from src.ptlog.models import ExerciseSetInfo, RepEvent
    store = SessionStore({db!r}).open()
    sid = store.start_session("unassigned", "webcam", "0")
    set_id = store.open_set(sid, ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0))
    print("READY", flush=True)
    n = 0
    while True:
        n += 1
        store.add_rep(set_id, RepEvent(rep_number=n, min_angle=10.0, max_angle=88.0, rom=78.0,
                                       duration_seconds=3.0, form_score=90.0,
                                       timestamp=f"2026-03-23T09:15:{{n:02d}}", frame_num=60 * n))
        time.sleep(0.05)
""")


class TestSigkillRecovery:
    def test_events_committed_before_kill_survive(self, tmp_db):
        script = WRITER_SCRIPT.format(repo=str(REPO_ROOT), db=str(tmp_db))
        proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        assert proc.stdout.readline().strip() == "READY"
        time.sleep(1.0)
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)

        with SessionStore(tmp_db).open() as store:
            reps = store.conn.execute("SELECT COUNT(*) FROM reps").fetchone()[0]
            status = store.conn.execute("SELECT status FROM sessions").fetchone()[0]
        assert reps >= 5, f"only {reps} reps survived the kill"
        assert status == "interrupted"
