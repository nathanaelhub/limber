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
