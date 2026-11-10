"""
Make the video analysis page's outputs work in a browser (issue #35).

The engine (`analyze.py`) writes its annotated clip with OpenCV's `mp4v` fourcc, which browsers do not play,
and its metrics are numpy numbers, which `json.dumps` refuses. The engine stays as it is; the page passes its
outputs through here.
"""

from __future__ import annotations

import json
from pathlib import Path

ENCODERS = ("libx264", "h264")


def browser_video(path) -> Path:
    """Re-encode a clip as H.264 (yuv420p, moov atom first) next to the original, and return the new path.
    Anything that cannot be read or encoded is returned unchanged, so the page still offers the original."""
    import av

    src = Path(path)
    out = src.with_name(src.stem + ".h264.mp4")
    try:
        with av.open(str(src)) as inp:
            vin = inp.streams.video[0]
            rate = vin.average_rate or 30
            width, height = vin.codec_context.width // 2 * 2, vin.codec_context.height // 2 * 2
            with av.open(str(out), "w", options={"movflags": "faststart"}) as dst:
                vout = None
                for name in ENCODERS:
                    try:
                        vout = dst.add_stream(name, rate=rate)
                        break
                    except Exception:  # noqa: BLE001 — try the next encoder this build has
                        continue
                if vout is None:
                    raise RuntimeError("no H.264 encoder")
                vout.width, vout.height, vout.pix_fmt = width, height, "yuv420p"
                for frame in inp.decode(vin):
                    frame = frame.reformat(width=width, height=height, format="yuv420p")
                    for packet in vout.encode(frame):
                        dst.mux(packet)
                for packet in vout.encode():
                    dst.mux(packet)
    except Exception:  # noqa: BLE001 — keep the original rather than lose the result
        out.unlink(missing_ok=True)
        return src
    return out


def _plain(value):
    """numpy scalars and arrays as plain numbers and lists."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def report_json(report: dict) -> str:
    return json.dumps(report, indent=2, default=_plain)
