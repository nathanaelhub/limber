"""
Inspect an uploaded media file (feature 011). The file decides what it is: container and codecs come
from PyAV, never from the name or the browser's declared type. `probe()` does the work; `run_isolated()`
runs it in a subprocess with a timeout so a malformed file that crashes the media library cannot take
the service down. Both raise MediaRejected with a reason word (never a filename) on refusal.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from src.ptlog.models import PortalError

LIMITS = {
    "clip": {"max_seconds": 65.0, "max_bytes": 80 * 1024 * 1024, "max_side": 1920,
             "containers": {"mov,mp4,m4a,3gp,3g2,mj2": None, "matroska,webm": None},
             "video_codecs": {"h264", "hevc", "vp8", "vp9", "av1"}, "needs_video": True},
    # A voice note (feature 014): whatever a phone records, as long as it is audio and only audio.
    "voice": {"max_seconds": 180.0, "max_bytes": 10 * 1024 * 1024, "max_side": 0,
              "containers": {"mov,mp4,m4a,3gp,3g2,mj2": None, "matroska,webm": None, "ogg": None,
                             "mp3": None, "wav": None},
              "video_codecs": set(), "needs_video": False},
}
EXT_BY_CONTAINER = {"mov,mp4,m4a,3gp,3g2,mj2": {"clip": "mp4", "voice": "m4a"}, "matroska,webm": {"clip": "webm", "voice": "webm"},
                    "ogg": {"voice": "ogg"}, "mp3": {"voice": "mp3"}, "wav": {"voice": "wav"}}
DECODE_FRAMES = 30
REASONS = {
    "not_media": "This file is not a video Limber can read.",
    "damaged": "This video is damaged or cut short and cannot be read.",
    "no_video": "This file has no video in it.",
    "unsupported": "This video format is not supported. Record with your phone's camera and try again.",
    "too_long": "This clip is longer than the limit of about a minute.",
    "too_large": "This file is larger than the limit.",
    "timeout": "This file took too long to check and was not accepted.",
    # Voice notes (feature 014)
    "no_audio": "This file has no sound in it, so it cannot be sent as a voice note.",
    "has_video": "This file has a picture in it. Send it as a video instead of a voice note.",
    "too_long_voice": "This voice note is longer than the limit of about three minutes.",
    "unsupported_voice": "Limber cannot read this recording. Record it with the app and try again.",
}


class MediaRejected(PortalError):
    """A refusal carrying a reason word (never a filename), and a sentence for the patient.

    `kind` picks the wording where a clip and a voice note need to be told different things; the reason
    word itself stays the same, because that is what the access history records."""

    def __init__(self, reason: str, kind: str = "clip"):
        wording = REASONS.get(f"{reason}_voice") if kind == "voice" else None
        super().__init__(wording or REASONS.get(reason, "This file was not accepted."))
        self.reason = reason
        self.kind = kind


@dataclass
class MediaInfo:
    ext: str
    container: str
    codec: str
    bytes: int
    duration: float
    width: int
    height: int
    has_video: bool
    has_audio: bool


def probe(path: Path, kind: str = "clip", max_bytes: Optional[int] = None) -> MediaInfo:
    import av

    limits = LIMITS[kind]
    path = Path(path)
    size = path.stat().st_size if path.exists() else 0
    if size == 0:
        raise MediaRejected("not_media")
    if size > (max_bytes or limits["max_bytes"]):
        raise MediaRejected("too_large")
    try:
        container = av.open(str(path), metadata_errors="strict")
    except Exception:  # noqa: BLE001 — anything PyAV cannot open is not media
        raise MediaRejected("not_media") from None
    try:
        fmt = container.format.name
        if "pipe" in fmt or fmt.startswith("image2"):      # a still image, whatever its name says
            raise MediaRejected("not_media")
        if fmt not in limits["containers"]:
            # MOV files sometimes open under a different name; anything else is refused
            raise MediaRejected("unsupported", kind)
        video = [s for s in container.streams if s.type == "video" and s.codec_context.name not in ("mjpeg", "png")]
        audio = [s for s in container.streams if s.type == "audio"]
        if limits["needs_video"] and not video:
            raise MediaRejected("no_video")
        if not limits["needs_video"]:
            if video:
                raise MediaRejected("has_video", kind)      # a picture makes it a clip, not a voice note
            if not audio:
                raise MediaRejected("no_audio", kind)
        duration = float(container.duration or 0) / 1_000_000.0
        stream = video[0] if video else audio[0]
        if stream.duration and stream.time_base:
            duration = max(duration, float(stream.duration * stream.time_base))
        if duration <= 0:
            raise MediaRejected("damaged")
        if duration > limits["max_seconds"]:
            raise MediaRejected("too_long", kind)
        codec = stream.codec_context.name
        if video and codec not in limits["video_codecs"]:
            raise MediaRejected("unsupported")
        width = height = 0
        if video:
            width, height = stream.codec_context.width, stream.codec_context.height
            if not width or not height or max(width, height) > limits["max_side"]:
                raise MediaRejected("unsupported" if width and height else "damaged")
        try:
            decoded = 0
            for frame in container.decode(stream):
                decoded += 1
                if decoded >= DECODE_FRAMES:
                    break
            if decoded == 0:
                raise MediaRejected("damaged")
        except MediaRejected:
            raise
        except Exception:  # noqa: BLE001
            raise MediaRejected("damaged") from None
        return MediaInfo(ext=EXT_BY_CONTAINER[fmt][kind], container=fmt.split(",")[0], codec=codec, bytes=size,
                         duration=round(duration, 2), width=width, height=height,
                         has_video=bool(video), has_audio=bool(audio))
    finally:
        container.close()


_WORKER_ARGS = [sys.executable, "-m", "src.media.probe"]


def run_isolated(path: Path, kind: str = "clip", timeout: float = 30.0) -> MediaInfo:
    """Probe in a subprocess. A hang becomes `timeout`, a crash becomes `damaged`."""
    try:
        done = subprocess.run(_WORKER_ARGS + [str(path), kind], capture_output=True, text=True, timeout=timeout,
                              cwd=str(Path(__file__).resolve().parent.parent.parent))
    except subprocess.TimeoutExpired:
        raise MediaRejected("timeout") from None
    if done.returncode == 3:
        raise MediaRejected(done.stdout.strip() or "not_media")
    if done.returncode != 0:
        raise MediaRejected("damaged")
    try:
        return MediaInfo(**json.loads(done.stdout))
    except (ValueError, TypeError):
        raise MediaRejected("damaged") from None


def main(argv) -> int:
    path, kind = argv[1], argv[2] if len(argv) > 2 else "clip"
    try:
        print(json.dumps(asdict(probe(Path(path), kind))))
        return 0
    except MediaRejected as err:
        print(err.reason)
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
