"""
Tests for Core Analysis Functions
==================================

Tests angle calculation, rep counting state machine, and video processing.

Run with:
    pytest tests/test_analysis.py -v
"""

import pytest
import numpy as np
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils import (
    calculate_angle,
    extract_keypoint,
    get_angle_from_keypoints,
    get_keypoint_distance,
    get_midpoint,
    get_trunk_angle,
    calculate_angle_with_vertical,
    calculate_angle_with_horizontal,
)


# =============================================================================
# FIXTURES - Mock Keypoint Data
# =============================================================================

@pytest.fixture
def straight_leg_keypoints():
    """
    Keypoints representing a straight leg (knee angle ~180°).

    Hip at (100, 100), Knee at (100, 200), Ankle at (100, 300)
    All points vertically aligned = 180° angle
    """
    keypoints = np.zeros((17, 3))
    keypoints[11] = [100, 100, 0.9]  # Left hip
    keypoints[13] = [100, 200, 0.9]  # Left knee
    keypoints[15] = [100, 300, 0.9]  # Left ankle
    return keypoints


@pytest.fixture
def bent_knee_keypoints():
    """
    Keypoints representing a bent knee (angle ~90°).

    Hip at (100, 100), Knee at (100, 200), Ankle at (200, 200)
    Forms a right angle at the knee
    """
    keypoints = np.zeros((17, 3))
    keypoints[11] = [100, 100, 0.9]  # Left hip
    keypoints[13] = [100, 200, 0.9]  # Left knee
    keypoints[15] = [200, 200, 0.9]  # Left ankle (to the right)
    return keypoints


@pytest.fixture
def standing_pose_keypoints():
    """
    Keypoints representing a person standing upright.
    """
    keypoints = np.zeros((17, 3))
    # Head
    keypoints[0] = [150, 50, 0.95]   # Nose
    keypoints[1] = [140, 45, 0.9]    # Left eye
    keypoints[2] = [160, 45, 0.9]    # Right eye
    keypoints[3] = [130, 50, 0.85]   # Left ear
    keypoints[4] = [170, 50, 0.85]   # Right ear

    # Upper body
    keypoints[5] = [120, 120, 0.95]  # Left shoulder
    keypoints[6] = [180, 120, 0.95]  # Right shoulder
    keypoints[7] = [110, 200, 0.9]   # Left elbow
    keypoints[8] = [190, 200, 0.9]   # Right elbow
    keypoints[9] = [105, 280, 0.85]  # Left wrist
    keypoints[10] = [195, 280, 0.85] # Right wrist

    # Lower body
    keypoints[11] = [130, 280, 0.95] # Left hip
    keypoints[12] = [170, 280, 0.95] # Right hip
    keypoints[13] = [130, 400, 0.9]  # Left knee
    keypoints[14] = [170, 400, 0.9]  # Right knee
    keypoints[15] = [130, 520, 0.85] # Left ankle
    keypoints[16] = [170, 520, 0.85] # Right ankle

    return keypoints


@pytest.fixture
def low_confidence_keypoints():
    """Keypoints with low confidence scores."""
    keypoints = np.zeros((17, 3))
    keypoints[11] = [100, 100, 0.1]  # Low confidence hip
    keypoints[13] = [100, 200, 0.2]  # Low confidence knee
    keypoints[15] = [100, 300, 0.9]  # Good confidence ankle
    return keypoints


# =============================================================================
# ANGLE CALCULATION TESTS
# =============================================================================

