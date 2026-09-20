"""Feature 004 US3 — interruptions and one running session."""

import os
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from src.live_session import LiveSession
from src.ptlog.store import SessionStore
from tests.fixtures.poses import FakeInfer, rep_cycle

REPO_ROOT = Path(__file__).resolve().parent.parent
FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def _live(store, angles=(), clock=datetime.now):
    return LiveSession(store, None, "knee_extension", 10, "Default", FakeInfer(angles), draw=False, clock=clock)


def test_killed_process_leaves_an_interrupted_session_with_its_reps(tmp_db):
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(REPO_ROOT)!r})
        import numpy as np
        from src.live_session import LiveSession
        from src.ptlog.store import SessionStore
        from tests.fixtures.poses import FakeInfer, rep_cycle
        angles = rep_cycle() * 4
        store = SessionStore({str(tmp_db)!r}, check_same_thread=False).open()
        live = LiveSession(store, None, "knee_extension", 10, "Default", FakeInfer(angles), draw=False)
        live.start()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        for _ in angles:
            live.process(frame)
        print("READY", live.session_id, flush=True)
        time.sleep(60)
    """)
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True, cwd=str(REPO_ROOT))
    try:
        line = proc.stdout.readline().split()
        assert line and line[0] == "READY", line
        sid = int(line[1])
    finally:
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()
    with SessionStore(tmp_db).open() as store:
        s = store.load_session(sid)
    assert (s.status, s.interrupted_reason, s.total_reps) == ("interrupted", "recovered_on_open", 4)
    assert len(s.sets[0].reps) == 4


def test_second_stream_supersedes_the_first(tmp_db):
    store_a = SessionStore(tmp_db, check_same_thread=False).open()
    store_b = SessionStore(tmp_db, check_same_thread=False).open()
    first, second = _live(store_a), _live(store_b)
    a = first.start()
    b = second.start()
    s = store_b.load_session(a)
    assert (s.status, s.interrupted_reason) == ("interrupted", "superseded_by_new_session")
    first.end()                                                   # the old stream stopping later changes nothing
    assert store_b.load_session(a).status == "interrupted"
    running = store_b.conn.execute("SELECT id FROM sessions WHERE status = 'running'").fetchall()
    assert [r[0] for r in running] == [b]
    second.end()
    store_a.close()
    store_b.close()


def test_camera_silence_then_stop_ends_normally(tmp_db):
    now = [datetime(2026, 3, 23, 9, 0, 0)]
    store = SessionStore(tmp_db, clock=lambda: now[0], check_same_thread=False).open()
    angles = rep_cycle()
    live = _live(store, angles, clock=lambda: now[0])
    live.start()
    for _ in angles:
        now[0] += timedelta(seconds=1 / 30)
        live.process(FRAME)
    now[0] += timedelta(seconds=30)                                # no frames arrive for 30 s
    done = live.end()
    assert done.status == "completed" and done.total_reps == 1 and done.duration_seconds >= 30
    store.close()
