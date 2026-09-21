"""
Body-point messages from the patient's browser (feature 007): parsing, validation, scaling to the
frame size the engine's form checks were calibrated on, and the incoming rate.

The service never receives video. Each frame message carries 17 points as x, y, score in the video's
own pixel space (COCO order), plus the frame size. Nothing a client sends about time or frame
numbers is trusted.
"""

from __future__ import annotations

import json
import math
from collections import deque
from datetime import datetime
from typing import Any, Callable, Deque, Dict, Optional, Tuple

import numpy as np

from src.ptlog.models import PortalError

MAX_MESSAGE_BYTES = 4096
POINTS = 17
REFERENCE_HEIGHT = 720.0          # the engine's pixel-distance form checks were tuned near 720p
MIN_SIDE, MAX_SIDE = 64, 4096
MESSAGE_TYPES = ("start", "frame", "next", "stop")


class FrameError(PortalError):
    """A message from the browser is not what the contract allows."""


def parse(text: Any) -> Dict[str, Any]:
    """A WebSocket text message as a dict with a known `type`, or FrameError."""
    if not isinstance(text, str) or len(text.encode("utf-8", "ignore")) > MAX_MESSAGE_BYTES:
        raise FrameError("message too large or not text")
    try:
        data = json.loads(text)
    except ValueError:
        raise FrameError("message is not JSON") from None
    if not isinstance(data, dict) or data.get("type") not in MESSAGE_TYPES:
        raise FrameError("unknown message")
    return data


def _side(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_SIDE <= value <= MAX_SIDE:
        raise FrameError("frame size out of range")
    return value


def validate_frame(message: Any) -> Tuple[Optional[np.ndarray], int, int]:
    """(keypoints or None, width, height). Points up to half a frame outside the picture are kept
    (pose models extrapolate); anything further is clamped. Scores are clamped to 0-1."""
    if not isinstance(message, dict):
        raise FrameError("frame is not an object")
    w, h = _side(message.get("w")), _side(message.get("h"))
    k = message.get("k")
    if k is None:
        return None, w, h
    if not isinstance(k, list) or len(k) != POINTS * 3:
        raise FrameError("a frame carries 17 points of x, y, score")
    for v in k:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise FrameError("points must be finite numbers")
    kp = np.asarray(k, dtype=np.float32).reshape(POINTS, 3)
    kp[:, 0] = np.clip(kp[:, 0], -0.5 * w, 1.5 * w)
    kp[:, 1] = np.clip(kp[:, 1], -0.5 * h, 1.5 * h)
    kp[:, 2] = np.clip(kp[:, 2], 0.0, 1.0)
    return kp, w, h


def to_engine_keypoints(keypoints: Optional[np.ndarray], width: int, height: int) -> Optional[np.ndarray]:
    """Scale x and y by one factor so the frame is 720 pixels high. One factor for both axes keeps
    every joint angle unchanged; the engine's pixel-distance checks then see clinic-like sizes."""
    if keypoints is None:
        return None
    scaled = np.array(keypoints, dtype=np.float32, copy=True)
    scaled[:, :2] *= REFERENCE_HEIGHT / float(height)
    return scaled


class RateMeter:
    """Counts accepted frames, drops those above the cap, and notices a device that cannot keep up."""

    def __init__(self, clock: Callable[[], datetime] = datetime.now, nominal: int = 15, cap: int = 20,
                 floor: int = 12, slow_seconds: float = 5.0):
        self.clock, self.nominal, self.cap, self.floor, self.slow_seconds = clock, nominal, cap, floor, slow_seconds
        self._recent: Deque[datetime] = deque()
        self._slow_since: Optional[datetime] = None
        self._started: Optional[datetime] = None
        self.accepted = 0
        self.dropped = 0
        self.low_rate = False
        self.was_low_rate = False

    def accept(self) -> bool:
        now = self.clock()
        if self._started is None:
            self._started = now
        while self._recent and (now - self._recent[0]).total_seconds() >= 1.0:
            self._recent.popleft()
        if len(self._recent) >= self.cap:
            self.dropped += 1
            return False
        self._recent.append(now)
        self.accepted += 1
        self._watch(now)
        return True

    def _watch(self, now: datetime) -> None:
        if (now - self._started).total_seconds() < 1.0:
            return                                           # not enough history to judge
        if len(self._recent) < self.floor:
            self._slow_since = self._slow_since or now
            if (now - self._slow_since).total_seconds() >= self.slow_seconds:
                self.low_rate = self.was_low_rate = True
        else:
            self._slow_since = None
            self.low_rate = False

    @property
    def observed(self) -> float:
        """Accepted frames per second over the session so far."""
        if self._started is None or self.accepted < 2:
            return 0.0
        seconds = (self.clock() - self._started).total_seconds()
        return round(self.accepted / seconds, 1) if seconds > 0 else 0.0