class TestCalculateAngle:
    """Tests for the calculate_angle function."""

    def test_straight_line_180_degrees(self):
        """Three collinear points should give 180°."""
        p1 = np.array([0, 0])
        vertex = np.array([0, 1])
        p2 = np.array([0, 2])

        angle = calculate_angle(p1, vertex, p2)
        assert abs(angle - 180) < 0.1, f"Expected ~180°, got {angle}°"

    def test_right_angle_90_degrees(self):
        """Points forming an L should give 90°."""
        p1 = np.array([0, 0])
        vertex = np.array([0, 1])
        p2 = np.array([1, 1])

        angle = calculate_angle(p1, vertex, p2)
        assert abs(angle - 90) < 0.1, f"Expected ~90°, got {angle}°"

    def test_45_degree_angle(self):
        """Points forming 45° angle."""
        p1 = np.array([0, 1])
        vertex = np.array([0, 0])
        p2 = np.array([1, 1])  # 45° from vertical

        angle = calculate_angle(p1, vertex, p2)
        assert abs(angle - 45) < 0.1, f"Expected ~45°, got {angle}°"

    def test_zero_length_vector(self):
        """Should return 0 when vector length is zero."""
        p1 = np.array([1, 1])
        vertex = np.array([1, 1])  # Same as p1
        p2 = np.array([2, 2])

        angle = calculate_angle(p1, vertex, p2)
        assert angle == 0.0

    def test_angle_is_symmetric(self):
        """Swapping p1 and p2 should give same angle."""
        p1 = np.array([0, 0])
        vertex = np.array([1, 1])
        p2 = np.array([2, 0])

        angle1 = calculate_angle(p1, vertex, p2)
        angle2 = calculate_angle(p2, vertex, p1)

        assert abs(angle1 - angle2) < 0.01


class TestAngleFromKeypoints:
    """Tests for get_angle_from_keypoints function."""

    def test_straight_leg_angle(self, straight_leg_keypoints):
        """Straight leg should give ~180°."""
        angle = get_angle_from_keypoints(straight_leg_keypoints, [11, 13, 15])
        assert angle is not None
        assert abs(angle - 180) < 0.1, f"Expected ~180°, got {angle}°"

    def test_bent_knee_angle(self, bent_knee_keypoints):
        """Bent knee should give ~90°."""
        angle = get_angle_from_keypoints(bent_knee_keypoints, [11, 13, 15])
        assert angle is not None
        assert abs(angle - 90) < 0.1, f"Expected ~90°, got {angle}°"

    def test_missing_keypoint_returns_none(self, straight_leg_keypoints):
        """Should return None if keypoint is missing."""
        straight_leg_keypoints[13] = [0, 0, 0]  # Remove knee
        angle = get_angle_from_keypoints(straight_leg_keypoints, [11, 13, 15])
        assert angle is None

    def test_low_confidence_returns_none(self, low_confidence_keypoints):
        """Should return None if confidence is too low."""
        angle = get_angle_from_keypoints(low_confidence_keypoints, [11, 13, 15])
        assert angle is None

    def test_invalid_indices_returns_none(self, straight_leg_keypoints):
        """Should return None for invalid keypoint indices."""
        angle = get_angle_from_keypoints(straight_leg_keypoints, [11, 13])  # Only 2 indices
        assert angle is None


# =============================================================================
# KEYPOINT EXTRACTION TESTS
# =============================================================================

class TestExtractKeypoint:
    """Tests for extract_keypoint function."""

    def test_extract_valid_keypoint(self, standing_pose_keypoints):
        """Should return coordinates for valid keypoint."""
        point = extract_keypoint(standing_pose_keypoints, 11)  # Left hip
        assert point is not None
        assert len(point) == 2
        assert point[0] == 130  # x coordinate
        assert point[1] == 280  # y coordinate

    def test_extract_low_confidence_returns_none(self, low_confidence_keypoints):
        """Should return None for low confidence keypoint."""
        point = extract_keypoint(low_confidence_keypoints, 11)  # Low confidence
        assert point is None

    def test_extract_with_custom_threshold(self, low_confidence_keypoints):
        """Should work with custom confidence threshold."""
        # With threshold of 0.05, should extract the point
        point = extract_keypoint(low_confidence_keypoints, 11, confidence_threshold=0.05)
        assert point is not None

    def test_extract_invalid_index(self, standing_pose_keypoints):
        """Should return None for invalid index."""
        point = extract_keypoint(standing_pose_keypoints, 99)
        assert point is None

    def test_extract_from_none_keypoints(self):
        """Should return None for None keypoints."""
        point = extract_keypoint(None, 11)
        assert point is None


