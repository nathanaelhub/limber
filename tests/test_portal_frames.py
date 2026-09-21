"""Feature 007 T022 — body-point messages from the patient's browser: validation, scaling, rate."""

import json
from datetime import datetime, timedelta

import numpy as np
import pytest

from analyze import get_angle_from_keypoints
from src.portal import frames
from src.ptlog.models import PortalError
from tests.fixtures.poses import keypoints_for_angle


def message(angle=120.0, w=640, h=480, **extra):
    k = keypoints_for_angle(angle).reshape(-1).tolist()
    return {"type": "frame", "k": k, "w": w, "h": h, **extra}


class TestValidate:
    def test_a_good_frame_becomes_a_17_by_3_array(self):
        kp, w, h = frames.validate_frame(message())
        assert kp.shape == (17, 3) and kp.dtype == np.float32 and (w, h) == (640, 480)

    def test_nobody_in_view(self):
        assert frames.validate_frame({"type": "frame", "k": None, "w": 640, "h": 480}) == (None, 640, 480)

    def test_points_slightly_outside_the_frame_are_clamped_not_rejected(self):
        m = message()
        m["k"][0], m["k"][1] = -50.0, 700.0                 # within half a frame outside: allowed
        kp, _, _ = frames.validate_frame(m)
        assert kp[0, 0] == -50.0 and kp[0, 1] == 700.0
        m["k"][0] = -5000.0
        kp, _, _ = frames.validate_frame(m)
        assert kp[0, 0] == -320.0                           # clamped to half a frame width outside
        m["k"][2] = 7.5                                     # a score above 1 is clamped too
        assert frames.validate_frame(m)[0][0, 2] == 1.0

    @pytest.mark.parametrize("bad", [
        {"type": "frame", "k": [1.0] * 50, "w": 640, "h": 480},
        {"type": "frame", "k": [1.0] * 52, "w": 640, "h": 480},
        {"type": "frame", "k": "not a list", "w": 640, "h": 480},
        {"type": "frame", "k": [float("nan")] + [1.0] * 50, "w": 640, "h": 480},
        {"type": "frame", "k": [float("inf")] + [1.0] * 50, "w": 640, "h": 480},
        {"type": "frame", "k": ["x"] * 51, "w": 640, "h": 480},
        {"type": "frame", "k": [True] * 51, "w": 640, "h": 480},
        {"type": "frame", "k": [1.0] * 51, "w": 10, "h": 480},
        {"type": "frame", "k": [1.0] * 51, "w": 640, "h": 99999},
        {"type": "frame", "k": [1.0] * 51, "w": "640", "h": 480},
        {"type": "frame", "k": [1.0] * 51},
        "just text", None, [1, 2, 3],
    ])
    def test_malformed_frames_are_rejected(self, bad):
        with pytest.raises(PortalError):
            frames.validate_frame(bad)

    def test_parse_enforces_the_size_limit_and_json(self):
        assert frames.parse(json.dumps({"type": "start"}))["type"] == "start"
        with pytest.raises(PortalError):
            frames.parse("x" * 5000)
        with pytest.raises(PortalError):
            frames.parse("{not json")
        with pytest.raises(PortalError):
            frames.parse(json.dumps(["a list"]))
        with pytest.raises(PortalError):
            frames.parse(json.dumps({"type": "launch"}))


class TestScale:
    @pytest.mark.parametrize("h", [360, 480, 720, 1080])
    def test_uniform_scale_to_720_keeps_every_angle(self, h):
        w = int(h * 16 / 9)
        kp = keypoints_for_angle(133.0).copy()
        kp[:, :2] *= h / 480.0
        scaled = frames.to_engine_keypoints(kp, w, h)
        before = get_angle_from_keypoints(kp, [11, 13, 15])
        after = get_angle_from_keypoints(scaled, [11, 13, 15])
        assert after == pytest.approx(before, abs=1e-3)
        assert scaled[13, 1] == pytest.approx(kp[13, 1] * 720.0 / h, rel=1e-5)     # pixel distances now at 720p scale
        assert (scaled[:, 2] == kp[:, 2]).all() and scaled is not kp

    def test_portrait_phone_uses_the_same_factor_on_both_axes(self):
        kp = keypoints_for_angle(90.0)
        scaled = frames.to_engine_keypoints(kp, 480, 640)
        factor = 720.0 / 640
        assert np.allclose(scaled[:, 0], kp[:, 0] * factor) and np.allclose(scaled[:, 1], kp[:, 1] * factor)

    def test_none_passes_through(self):
        assert frames.to_engine_keypoints(None, 640, 480) is None


class TestRateMeter:
    def test_observed_rate_and_the_cap(self):
        now = [datetime(2026, 9, 21, 9, 0, 0)]
        meter = frames.RateMeter(clock=lambda: now[0], nominal=15, cap=20)
        accepted = 0
        for _ in range(40):                                 # forty messages inside one second
            accepted += meter.accept()
            now[0] += timedelta(milliseconds=20)
        assert accepted == 20 and meter.dropped == 20
        now[0] += timedelta(seconds=1)
        assert meter.accept() is True

    def test_low_rate_is_reported_after_five_slow_seconds(self):
        now = [datetime(2026, 9, 21, 9, 0, 0)]
        meter = frames.RateMeter(clock=lambda: now[0], nominal=15, floor=12)
        for _ in range(15 * 6):                             # six seconds at 15 Hz
            meter.accept(); now[0] += timedelta(seconds=1 / 15)
        assert meter.low_rate is False and 14 <= meter.observed <= 16
        for _ in range(10 * 4):                             # four slow seconds: not yet
            meter.accept(); now[0] += timedelta(seconds=1 / 10)
        assert meter.low_rate is False
        for _ in range(10 * 3):
            meter.accept(); now[0] += timedelta(seconds=1 / 10)
        assert meter.low_rate is True and meter.was_low_rate is True
        for _ in range(15 * 3):
            meter.accept(); now[0] += timedelta(seconds=1 / 15)
        assert meter.low_rate is False and meter.was_low_rate is True          # the session stays tagged
