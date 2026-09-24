"""Feature 011 T002 — the file says what it is, not its name or declared type."""

import sys
from pathlib import Path

import pytest

from src.media import probe
from src.media.probe import MediaRejected
from tests.fixtures import media as fx


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    return {
        "mp4": fx.make_video(d / "a.mp4", codec="libx264", audio=True),
        "webm": fx.make_video(d / "b.webm", codec="libvpx"),
        "mov_hevc": fx.make_video(d / "c.mov", codec="hevc"),
        "audio": fx.make_audio(d / "d.m4a"),
        "png": fx.make_png_named_mp4(d / "e.mp4"),
        "html": (lambda p: (p.write_text("<html><script>alert(1)</script></html>"), p)[1])(d / "f.mp4"),
        "truncated": fx.truncate(fx.make_video(d / "g.webm", seconds=3.0, codec="libvpx"), 0.15),   # cut inside the header
        "long": fx.make_video(d / "h.mp4", seconds=70.0, fps=5, size=(32, 32)),
        "empty": (lambda p: (p.write_bytes(b""), p)[1])(d / "i.mp4"),
    }


def test_accepts_the_three_containers(files):
    for key, ext, codec in (("mp4", "mp4", "h264"), ("webm", "webm", "vp8"), ("mov_hevc", "mp4", "hevc")):   # MOV is the same family, stored as .mp4
        info = probe.probe(files[key], kind="clip")
        assert (info.ext, info.codec) == (ext, codec) and info.width == 64 and 1.5 <= info.duration <= 2.5, key
        assert info.container and info.has_video and info.bytes > 0
    assert probe.probe(files["mp4"], kind="clip").has_audio is True


@pytest.mark.parametrize("key,reason", [
    ("audio", "no_video"), ("png", "not_media"), ("html", "not_media"), ("truncated", "damaged"),
    ("long", "too_long"), ("empty", "not_media"),
])
def test_refusals_carry_a_reason_word(files, key, reason):
    with pytest.raises(MediaRejected) as err:
        probe.probe(files[key], kind="clip")
    if key == "truncated":
        assert err.value.reason in ("damaged", "not_media")      # a file cut short but still readable is accepted as it is
    else:
        assert err.value.reason == reason
    assert len(str(err.value)) > 20


def test_isolated_probe_survives_a_hang_and_a_crash(files, monkeypatch, tmp_path):
    info = probe.run_isolated(files["mp4"], kind="clip", timeout=30)
    assert info.codec == "h264"
    with pytest.raises(MediaRejected) as err:
        probe.run_isolated(files["png"], kind="clip", timeout=30)
    assert err.value.reason == "not_media"
    hang = tmp_path / "hang.py"
    hang.write_text("import time; time.sleep(60)")
    monkeypatch.setattr(probe, "_WORKER_ARGS", [sys.executable, str(hang)])
    with pytest.raises(MediaRejected) as err:
        probe.run_isolated(files["mp4"], kind="clip", timeout=1)
    assert err.value.reason == "timeout"
    crash = tmp_path / "crash.py"
    crash.write_text("import os; os._exit(139)")
    monkeypatch.setattr(probe, "_WORKER_ARGS", [sys.executable, str(crash)])
    with pytest.raises(MediaRejected) as err:
        probe.run_isolated(files["mp4"], kind="clip", timeout=5)
    assert err.value.reason == "damaged"


def test_size_limit(files):
    with pytest.raises(MediaRejected) as err:
        probe.probe(files["mp4"], kind="clip", max_bytes=100)
    assert err.value.reason == "too_large"