class TestKeypointDistance:
    """Tests for get_keypoint_distance function."""

    def test_distance_between_hips(self, standing_pose_keypoints):
        """Distance between hips should be calculable."""
        distance = get_keypoint_distance(standing_pose_keypoints, 11, 12)
        assert distance is not None
        # Left hip at 130, right hip at 170, same y -> distance = 40
        assert abs(distance - 40) < 0.1

    def test_vertical_distance(self, straight_leg_keypoints):
        """Vertical distance calculation."""
        distance = get_keypoint_distance(straight_leg_keypoints, 11, 13)
        assert distance is not None
        # Hip at y=100, knee at y=200 -> distance = 100
        assert abs(distance - 100) < 0.1


class TestMidpoint:
    """Tests for get_midpoint function."""

    def test_hip_center(self, standing_pose_keypoints):
        """Midpoint of hips should be at center."""
        midpoint = get_midpoint(standing_pose_keypoints, 11, 12)
        assert midpoint is not None
        # Left hip at (130, 280), right hip at (170, 280) -> midpoint (150, 280)
        assert abs(midpoint[0] - 150) < 0.1
        assert abs(midpoint[1] - 280) < 0.1


# =============================================================================
# TRUNK ANGLE TESTS
# =============================================================================

class TestTrunkAngle:
    """Tests for trunk angle calculation."""

    def test_upright_trunk(self, standing_pose_keypoints):
        """Standing straight should have ~0° trunk angle."""
        # Adjust shoulders to be directly above hips
        standing_pose_keypoints[5] = [130, 120, 0.95]  # Left shoulder above left hip
        standing_pose_keypoints[6] = [170, 120, 0.95]  # Right shoulder above right hip

        trunk_angle = get_trunk_angle(standing_pose_keypoints)
        assert trunk_angle is not None
        assert trunk_angle < 5, f"Expected <5° for upright trunk, got {trunk_angle}°"

    def test_leaning_trunk(self, standing_pose_keypoints):
        """Leaning forward should have larger trunk angle."""
        # Move shoulders forward (increase x, simulating lean)
        standing_pose_keypoints[5] = [180, 120, 0.95]  # Left shoulder
        standing_pose_keypoints[6] = [240, 120, 0.95]  # Right shoulder

        trunk_angle = get_trunk_angle(standing_pose_keypoints)
        assert trunk_angle is not None
        assert trunk_angle > 10, f"Expected >10° for leaning trunk"


class TestAngleWithVertical:
    """Tests for calculate_angle_with_vertical function."""

    def test_vertical_line(self):
        """Vertical line should have 0° angle."""
        p1 = np.array([100, 0])
        p2 = np.array([100, 100])

        angle = calculate_angle_with_vertical(p1, p2)
        assert abs(angle) < 0.1

    def test_horizontal_line(self):
        """Horizontal line should have 90° angle from vertical."""
        p1 = np.array([0, 100])
        p2 = np.array([100, 100])

        angle = calculate_angle_with_vertical(p1, p2)
        assert abs(angle - 90) < 0.1


class TestAngleWithHorizontal:
    """Tests for calculate_angle_with_horizontal function."""

    def test_horizontal_line(self):
        """Horizontal line should have 0° angle."""
        p1 = np.array([0, 100])
        p2 = np.array([100, 100])

        angle = calculate_angle_with_horizontal(p1, p2)
        assert abs(angle) < 0.1

    def test_vertical_line(self):
        """Vertical line should have 90° angle from horizontal."""
        p1 = np.array([100, 0])
        p2 = np.array([100, 100])

        angle = calculate_angle_with_horizontal(p1, p2)
        assert abs(angle - 90) < 0.1


# =============================================================================
# REP COUNTING STATE MACHINE TESTS
# =============================================================================


def _hold(tracker, angle):
    """Feed an angle for a full smoothing window so the moving average settles on it."""
    for _ in range(tracker.angle_buffer.maxlen):
        tracker.update(angle)

