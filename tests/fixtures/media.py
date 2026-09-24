"""Synthetic media files for tests, generated with PyAV at test time. No binary is committed and no
file contains a person."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np


def make_video(path: Path, seconds: float = 2.0, fps: int = 15, size=(64, 64), codec: str = "libx264",
               container: str = None, audio: bool = False) -> Path:
    """A moving-square clip. `container` defaults to the path's suffix."""
    path = Path(path)
    out = av.open(str(path), mode="w", format=container)
    stream = out.add_stream(codec, rate=fps)
    stream.width, stream.height = size
    stream.pix_fmt = "yuv420p"
    astream = out.add_stream("aac", rate=44100) if audio else None
    n = int(seconds * fps)
    for i in range(n):
        frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        x = int((i / max(1, n - 1)) * (size[0] - 16))
        frame[24:40, x:x + 16] = (14, 107, 100)
        for packet in stream.encode(av.VideoFrame.from_ndarray(frame, format="rgb24")):
            out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    if astream is not None:
        aframe = av.AudioFrame.from_ndarray(np.zeros((1, 1024), dtype=np.float32), format="fltp", layout="mono")
        aframe.sample_rate = 44100
        for _ in range(int(seconds * 44100 / 1024)):
            for packet in astream.encode(aframe):
                out.mux(packet)
        for packet in astream.encode():
            out.mux(packet)
    out.close()
    return path


def make_audio(path: Path, seconds: float = 1.0, codec: str = "aac") -> Path:
    path = Path(path)
    out = av.open(str(path), mode="w")
    stream = out.add_stream(codec, rate=44100)
    t = np.arange(1024) / 44100.0
    tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32).reshape(1, -1)
    frame = av.AudioFrame.from_ndarray(tone, format="fltp", layout="mono")
    frame.sample_rate = 44100
    for _ in range(int(seconds * 44100 / 1024)):
        for packet in stream.encode(frame):
            out.mux(packet)
    for packet in stream.encode():
        out.mux(packet)
    out.close()
    return path


def make_png_named_mp4(path: Path) -> Path:
    import cv2
    path = Path(path)
    png = path.with_suffix(".png")
    cv2.imwrite(str(png), np.zeros((16, 16, 3), dtype=np.uint8))
    path.write_bytes(png.read_bytes())
    png.unlink()
    return path


def truncate(path: Path, keep_fraction: float = 0.4) -> Path:
    data = Path(path).read_bytes()
    Path(path).write_bytes(data[: int(len(data) * keep_fraction)])
    return Path(path)
