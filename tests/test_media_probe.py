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


# ----------------------------------------------------------------------------- feature 014: voice notes

@pytest.fixture(scope="module")
def audio_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("audio")
    return {
        "m4a": fx.make_audio(d / "a.m4a", seconds=1.5),
        "mp3": fx.make_audio(d / "b.mp3", seconds=1.5),
        "ogg": fx.make_audio(d / "c.ogg", seconds=1.5),
        "wav": fx.make_audio(d / "d.wav", seconds=1.5),
        "webm": fx.make_audio(d / "e.webm", seconds=1.5),
        "silent": fx.make_audio(d / "f.m4a", seconds=1.0, silent=True),
        "with_video": fx.make_video(d / "g.mp4", seconds=1.5, audio=True),      # audio, but it carries video
        "no_audio": fx.make_video(d / "h.webm", seconds=1.0, codec="libvpx"),
        "truncated": fx.truncate(fx.make_audio(d / "i.m4a", seconds=3.0), 0.1),
        "text": (lambda p: (p.write_text("dear therapist, my knee hurts"), p)[1])(d / "j.m4a"),
        "long": fx.make_audio(d / "k.m4a", seconds=200.0, rate=8000, chunk=8000),   # cheap to build
        "empty": (lambda p: (p.write_bytes(b""), p)[1])(d / "l.m4a"),
    }


@pytest.mark.parametrize("key, ext, codec", [
    ("m4a", "m4a", "aac"), ("mp3", "mp3", "mp3"), ("ogg", "ogg", "opus"),
    ("wav", "wav", "pcm_s16le"), ("webm", "webm", "opus"),
])
def test_accepts_what_a_phone_records(audio_files, key, ext, codec):
    info = probe.probe(audio_files[key], kind="voice")
    assert info.ext == ext and codec in info.codec                 # mp3 decodes as "mp3float"
    assert info.has_audio and not info.has_video
    assert 1.0 <= info.duration <= 2.0 and info.bytes > 0
    assert info.width == 0 and info.height == 0


def test_silence_is_still_a_voice_note(audio_files):
    """A patient may record nothing audible; that is theirs to decide, not ours to refuse."""
    info = probe.probe(audio_files["silent"], kind="voice")
    assert info.has_audio and info.duration > 0


@pytest.mark.parametrize("key, reason", [
    ("with_video", "has_video"),      # a video file is a clip, not a voice note
    ("no_audio", "has_video"),        # a silent video is still a video: the picture is what disqualifies it
    ("text", "not_media"),
    ("empty", "not_media"),
    ("long", "too_long"),
])
def test_audio_refusals_carry_a_reason_word(audio_files, key, reason):
    with pytest.raises(MediaRejected) as err:
        probe.probe(audio_files[key], kind="voice")
    assert err.value.reason == reason
    assert len(str(err.value)) > 20 and "voice note" in str(err.value).lower() or reason == "not_media"


def test_the_no_audio_refusal_exists_for_a_file_that_is_neither(audio_files):
    """No fixture can reach it: a real file without audio either carries video (refused `has_video`) or
    cannot be opened at all (`not_media`). The reason word stays for a container of only data streams,
    and this test pins its wording so the path is not silently lost."""
    assert "no_audio" in probe.REASONS and "sound" in probe.REASONS["no_audio"]


def test_a_damaged_recording_is_refused(audio_files):
    with pytest.raises(MediaRejected) as err:
        probe.probe(audio_files["truncated"], kind="voice")
    assert err.value.reason in ("damaged", "not_media")


def test_the_size_limit_is_audio_sized(audio_files):
    assert probe.LIMITS["voice"]["max_bytes"] < probe.LIMITS["clip"]["max_bytes"]
    with pytest.raises(MediaRejected) as err:
        probe.probe(audio_files["m4a"], kind="voice", max_bytes=100)
    assert err.value.reason == "too_large"


def test_the_isolated_probe_works_for_audio(audio_files):
    info = probe.run_isolated(audio_files["m4a"], kind="voice", timeout=30.0)
    assert info.ext == "m4a" and info.has_audio and not info.has_video
