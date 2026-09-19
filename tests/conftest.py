"""Shared pytest fixtures for the ptlog test suite.

No fixture touches a camera, the network, the model weights, or the project's
data directories (constitution IV).
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Make the repo root importable (analyze.py, src/, interfaces/) regardless of cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeClock:
    """Deterministic clock: fixed at `start` unless `advance()` is called (or `step` > 0)."""

    def __init__(self, start: datetime = datetime(2026, 3, 23, 9, 15, 0), step: float = 0.0):
        self._now = start
        self._step = timedelta(seconds=step)
        self.calls = 0

    def __call__(self) -> datetime:
        current = self._now
        self._now = self._now + self._step
        self.calls += 1
        return current

    def peek(self) -> datetime:
        """Return the timestamp the next call will produce, without advancing."""
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Path to a fresh SQLite database inside the test's temporary directory."""
    return tmp_path / "ptassist.db"


@pytest.fixture
def fake_clock() -> FakeClock:
    """A fixed clock at 2026-03-23T09:15:00; tests move it with advance(seconds)."""
    return FakeClock()


@pytest.fixture
def cli_env(tmp_db: Path) -> dict:
    """Environment for subprocess CLI tests: PTASSIST_DB points at the temp database."""
    env = dict(os.environ)
    env["PTASSIST_DB"] = str(tmp_db)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


# ---------------------------------------------------------------- review-over-time helpers

from datetime import timedelta as _td  # noqa: E402


@pytest.fixture
def fixed_store(tmp_db: Path):
    """(store, clock) with a settable FixedClock, for tests that need explicit start times."""
    from src.ptlog.store import SessionStore
    from tests.fixtures.golden.sequence import FixedClock
    clock = FixedClock(datetime(2026, 3, 23, 9, 15, 0))
    with SessionStore(tmp_db, clock=clock).open() as store:
        yield store, clock


def _set_info(exercise, target_reps: int):
    from src.ptlog.models import ExerciseSetInfo
    from src.ptlog.recorder import derive_exercise_key
    if isinstance(exercise, ExerciseSetInfo):
        return exercise
    lowered = exercise.lower()
    side = "right" if "(right)" in lowered else ("bilateral" if any(w in lowered for w in ("squat", "push", "trunk")) else "left")
    return ExerciseSetInfo(derive_exercise_key(exercise), exercise, side, target_reps, 170.0, 90.0)


@pytest.fixture
def make_session():
    """Factory: a completed (or interrupted) session with reps given as (form, rom, duration) tuples.

    make_session(store, clock, patient_id, exercise, start, reps, partials=0, target_reps=10,
                 safety_stop=None, interrupted=False, extra_sets=(), source="video") -> session_id
    extra_sets: dicts with keys exercise, reps, partials (0), target_reps (10), safety_stop (None).
    """
    from src.ptlog.models import FormEvent, PartialRepEvent, RepEvent

    def _add_set(store, sid, exercise, reps, partials, target_reps, safety_stop, t0):
        set_id = store.open_set(sid, _set_info(exercise, target_reps))
        ts = t0
        for n, (form, rom, dur) in enumerate(reps, 1):
            ts = t0 + _td(seconds=5 * n)
            store.add_rep(set_id, RepEvent(n, 10.0, round(10.0 + rom, 1), float(rom), float(dur), float(form),
                                           ts.isoformat(), 60 * n))
        for _ in range(partials):
            ts = ts + _td(seconds=3)
            store.add_partial_rep(set_id, PartialRepEvent("reversed_early", 95.0, 135.0, 40.0, 1.3, ts.isoformat(), 0))
        if safety_stop:
            ts = ts + _td(seconds=1)
            store.add_form_event(set_id, FormEvent("stop", "stop", safety_stop, ts.isoformat(), 0, body_part="knee"))
        store.close_set(set_id, (ts + _td(seconds=1)).isoformat())
        return ts

    def _make(store, clock, patient_id, exercise, start, reps, partials=0, target_reps=10,
              safety_stop=None, interrupted=False, extra_sets=(), source="video"):
        clock.set(start)
        sid = store.start_session(patient_id, source, "clip.mp4")
        ts = _add_set(store, sid, exercise, reps, partials, target_reps, safety_stop, start)
        for extra in extra_sets:
            t0 = ts + _td(seconds=10)
            clock.set(t0)
            ts = _add_set(store, sid, extra["exercise"], extra["reps"], extra.get("partials", 0),
                          extra.get("target_reps", 10), extra.get("safety_stop"), t0)
        clock.set(ts + _td(seconds=10))
        if interrupted:
            store._interrupt_running("recovered_on_open")
        else:
            store.end_session(sid)
        return sid

    return _make


# ---------------------------------------------------------------- tracker helpers (feature 003)

from datetime import date as _date  # noqa: E402

D0_DATE = _date(2026, 3, 23)


@pytest.fixture
def caseload(make_session):
    """Factory: register patients and record sessions from a compact description.

    caseload(store, clock, {"P-017": [(days_ago, exercise, [(form, rom, dur), ...]), ...], ...})
    Sessions are recorded relative to 2026-03-23 09:15. Returns {patient_id: [session_id, ...]}
    in the order given. Patients that already exist are reused.
    """
    from datetime import datetime, timedelta

    def _build(store, clock, spec):
        base = datetime(2026, 3, 23, 9, 15, 0)
        ids = {}
        for patient_id, sessions in spec.items():
            if store.get_patient(patient_id) is None:
                store.add_patient(patient_id)
            ids[patient_id] = []
            for entry in sessions:
                days_ago, exercise, reps = entry[0], entry[1], entry[2]
                kwargs = entry[3] if len(entry) > 3 else {}
                ids[patient_id].append(make_session(store, clock, patient_id, exercise,
                                                    base - timedelta(days=days_ago), reps, **kwargs))
        return ids

    return _build
