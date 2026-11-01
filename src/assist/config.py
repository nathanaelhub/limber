"""
Where the API key comes from (feature 018, FR-002).

Only `LIMBER_ANTHROPIC_API_KEY`, from the environment or the gitignored `.env` at the repository root.
The shell's `ANTHROPIC_API_KEY` is deliberately never read: on a developer's machine it can hold a token
the API rejects, and the assistant must not pick up a key nobody configured for Limber. The key is never
printed, logged, or returned in a status line.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

KEY_ENV = "LIMBER_ANTHROPIC_API_KEY"
ENV_FILE_ENV = "LIMBER_ENV_FILE"            # tests point this away from the real .env
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _from_env_file() -> Optional[str]:
    path = Path(os.environ.get(ENV_FILE_ENV) or DEFAULT_ENV_FILE)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == KEY_ENV:
            return value.strip().strip('"').strip("'") or None
    return None


def api_key() -> Optional[str]:
    return (os.environ.get(KEY_ENV) or "").strip() or _from_env_file()


def available() -> bool:
    """With no key, every AI control is hidden and nothing is ever sent."""
    return api_key() is not None


def status_line() -> str:
    return "AI assistant: on" if available() else "AI assistant: off (no key)"
