"""Writing out a voice note on this host (feature 014).

**This is the optional half of the feature.** Recording, sending, playing, reviewing, and deleting a
voice note never come near this module: they work whether or not a speech model is installed. What lives
here is the question "can this installation write out audio at all?", and (in the second slice) the
worker that does it.

Whatever is added here must keep two promises:

1. **Nothing leaves the host.** No third-party service, no browser speech API. The model files are local,
   fetched by a pinned, hash-checked script, and read from disk.
2. **The suite never needs a model.** `available()` answers from the filesystem and an import check, so
   tests can assert the "not available" path without downloading anything, and the transcription tests
   use a fake transcriber rather than real weights.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_DIR_ENV = "LIMBER_SPEECH_MODEL"
DEFAULT_MODEL_DIR = REPO_ROOT / "models" / "speech"
# What a faster-whisper model directory has to contain to be worth trying.
REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json")
NOT_AVAILABLE = ("Writing out voice notes is not set up on this installation. Recordings still arrive "
                 "and play; only the automatic text is missing.")


def model_dir() -> Path:
    """Where the speech model lives: the environment wins, so a host can keep it off the repository disk."""
    set_to = os.environ.get(MODEL_DIR_ENV)
    return Path(set_to) if set_to else DEFAULT_MODEL_DIR


def model_installed(directory: Optional[Path] = None) -> bool:
    """True when a complete-looking model is on disk. It does not open it: that is the worker's job."""
    folder = Path(directory) if directory else model_dir()
    return folder.is_dir() and all((folder / name).is_file() for name in REQUIRED_FILES)


def library_installed() -> bool:
    """True when the speech library is importable, without importing it."""
    from importlib.util import find_spec
    try:
        return find_spec("faster_whisper") is not None
    except (ImportError, ValueError):
        return False


def available(directory: Optional[Path] = None) -> bool:
    """Whether this installation can write out a voice note at all."""
    return library_installed() and model_installed(directory)


def why_not(directory: Optional[Path] = None) -> str:
    """One plain sentence for the therapist's view and the health check."""
    if not library_installed():
        return "the speech library is not installed"
    if not model_installed(directory):
        return f"no speech model was found in {model_dir()}"
    return ""
