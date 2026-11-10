"""Issue #35: the video analysis page's annotated clip and report work in a browser."""

import json

import av
import cv2
import numpy as np

from src.media import playable


def _mp4v_clip(path, frames=12, size=(160, 120)):
    """What analyze.py writes: OpenCV's mp4v, which browsers do not play."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12, size)
    for i in range(frames):
        frame = np.full((size[1], size[0], 3), (i * 20) % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


def _codec(path):
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        return s.codec_context.name, s.codec_context.pix_fmt, s.frames or sum(1 for _ in c.decode(s))


def test_mp4v_becomes_h264_a_browser_plays(tmp_path):
    src = _mp4v_clip(tmp_path / "annotated.mp4")
    assert _codec(src)[0] == "mpeg4"
    out = playable.browser_video(src)
    name, pix_fmt, frames = _codec(out)
    assert name == "h264" and pix_fmt == "yuv420p" and frames == 12


def test_odd_frame_sizes_are_accepted(tmp_path):
    """H.264 in yuv420p needs even sides; a 161x121 clip must still convert."""
    out = playable.browser_video(_mp4v_clip(tmp_path / "odd.mp4", size=(161, 121)))
    assert _codec(out)[0] == "h264"


def test_an_unreadable_file_is_returned_unchanged(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    assert playable.browser_video(bad) == bad


def test_report_json_takes_numpy_numbers():
    report = {"avg_rom": np.float32(117.3), "total_reps": np.int64(4),
              "reps": [{"rom": np.float32(120.5), "angles": np.array([90.0, 170.0])}]}
    data = json.loads(playable.report_json(report))
    assert data["total_reps"] == 4 and abs(data["avg_rom"] - 117.3) < 1e-4
    assert data["reps"][0]["angles"] == [90.0, 170.0]