class TestRepCountingStateMachine:
    """Tests for the rep counting logic."""

    def test_state_transitions(self):
        """Test that state transitions work correctly."""
        from dataclasses import dataclass

        @dataclass
        class SimpleConfig:
            name: str = "test"
            keypoints: list = None
            up_angle: float = 170
            down_angle: float = 90
            form_tolerance: float = 15
            target_reps: int = 10

            def __post_init__(self):
                if self.keypoints is None:
                    self.keypoints = [11, 13, 15]

        # Import after path setup
        try:
            # Try to import from analyze.py
            from analyze import ExerciseTracker
            config = SimpleConfig()
            tracker = ExerciseTracker(config, fps=30.0)

            # Simulate a rep: down -> up -> down
            # Start in neutral
            assert tracker.current_state == "neutral"
            assert tracker.rep_count == 0

            # Move to down position (hold so the 5-frame moving average settles)
            _hold(tracker, 90)
            assert tracker.current_state == "down"
            assert tracker.rep_count == 0

            # Move to up position
            _hold(tracker, 170)
            assert tracker.current_state == "up"
            assert tracker.rep_count == 0  # Not counted until back to down

            # Return to down (completes rep)
            _hold(tracker, 90)
            assert tracker.current_state == "down"
            assert tracker.rep_count == 1  # Rep completed!

        except ImportError:
            pytest.skip("analyze.py not available for import")

    def test_multiple_reps(self):
        """Test counting multiple reps."""
        from dataclasses import dataclass

        @dataclass
        class SimpleConfig:
            name: str = "test"
            keypoints: list = None
            up_angle: float = 170
            down_angle: float = 90
            form_tolerance: float = 15
            target_reps: int = 10

            def __post_init__(self):
                if self.keypoints is None:
                    self.keypoints = [11, 13, 15]

        try:
            from analyze import ExerciseTracker
            config = SimpleConfig()
            tracker = ExerciseTracker(config, fps=30.0)

            # Simulate 3 complete reps
            angles = [90, 170, 90, 170, 90, 170, 90]  # down-up-down-up-down-up-down

            for angle in angles:
                _hold(tracker, angle)  # settle the moving average at each position

            assert tracker.rep_count == 3

        except ImportError:
            pytest.skip("analyze.py not available for import")

    def test_incomplete_rep_not_counted(self):
        """Incomplete reps should not be counted."""
        from dataclasses import dataclass

        @dataclass
        class SimpleConfig:
            name: str = "test"
            keypoints: list = None
            up_angle: float = 170
            down_angle: float = 90
            form_tolerance: float = 15
            target_reps: int = 10

            def __post_init__(self):
                if self.keypoints is None:
                    self.keypoints = [11, 13, 15]

        try:
            from analyze import ExerciseTracker
            config = SimpleConfig()
            tracker = ExerciseTracker(config, fps=30.0)

            # Go halfway and stop
            tracker.update(90)   # down
            tracker.update(130)  # midway (not reaching up threshold)
            tracker.update(90)   # back to down

            # Should not count as a rep
            assert tracker.rep_count == 0

        except ImportError:
            pytest.skip("analyze.py not available for import")


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests for the full pipeline."""

    def test_full_keypoint_to_angle_pipeline(self, standing_pose_keypoints):
        """Test extracting keypoints and calculating angle."""
        # Extract knee angle (hip-knee-ankle)
        angle = get_angle_from_keypoints(standing_pose_keypoints, [11, 13, 15])

        # Standing position should have nearly straight legs
        assert angle is not None
        assert 160 < angle <= 180, f"Standing leg angle should be ~180°, got {angle}°"

    def test_multiple_angle_calculations(self, standing_pose_keypoints):
        """Test calculating multiple angles from same keypoints."""
        # Left knee angle
        left_knee = get_angle_from_keypoints(standing_pose_keypoints, [11, 13, 15])

        # Right knee angle
        right_knee = get_angle_from_keypoints(standing_pose_keypoints, [12, 14, 16])

        # Left elbow angle
        left_elbow = get_angle_from_keypoints(standing_pose_keypoints, [5, 7, 9])

        assert all(a is not None for a in [left_knee, right_knee, left_elbow])

        # Both knees should be similar (standing pose)
        assert abs(left_knee - right_knee) < 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
