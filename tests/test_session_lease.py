"""Feature 020 slice F (T032): a running session belongs to whoever holds its lease, not to a process id.

On Vercel each request may land on another instance. Recovery used to ask "is the recording process alive?" with
os.kill(pid, 0), which on another instance either marked a live session interrupted or, if process ids happened
to match, kept a dead one. The recorder now writes its host, its process id and a lease into the session's
extras and renews the lease while frames arrive. Recovery keeps a session that another host still holds a lease
on, and on this host still checks the process, so a crash here is recovered at once."""

import json
import os
from datetime import timedelta

from src.ptlog import store as store_module
from src.ptlog.recorder import LEASE_SECONDS, RENEW_SECONDS, SessionRecorder
from src.ptlog.store import SessionStore
from tests.test_ptlog_recorder import KNEE, FakeTracker

DEAD_PID = 999_999_999          # no such process


def _extras(store, sid):
    return json.loads(store.conn.execute("SELECT source_extras FROM sessions WHERE id = ?", (sid,)).fetchone()[0])


def _status(db, clock, sid):
    with SessionStore(db, clock=clock).open() as s:
        return s.conn.execute("SELECT status FROM sessions WHERE id = ?", (sid,)).fetchone()[0]


def _start(db, clock):
    store = SessionStore(db, clock=clock).open()
    recorder = SessionRecorder(store, clock=clock)
    sid = recorder.start("unassigned", "webcam", "0", KNEE)
    return store, recorder, sid


def test_a_session_records_who_holds_it_and_until_when(tmp_db, fake_clock):
    store, _recorder, sid = _start(tmp_db, fake_clock)
    extras = _extras(store, sid)
    assert extras["pid"] == os.getpid() and extras["host"] == store_module.this_host()
    assert extras["lease_until"] == (fake_clock.peek() + timedelta(seconds=LEASE_SECONDS)).isoformat()


def test_the_lease_is_renewed_while_frames_arrive(tmp_db, fake_clock):
    store, recorder, sid = _start(tmp_db, fake_clock)
    first = _extras(store, sid)["lease_until"]
    tracker = FakeTracker(KNEE)
    fake_clock.advance(RENEW_SECONDS - 1)
    recorder.observe(tracker, {"rep_count": 0}, 120.0, 1, None)
    assert _extras(store, sid)["lease_until"] == first                       # not yet due
    fake_clock.advance(2)
    recorder.observe(tracker, {"rep_count": 0}, 120.0, 2, None)
    assert _extras(store, sid)["lease_until"] > first


def test_another_hosts_session_survives_while_its_lease_runs(tmp_db, fake_clock, monkeypatch):
    store, _recorder, sid = _start(tmp_db, fake_clock)
    monkeypatch.setattr(store_module, "this_host", lambda: "another-instance")
    fake_clock.advance(LEASE_SECONDS - 5)
    assert _status(tmp_db, fake_clock, sid) == "running"                     # opened elsewhere: still live


def test_another_hosts_session_is_recovered_once_its_lease_runs_out(tmp_db, fake_clock, monkeypatch):
    store, _recorder, sid = _start(tmp_db, fake_clock)
    monkeypatch.setattr(store_module, "this_host", lambda: "another-instance")
    fake_clock.advance(LEASE_SECONDS + 1)
    assert _status(tmp_db, fake_clock, sid) == "interrupted"


def test_a_dead_process_on_this_host_is_recovered_at_once(tmp_db, fake_clock):
    store, _recorder, sid = _start(tmp_db, fake_clock)
    extras = _extras(store, sid)
    extras["pid"] = DEAD_PID                                                   # the recorder crashed
    store.conn.execute("UPDATE sessions SET source_extras = ? WHERE id = ?", (json.dumps(extras), sid))
    store.conn.commit()
    assert _status(tmp_db, fake_clock, sid) == "interrupted"                  # the lease alone doesn't save it


def test_an_older_session_without_a_lease_keeps_the_process_rule(tmp_db, fake_clock):
    store = SessionStore(tmp_db, clock=fake_clock).open()
    for pid in ("P-001", "P-002"):                       # two patients: a new session ends the patient's other ones
        store.add_patient(pid)
    alive = store.start_session("P-001", "webcam", "0", {"pid": os.getpid()})
    dead = store.start_session("P-002", "webcam", "1", {"pid": DEAD_PID})
    store.close()
    assert _status(tmp_db, fake_clock, alive) == "running"
    assert _status(tmp_db, fake_clock, dead) == "interrupted"
