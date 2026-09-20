"""Synthetic poses for driving the real engine without a camera or the model."""

import math
from typing import Iterable, List, Optional

import numpy as np

# A plausible standing figure (x, y) in a 640x480 frame, COCO-17 order.
_BASE = [
    (320, 60), (312, 52), (328, 52), (304, 58), (336, 58),      # nose, eyes, ears
    (290, 110), (350, 110), (280, 170), (360, 170), (275, 225), (365, 225),  # shoulders, elbows, wrists
    (300, 230), (340, 230), (300, 330), (340, 330), (300, 430), (340, 430),  # hips, knees, ankles
]


def keypoints_for_angle(angle: float) -> np.ndarray:
    """(17, 3) keypoints whose left hip (11), knee (13), ankle (15) form `angle` degrees at the knee."""
    kp = np.array([[x, y, 1.0] for x, y in _BASE], dtype=np.float32)
    hip = np.array([300.0, 230.0])
    knee = np.array([300.0, 330.0])
    a = math.radians(angle)
    # hip sits straight above the knee (direction (0,-1)); rotate that direction by `angle`
    ankle = knee + 100.0 * np.array([math.sin(a), -math.cos(a)])
    kp[11, :2], kp[13, :2], kp[15, :2] = hip, knee, ankle
    return kp


def rep_cycle(top: float = 172.0, bottom: float = 85.0, hold: int = 8, steps: int = 6) -> List[float]:
    """Angles for one rep: hold top, move to bottom, hold, move back, hold top."""
    down = list(np.linspace(top, bottom, steps))
    up = list(np.linspace(bottom, top, steps))
    return [top] * hold + down + [bottom] * hold + up + [top] * hold


class FakeInfer:
    """Stands in for the pose model: returns keypoints for each queued angle, None for a None angle."""

    def __init__(self, angles: Iterable[Optional[float]] = ()):
        self.angles = list(angles)
        self.calls = 0

    def extend(self, angles: Iterable[Optional[float]]):
        self.angles.extend(angles)

    def __call__(self, frame):
        angle = self.angles[self.calls] if self.calls < len(self.angles) else None
        self.calls += 1
        return None if angle is None else keypoints_for_angle(angle)
