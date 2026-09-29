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


# ----------------------------------------------------------------------------- doing the work

import json
import subprocess
import sys
import time
from typing import Callable, Dict, Optional as Opt

MAX_ATTEMPTS = 2
TIMEOUT_SECONDS = 600.0          # ten minutes for a three-minute recording, on a small host
MODEL_NAME_ENV = "LIMBER_SPEECH_MODEL_NAME"
DEFAULT_MODEL_NAME = "small"
REASONS = ("timeout", "unreadable", "not_installed", "missing", "error")


class NotInstalled(Exception):
    """No speech library or no model files: writing out is simply not available here."""


class TranscriberTimeout(Exception):
    """The recording took longer than the limit; the audio is untouched."""


class Unreadable(Exception):
    """The worker could not get text out of this file."""


def worker_command() -> list:
    """The command the host runs to write out one recording: this repository's own module, no shell."""
    return [sys.executable, "-m", "src.media.transcribe"]


def model_name() -> str:
    return os.environ.get(MODEL_NAME_ENV) or DEFAULT_MODEL_NAME


def load(directory: Opt[Path] = None):
    """The local model, or NotInstalled. Imported here and nowhere else, so nothing else depends on it."""
    if not library_installed():
        raise NotInstalled("The speech library is not installed, so writing out is not available.")
    if not model_installed(directory):
        raise NotInstalled(f"No speech model was found in {model_dir()}, so writing out is not available.")
    from faster_whisper import WhisperModel          # noqa: PLC0415 — deliberately lazy
    return WhisperModel(str(directory or model_dir()), device="cpu", compute_type="int8")


def transcribe_file(path: Path, directory: Opt[Path] = None) -> str:
    """Write out one file in this process. Only the subprocess worker calls this."""
    model = load(directory)
    segments, _info = model.transcribe(str(path), vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()


def subprocess_transcriber(timeout: float = TIMEOUT_SECONDS, directory: Opt[Path] = None) -> Callable:
    """The real transcriber: a separate process with a time limit, as the media probe does it.

    A model that hangs or dies cannot take the service with it, and the limit is enforceable, which it
    would not be inside a thread."""
    def runner(path: Path) -> str:
        args = worker_command() + [str(path)]
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise TranscriberTimeout(f"longer than {timeout:g} seconds") from None
        if done.returncode != 0:
            raise Unreadable((done.stderr or "").strip()[:200] or "the worker failed")
        try:
            return str(json.loads(done.stdout or "{}").get("text") or "")
        except ValueError:
            raise Unreadable("the worker did not answer with a transcript") from None
    runner.model_name = model_name()
    return runner


def queue_if_available(store, media_id: str, directory: Opt[Path] = None):
    """Queue a recording to be written out, if this installation can do it at all (FR-009, FR-010)."""
    if not available(directory):
        return None
    return store.transcription_queue(media_id)


def retry(store, job_id: int) -> bool:
    """Put a failed job back in the queue, up to MAX_ATTEMPTS in all."""
    job = store.transcription(job_id)
    if job.state != "failed" or job.attempts >= MAX_ATTEMPTS:
        return False
    store.transcription_requeue(job_id)
    return True


def run_one(store, media_dir: Path, transcriber: Opt[Callable] = None,
            directory: Opt[Path] = None) -> Opt[object]:
    """Take the oldest queued recording and write it out. Returns the finished job, or None if the
    queue is empty. Every ending — success, refusal, failure — is written to the record."""
    from src.portal import messages as privacy
    from src.portal import uploads as media_files

    waiting = store.transcriptions_waiting(limit=1)
    if not waiting:
        return None
    job = waiting[0]
    runner = transcriber or subprocess_transcriber(directory=directory)
    name = getattr(runner, "model_name", None) or model_name()
    store.transcription_start(job.id, model=name)

    media = store.media_get(job.media_id)
    if media is None or media.deleted_at is not None:
        return store.transcription_fail(job.id, reason="missing")
    path = media_files.media_path(media_dir, media)
    if not path.is_file():
        return store.transcription_fail(job.id, reason="missing")

    started = time.monotonic()
    try:
        text = (runner(path) or "").strip()
    except TranscriberTimeout:
        return store.transcription_fail(job.id, reason="timeout")
    except Unreadable:
        return store.transcription_fail(job.id, reason="unreadable")
    except NotInstalled:
        return store.transcription_fail(job.id, reason="not_installed")
    except Exception:                      # noqa: BLE001 — a model is third-party code; nothing may escape
        return store.transcription_fail(job.id, reason="error")
    warned = bool(privacy.check_text(text)) if text else False
    return store.transcription_finish(job.id, text=text, warned=warned,
                                      seconds=round(time.monotonic() - started, 2))


def run_queue(store, media_dir: Path, transcriber: Opt[Callable] = None, limit: int = 50,
              directory: Opt[Path] = None) -> Dict[str, int]:
    """Work the queue until it is empty (or `limit` jobs have been done). One at a time, always."""
    counts = {"done": 0, "failed": 0}
    for _ in range(max(0, int(limit))):
        job = run_one(store, media_dir, transcriber=transcriber, directory=directory)
        if job is None:
            break
        counts["done" if job.state == "done" else "failed"] += 1
    return counts


def _main(argv: list) -> int:
    """The subprocess worker: one file in, one JSON transcript out. Nothing else."""
    if len(argv) < 2:
        print(json.dumps({"error": "usage: python -m src.media.transcribe <file>"}), file=sys.stderr)
        return 2
    try:
        print(json.dumps({"text": transcribe_file(Path(argv[1]))}))
    except NotInstalled as missing:
        print(str(missing), file=sys.stderr)
        return 3
    except Exception as err:               # noqa: BLE001
        print(f"{type(err).__name__}: {err}"[:200], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
