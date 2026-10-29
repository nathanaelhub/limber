#!/usr/bin/env python3
"""
AI Physical Therapy Assistant
=============================
A comprehensive pose estimation system for monitoring physical therapy exercises
using Ultralytics YOLO11 pose estimation.

This script provides real-time feedback on:
- Exercise rep counting
- Joint angle measurements
- Range of motion tracking
- Form quality assessment
- Tempo/pace analysis

YOLO11 Pose Keypoint Reference (17 keypoints):
    0: Nose           1: Left Eye       2: Right Eye
    3: Left Ear       4: Right Ear      5: Left Shoulder
    6: Right Shoulder 7: Left Elbow     8: Right Elbow
    9: Left Wrist    10: Right Wrist   11: Left Hip
   12: Right Hip     13: Left Knee     14: Right Knee
   15: Left Ankle    16: Right Ankle

Author: AI PT Assistant
Version: 1.0.0
"""

import cv2
import numpy as np
import yaml
import json
import csv
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple, List, Dict, Any
from collections import deque
from ultralytics import YOLO
from ultralytics.solutions import AIGym
from src.form_assessment import FormAnalyzer
from src.ptlog.models import PatientNotFoundError
from src.ptlog.recorder import SessionRecorder
from src.ptlog.store import SessionStore, default_db_path


# =============================================================================
# DATA CLASSES FOR STRUCTURED METRICS
# =============================================================================

@dataclass
class RepMetrics:
    """Stores metrics for a single repetition."""
    rep_number: int
    min_angle: float
    max_angle: float
    rom: float  # Range of motion (max - min)
    duration_seconds: float
    form_score: float  # 0-100%
    timestamp: str


@dataclass
class PartialRepMetrics:
    """Stores metrics for a partial/incomplete repetition attempt."""
    exercise: str
    min_angle: float
    max_angle: float
    rom: float
    duration_seconds: float
    reason: str  # "insufficient_rom", "reversed_early", "interrupted"
    timestamp: str


@dataclass
class ExerciseSession:
    """Stores complete session data for an exercise."""
    exercise_name: str
    start_time: str
    end_time: str = ""
    total_reps: int = 0
    target_reps: int = 0
    avg_rom: float = 0.0
    max_rom: float = 0.0
    avg_form_score: float = 0.0
    tempo_consistency: float = 0.0  # Standard deviation of rep durations
    rep_metrics: List[RepMetrics] = field(default_factory=list)
    partial_rep_metrics: List[PartialRepMetrics] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ExerciseConfig:
    """Configuration for a specific exercise."""
    name: str
    keypoints: List[int]  # [point1, vertex, point2] for angle calculation
    up_angle: float       # Angle at "up" or extended position
    down_angle: float     # Angle at "down" or flexed position
    form_tolerance: float # Acceptable deviation from target angles
    target_reps: int
    side: str = "left"    # "left", "right", or "bilateral"


# =============================================================================
# CORE ANGLE CALCULATION FUNCTIONS
# =============================================================================

def calculate_angle(point1: np.ndarray, vertex: np.ndarray, point2: np.ndarray) -> float:
    """
    Calculate the angle formed by three points, with vertex as the middle point.

    Mathematical Concept:
    ---------------------
    We use the dot product formula to find the angle between two vectors:

        cos(θ) = (A · B) / (|A| * |B|)

    Where:
    - A is the vector from vertex to point1
    - B is the vector from vertex to point2
    - θ is the angle between them

    Args:
        point1: First point coordinates [x, y]
        vertex: Middle point (vertex of angle) [x, y]
        point2: Third point coordinates [x, y]

    Returns:
        Angle in degrees (0-180)

    Example:
        For knee angle: point1=hip, vertex=knee, point2=ankle
        - 180° = fully extended leg
        - 90° = bent at right angle
    """
    # Create vectors from vertex to each point
    vector1 = point1 - vertex
    vector2 = point2 - vertex

    # Calculate dot product: A · B = |A||B|cos(θ)
    dot_product = np.dot(vector1, vector2)

    # Calculate magnitudes (lengths) of vectors
    magnitude1 = np.linalg.norm(vector1)
    magnitude2 = np.linalg.norm(vector2)

    # Avoid division by zero
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    # Calculate cosine of angle
    cos_angle = dot_product / (magnitude1 * magnitude2)

    # Clamp to [-1, 1] to handle floating point errors
    cos_angle = np.clip(cos_angle, -1.0, 1.0)

    # Convert to degrees
    angle = np.degrees(np.arccos(cos_angle))

    return angle


def extract_keypoint(keypoints: np.ndarray, index: int) -> Optional[np.ndarray]:
    """
    Safely extract a keypoint from the YOLO pose output.

    YOLO Pose Output Format:
    ------------------------
    keypoints shape: (num_persons, 17, 3) where:
    - 17 is the number of body keypoints
    - 3 is [x, y, confidence]

    Confidence Interpretation:
    - > 0.5: High confidence, keypoint is clearly visible
    - 0.25-0.5: Medium confidence, may be partially occluded
    - < 0.25: Low confidence, likely occluded or not detected

    Args:
        keypoints: Array of keypoint coordinates and confidences
        index: Keypoint index (0-16)

    Returns:
        [x, y] coordinates if confidence > 0.3, else None
    """
    if keypoints is None or len(keypoints) == 0:
        return None

    # Get keypoint data [x, y, confidence]
    kp = keypoints[index]

    # Check confidence threshold
    if len(kp) >= 3 and kp[2] < 0.3:
        return None

    return np.array([kp[0], kp[1]])


def get_angle_from_keypoints(keypoints: np.ndarray, indices: List[int]) -> Optional[float]:
    """
    Calculate angle from three keypoint indices.

    Args:
        keypoints: Full keypoint array from YOLO
        indices: [point1_idx, vertex_idx, point2_idx]

    Returns:
        Calculated angle or None if keypoints not detected
    """
    if len(indices) != 3:
        return None

    point1 = extract_keypoint(keypoints, indices[0])
    vertex = extract_keypoint(keypoints, indices[1])
    point2 = extract_keypoint(keypoints, indices[2])

    if point1 is None or vertex is None or point2 is None:
        return None

    return calculate_angle(point1, vertex, point2)


# =============================================================================
# EXERCISE STATE MACHINE
# =============================================================================

class ExerciseTracker:
    """
    State machine for tracking exercise repetitions and form.

    State Machine Logic:
    --------------------
    The tracker monitors the joint angle and counts reps based on
    transitions between "up" (extended) and "down" (flexed) states.

    State Transitions:
               angle >= up_threshold
        DOWN ─────────────────────────> UP
          ^                              │
          │   angle <= down_threshold    │
          └──────────────────────────────┘

    A complete rep is counted when transitioning from UP back to DOWN.

    Form Quality Calculation:
    -------------------------
    Form score is based on:
    1. Reaching target angles (both up and down)
    2. Smooth, controlled movement
    3. Consistent range of motion across reps
    """

    def __init__(self, config: ExerciseConfig, fps: float = 30.0):
        self.config = config
        self.fps = fps

        # State tracking
        self.current_state = "neutral"   # "up", "down", "idle", "neutral"
        self.last_peak_state = "neutral" # last definitive "up" or "down" (ignores idle)
        self.rep_count = 0

        # Angle tracking for current rep
        self.angles_this_rep: List[float] = []
        self.frame_count_this_rep = 0

        # Session-wide tracking
        self.all_angles: List[float] = []
        self.rep_durations: List[float] = []
        self.form_scores: List[float] = []
        self.rep_roms: List[float] = []

        # Min/max for current rep
        self.current_rep_min = float('inf')
        self.current_rep_max = float('-inf')

        # Partial rep detection — minimum ROM (degrees) to count as an attempt
        self.partial_rep_min_rom = 10.0
        self.partial_rep_pending = False  # True when user entered idle zone

        # Smooth angle tracking (reduce noise)
        self.angle_buffer = deque(maxlen=5)

        # Rep timing
        self.rep_start_frame = 0
        self.total_frames = 0

        # Session data
        self.session = ExerciseSession(
            exercise_name=config.name,
            start_time=datetime.now().isoformat(),
            target_reps=config.target_reps
        )

    def get_smoothed_angle(self, raw_angle: float) -> float:
        """
        Apply moving average smoothing to reduce noise in angle measurements.

        Why Smoothing Matters:
        ----------------------
        Raw pose estimation can be noisy due to:
        - Video compression artifacts
        - Motion blur
        - Lighting changes
        - Partial occlusions

        A 5-frame moving average smooths these fluctuations while
        maintaining responsiveness to actual movement.
        """
        self.angle_buffer.append(raw_angle)
        return np.mean(self.angle_buffer)

    def update(self, raw_angle: Optional[float]) -> Dict[str, Any]:
        """
        Update the exercise tracker with a new angle measurement.

        Returns a dictionary with current metrics for display.
        """
        self.total_frames += 1

        if raw_angle is None:
            return self._get_current_metrics("No keypoints detected")

        angle = self.get_smoothed_angle(raw_angle)
        self.all_angles.append(angle)
        self.angles_this_rep.append(angle)
        self.frame_count_this_rep += 1

        # Update min/max for current rep
        self.current_rep_min = min(self.current_rep_min, angle)
        self.current_rep_max = max(self.current_rep_max, angle)

        # Determine thresholds (handle exercises where up > down or down > up)
        up_threshold = self.config.up_angle
        down_threshold = self.config.down_angle
        tolerance = self.config.form_tolerance

        # Check if this exercise goes from low angle to high (like shoulder flexion)
        # or high angle to low (like knee extension from bent to straight)
        ascending = up_threshold > down_threshold

        feedback = ""
        prev_state = self.current_state

        if ascending:
            # Exercise like shoulder flexion: starts low, goes high
            if angle >= up_threshold - tolerance:
                if self.last_peak_state == "down":
                    feedback = "Good extension!"
                self.current_state = "up"
                self.last_peak_state = "up"
                self.partial_rep_pending = False
            elif angle <= down_threshold + tolerance:
                if self.last_peak_state == "up":
                    # Completed a rep (went up and came back down)
                    self._complete_rep()
                    feedback = f"Rep {self.rep_count} complete!"
                elif self.partial_rep_pending and prev_state == "idle":
                    # Returned to start without reaching opposite threshold
                    self._record_partial_rep("reversed_early")
                self.current_state = "down"
                self.last_peak_state = "down"
                self.partial_rep_pending = False
            else:
                # Mid-movement — neither threshold reached yet
                self.current_state = "idle"
                self.partial_rep_pending = True
        else:
            # Exercise like squats: starts high (standing), goes low
            if angle <= up_threshold + tolerance:
                if self.last_peak_state == "down":
                    # Completed a rep (went down and came back up)
                    self._complete_rep()
                    feedback = f"Rep {self.rep_count} complete!"
                elif self.partial_rep_pending and prev_state == "idle":
                    # Returned to start without reaching opposite threshold
                    self._record_partial_rep("reversed_early")
                self.current_state = "up"
                self.last_peak_state = "up"
                self.partial_rep_pending = False
            elif angle >= down_threshold - tolerance:
                if self.last_peak_state == "up":
                    feedback = "Good depth!"
                self.current_state = "down"
                self.last_peak_state = "down"
                self.partial_rep_pending = False
            else:
                # Mid-movement — neither threshold reached yet
                self.current_state = "idle"
                self.partial_rep_pending = True

        # Form warnings
        warnings = self._check_form(angle)

        return self._get_current_metrics(feedback, warnings)

    def _complete_rep(self):
        """Record completion of a repetition."""
        self.rep_count += 1

        # Calculate rep metrics
        rom = self.current_rep_max - self.current_rep_min
        duration = self.frame_count_this_rep / self.fps if self.fps > 0 else 0
        form_score = self._calculate_form_score()

        # Store rep data
        rep_metrics = RepMetrics(
            rep_number=self.rep_count,
            min_angle=round(self.current_rep_min, 1),
            max_angle=round(self.current_rep_max, 1),
            rom=round(rom, 1),
            duration_seconds=round(duration, 2),
            form_score=round(form_score, 1),
            timestamp=datetime.now().isoformat()
        )
        self.session.rep_metrics.append(rep_metrics)

        # Update session aggregates
        self.rep_durations.append(duration)
        self.form_scores.append(form_score)
        self.rep_roms.append(rom)

        # Reset for next rep
        self._reset_rep_tracking()

    def _record_partial_rep(self, reason: str = "reversed_early"):
        """Record a partial/incomplete repetition attempt."""
        rom = self.current_rep_max - self.current_rep_min
        if rom < self.partial_rep_min_rom:
            # Too little movement to count even as a partial rep
            self._reset_rep_tracking()
            return

        duration = self.frame_count_this_rep / self.fps if self.fps > 0 else 0

        partial = PartialRepMetrics(
            exercise=self.config.name,
            min_angle=round(self.current_rep_min, 1),
            max_angle=round(self.current_rep_max, 1),
            rom=round(rom, 1),
            duration_seconds=round(duration, 2),
            reason=reason,
            timestamp=datetime.now().isoformat(),
        )
        self.session.partial_rep_metrics.append(partial)

        # Reset for next rep
        self._reset_rep_tracking()

    def _reset_rep_tracking(self):
        """Reset angle/frame tracking for the next rep attempt."""
        self.angles_this_rep = []
        self.frame_count_this_rep = 0
        self.current_rep_min = float('inf')
        self.current_rep_max = float('-inf')

    def _calculate_form_score(self) -> float:
        """
        Calculate form quality score for the current rep.

        Scoring Criteria:
        -----------------
        1. ROM Achievement (40%): Did the person reach target angles?
        2. Smoothness (30%): Was the movement controlled without jerks?
        3. Symmetry (30%): Was the up and down phase balanced?

        Returns score 0-100
        """
        if len(self.angles_this_rep) < 2:
            return 50.0  # Default score if not enough data

        score = 0.0

        # 1. ROM Achievement (40 points)
        target_rom = abs(self.config.up_angle - self.config.down_angle)
        actual_rom = self.current_rep_max - self.current_rep_min
        rom_ratio = min(actual_rom / target_rom, 1.0) if target_rom > 0 else 0
        score += rom_ratio * 40

        # 2. Smoothness (30 points) - measured by angle change variance
        if len(self.angles_this_rep) > 2:
            angle_changes = np.diff(self.angles_this_rep)
            smoothness = 1.0 / (1.0 + np.std(angle_changes))
            score += min(smoothness * 30, 30)
        else:
            score += 15  # Default if not enough data

        # 3. Phase symmetry (30 points) - balanced up/down timing
        angles = np.array(self.angles_this_rep)
        mid_angle = (self.current_rep_min + self.current_rep_max) / 2

        # Count frames above and below midpoint
        frames_above = np.sum(angles > mid_angle)
        frames_below = np.sum(angles <= mid_angle)
        total_frames = len(angles)

        if total_frames > 0:
            symmetry = 1.0 - abs(frames_above - frames_below) / total_frames
            score += symmetry * 30
        else:
            score += 15

        return min(score, 100.0)

    def _check_form(self, angle: float) -> List[str]:
        """Check for form issues and generate warnings."""
        warnings = []

        # Check if angle is way outside expected range
        min_expected = min(self.config.up_angle, self.config.down_angle) - 20
        max_expected = max(self.config.up_angle, self.config.down_angle) + 20

        if angle < min_expected:
            warnings.append("Angle too low - check form")
        elif angle > max_expected:
            warnings.append("Angle too high - check form")

        # Check for inconsistent ROM across reps
        if len(self.rep_roms) >= 2:
            avg_rom = np.mean(self.rep_roms)
            current_rom = self.current_rep_max - self.current_rep_min
            if current_rom < avg_rom * 0.7:
                warnings.append("Reduced range of motion")

        return warnings

    def _get_current_metrics(self, feedback: str = "", warnings: List[str] = None) -> Dict[str, Any]:
        """Package current metrics for display."""
        current_angle = self.angle_buffer[-1] if self.angle_buffer else 0

        return {
            "exercise": self.config.name,
            "rep_count": self.rep_count,
            "target_reps": self.config.target_reps,
            "current_angle": round(current_angle, 1),
            "state": self.current_state,
            "current_rep_min": round(self.current_rep_min, 1) if self.current_rep_min != float('inf') else 0,
            "current_rep_max": round(self.current_rep_max, 1) if self.current_rep_max != float('-inf') else 0,
            "avg_form_score": round(np.mean(self.form_scores), 1) if self.form_scores else 0,
            "feedback": feedback,
            "warnings": warnings or []
        }

    def finalize_session(self) -> ExerciseSession:
        """Finalize and return session data."""
        self.session.end_time = datetime.now().isoformat()
        self.session.total_reps = self.rep_count

        if self.rep_roms:
            self.session.avg_rom = round(np.mean(self.rep_roms), 1)
            self.session.max_rom = round(max(self.rep_roms), 1)

        if self.form_scores:
            self.session.avg_form_score = round(np.mean(self.form_scores), 1)

        if len(self.rep_durations) > 1:
            self.session.tempo_consistency = round(np.std(self.rep_durations), 2)

        return self.session


# =============================================================================
# VIDEO ANNOTATION FUNCTIONS
# =============================================================================

def draw_metrics_panel(frame: np.ndarray, metrics: Dict[str, Any],
                       panel_width: int = 300) -> np.ndarray:
    """
    Draw a metrics panel overlay on the frame.

    Visual Design:
    --------------
    - Semi-transparent dark background for readability
    - Color-coded metrics (green=good, yellow=warning, red=alert)
    - Large rep counter for visibility at distance
    """
    height, width = frame.shape[:2]

    # Create semi-transparent overlay
    overlay = frame.copy()
    cv2.rectangle(overlay, (width - panel_width, 0), (width, height), (40, 40, 40), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    # Starting position for text
    x = width - panel_width + 15
    y = 40
    line_height = 35

    # Colors
    white = (255, 255, 255)
    green = (0, 255, 0)
    yellow = (0, 255, 255)
    red = (0, 0, 255)
    cyan = (255, 255, 0)

    # Title
    cv2.putText(frame, metrics.get("exercise", "Exercise"), (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, cyan, 2)
    y += line_height + 10

    # Rep counter (large)
    rep_text = f"Reps: {metrics.get('rep_count', 0)}/{metrics.get('target_reps', 0)}"
    cv2.putText(frame, rep_text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, green, 2)
    y += line_height + 5

    # Current angle
    angle = metrics.get('current_angle', 0)
    cv2.putText(frame, f"Angle: {angle:.1f}", (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, white, 2)
    y += line_height

    # State indicator
    state = metrics.get('state', 'neutral')
    orange = (0, 165, 255)
    state_color = (green if state == "up" else
                   yellow if state == "down" else
                   orange if state == "idle" else white)
    cv2.putText(frame, f"Phase: {state.upper()}", (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, state_color, 2)
    y += line_height

    # ROM this rep
    rom_min = metrics.get('current_rep_min', 0)
    rom_max = metrics.get('current_rep_max', 0)
    if rom_min > 0 or rom_max > 0:
        cv2.putText(frame, f"ROM: {rom_min:.0f} - {rom_max:.0f}", (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, white, 1)
        y += line_height

    # Form score
    form_score = metrics.get('avg_form_score', 0)
    score_color = green if form_score >= 80 else (yellow if form_score >= 60 else red)
    cv2.putText(frame, f"Form: {form_score:.0f}%", (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, score_color, 2)
    y += line_height

    # Form status from FormAnalyzer
    if 'form_status' in metrics:
        status = metrics['form_status']
        status_colors = {
            'excellent': green, 'good': green,
            'warning': yellow, 'poor': red, 'stop': (0, 0, 255)
        }
        s_color = status_colors.get(status, white)
        cv2.putText(frame, f"Status: {status.upper()}", (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, s_color, 2)
        y += 28

    # Form feedback messages from FormAnalyzer
    for msg in metrics.get('form_messages', []):
        msg_disp = (msg[:25] + "..") if len(msg) > 27 else msg
        cv2.putText(frame, msg_disp, (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, yellow, 1)
        y += 20

    y += 5

    # Rep feedback
    feedback = metrics.get('feedback', '')
    if feedback:
        cv2.putText(frame, feedback, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, green, 1)
        y += line_height

    # Warnings
    for warning in metrics.get('warnings', []):
        cv2.putText(frame, f"! {warning}", (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, red, 1)
        y += 25

    return frame


def draw_angle_visualization(frame: np.ndarray, keypoints: np.ndarray,
                             indices: List[int], angle: float) -> np.ndarray:
    """
    Draw angle arc and value at the joint.

    Visualization:
    --------------
    - Lines connecting the three keypoints
    - Arc showing the measured angle
    - Angle value text at the vertex
    """
    if keypoints is None:
        return frame

    point1 = extract_keypoint(keypoints, indices[0])
    vertex = extract_keypoint(keypoints, indices[1])
    point2 = extract_keypoint(keypoints, indices[2])

    if point1 is None or vertex is None or point2 is None:
        return frame

    # Convert to integer coordinates
    p1 = tuple(point1.astype(int))
    v = tuple(vertex.astype(int))
    p2 = tuple(point2.astype(int))

    # Draw lines
    cv2.line(frame, v, p1, (0, 255, 255), 3)
    cv2.line(frame, v, p2, (0, 255, 255), 3)

    # Draw points
    cv2.circle(frame, p1, 8, (255, 0, 0), -1)
    cv2.circle(frame, v, 10, (0, 255, 0), -1)
    cv2.circle(frame, p2, 8, (255, 0, 0), -1)

    # Draw angle arc
    radius = 40

    # Calculate angles for arc
    angle1 = np.arctan2(point1[1] - vertex[1], point1[0] - vertex[0])
    angle2 = np.arctan2(point2[1] - vertex[1], point2[0] - vertex[0])

    start_angle = np.degrees(min(angle1, angle2))
    end_angle = np.degrees(max(angle1, angle2))

    cv2.ellipse(frame, v, (radius, radius), 0, start_angle, end_angle, (0, 255, 0), 2)

    # Draw angle text
    text_pos = (v[0] + 15, v[1] - 15)
    cv2.putText(frame, f"{angle:.1f}", text_pos,
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    return frame


# =============================================================================
# CONFIGURATION LOADING
# =============================================================================

def load_config(config_path: str = "config.yaml") -> Dict[str, ExerciseConfig]:
    """Load exercise configurations from YAML file."""
    config_file = Path(config_path)

    if not config_file.exists():
        print(f"Config file not found: {config_path}")
        print("Using default configurations...")
        return get_default_configs()

    with open(config_file, 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)

    exercises = {}
    for name, data in config_data.get('exercises', {}).items():
        exercises[name] = ExerciseConfig(
            name=data.get('display_name', name),
            keypoints=data.get('keypoints', []),
            up_angle=data.get('up_angle', 170),
            down_angle=data.get('down_angle', 90),
            form_tolerance=data.get('form_tolerance', 15),
            target_reps=data.get('target_reps', 10),
            side=data.get('side', 'left')
        )

    return exercises


def get_default_configs() -> Dict[str, ExerciseConfig]:
    """Return default exercise configurations."""
    return {
        "knee_extension": ExerciseConfig(
            name="Knee Extension",
            keypoints=[11, 13, 15],  # hip-knee-ankle (left)
            up_angle=170,    # Extended
            down_angle=90,   # Bent
            form_tolerance=15,
            target_reps=10
        ),
        "shoulder_flexion": ExerciseConfig(
            name="Shoulder Flexion",
            keypoints=[11, 5, 7],  # hip-shoulder-elbow for arm raise
            up_angle=170,    # Arm raised
            down_angle=20,   # Arm at side
            form_tolerance=15,
            target_reps=10
        ),
        "squat": ExerciseConfig(
            name="Squat",
            keypoints=[11, 13, 15],  # hip-knee-ankle
            up_angle=170,    # Standing
            down_angle=90,   # Squat depth
            form_tolerance=15,
            target_reps=10
        ),
        "hip_abduction": ExerciseConfig(
            name="Hip Abduction",
            keypoints=[12, 11, 13],  # right hip - left hip - left knee
            up_angle=45,     # Abducted
            down_angle=10,   # At rest
            form_tolerance=10,
            target_reps=10
        )
    }


# =============================================================================
# MAIN ANALYSIS FUNCTIONS
# =============================================================================

def _open_recording(patient_id: Optional[str]):
    """Open the canonical record and validate the patient before any heavy work."""
    patient_id = patient_id or "unassigned"
    store = SessionStore(default_db_path()).open()
    if store.get_patient(patient_id) is None:
        store.close()
        raise PatientNotFoundError(f"Patient '{patient_id}' not found")
    return store, patient_id


def _close_recording(recorder, store, session, patient_id: str) -> None:
    """End the canonical record for a finished session and report the outcome."""
    try:
        recorder.end(session)
        print(f"\nSession {recorder.session_id} saved for patient {patient_id} ({session.total_reps} reps)")
    except Exception as e:
        print(f"Warning: session record could not be fully saved: {e}")
    finally:
        store.close()


def main(video_path: str, exercise_name: str = "knee_extension",
         output_path: Optional[str] = None, config_path: str = "config.yaml",
         model_path: str = "models/yolo11m-pose.pt", show_video: bool = True,
         patient_id: Optional[str] = None) -> ExerciseSession:
    """
    Process a video file for PT exercise analysis.

    This is the primary analysis function that:
    1. Loads the YOLO pose model
    2. Processes each frame for pose estimation
    3. Tracks exercise metrics in real-time
    4. Generates annotated output video
    5. Returns complete session data

    Args:
        video_path: Path to input video file
        exercise_name: Name of exercise to track (from config)
        output_path: Path for annotated output video (optional)
        config_path: Path to configuration YAML
        model_path: Path to YOLO pose model
        show_video: Whether to display video during processing
        patient_id: Pseudonymous patient ID for the canonical record (None -> "unassigned")

    Returns:
        ExerciseSession with complete metrics
    """
    # Load configuration
    exercises = load_config(config_path)
    if exercise_name not in exercises:
        print(f"Exercise '{exercise_name}' not found. Available: {list(exercises.keys())}")
        exercise_name = list(exercises.keys())[0]

    exercise_config = exercises[exercise_name]
    print(f"\n{'='*60}")
    print(f"AI Physical Therapy Assistant")
    print(f"{'='*60}")
    print(f"Exercise: {exercise_config.name}")
    print(f"Keypoints: {exercise_config.keypoints}")
    print(f"Target angles: {exercise_config.down_angle}° - {exercise_config.up_angle}°")
    print(f"Target reps: {exercise_config.target_reps}")
    print(f"{'='*60}\n")

    # Canonical record: validate the patient before loading the model
    store, patient_id = _open_recording(patient_id)

    # Load YOLO model
    print("Loading YOLO pose model...")
    model = YOLO(model_path)

    # Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    # Get video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Video: {width}x{height} @ {fps:.1f} FPS, {total_frames} frames")

    # Initialize tracker
    tracker = ExerciseTracker(exercise_config, fps)

    # Canonical session record (single writer; replaces the legacy loggers)
    recorder = SessionRecorder(store)
    recorder.start(patient_id, "video", Path(video_path).name, exercise_config,
                   exercise_key=exercise_name)

    # Setup video writer if output path specified
    writer = None
    if output_path:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    frame_num = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_num += 1

            # Run pose estimation
            results = model(frame, verbose=False)

            # Extract keypoints (first person detected)
            keypoints = None
            if results and len(results) > 0:
                result = results[0]
                if result.keypoints is not None and len(result.keypoints) > 0:
                    # Get keypoints for first detected person
                    keypoints = result.keypoints.data[0].cpu().numpy()

            # Calculate angle for the exercise
            angle = None
            if keypoints is not None:
                angle = get_angle_from_keypoints(keypoints, exercise_config.keypoints)

            # Update tracker
            metrics = tracker.update(angle)

            # Canonical record: reps, partial reps, angle samples
            recorder.observe(tracker, metrics, angle, frame_num, None)

            # Draw skeleton from YOLO results
            annotated_frame = results[0].plot() if results else frame.copy()

            # Draw angle visualization
            if keypoints is not None and angle is not None:
                annotated_frame = draw_angle_visualization(
                    annotated_frame, keypoints, exercise_config.keypoints, angle
                )

            # Draw metrics panel
            annotated_frame = draw_metrics_panel(annotated_frame, metrics)

            # Progress indicator
            if frame_num % 30 == 0:
                progress = (frame_num / total_frames) * 100
                print(f"\rProgress: {progress:.1f}% | Reps: {metrics['rep_count']}", end="")

            # Write output frame
            if writer:
                writer.write(annotated_frame)

            # Display
            if show_video:
                cv2.imshow("PT Assistant", annotated_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("\nStopped by user")
                    break
                elif key == ord('p'):
                    cv2.waitKey(0)  # Pause

    finally:
        cap.release()
        if writer:
            writer.release()
        cv2.destroyAllWindows()

        # Finalize session and save the canonical record — must run even on exception
        try:
            session = tracker.finalize_session()
        except Exception as e:
            print(f"Warning: session finalization error: {e}")
            session = tracker.session
        _close_recording(recorder, store, session, patient_id)

    print(f"\n\n{'='*60}")
    print("Session Complete!")
    print(f"{'='*60}")
    print(f"Total Reps: {session.total_reps}/{session.target_reps}")
    print(f"Average ROM: {session.avg_rom}°")
    print(f"Maximum ROM: {session.max_rom}°")
    print(f"Average Form Score: {session.avg_form_score}%")
    print(f"Tempo Consistency (σ): {session.tempo_consistency}s")
    print(f"{'='*60}\n")

    return session


def analyze_single_frame(image_path: str, exercise_name: str = "knee_extension",
                         config_path: str = "config.yaml",
                         model_path: str = "models/yolo11m-pose.pt") -> Dict[str, Any]:
    """
    Analyze a single image for pose and angles.

    Useful for:
    - Testing pose detection on still images
    - Assessing starting/ending positions
    - Debugging keypoint detection

    Args:
        image_path: Path to image file
        exercise_name: Exercise to analyze
        config_path: Path to configuration
        model_path: Path to YOLO model

    Returns:
        Dictionary with angle measurements and visualization
    """
    # Load configuration
    exercises = load_config(config_path)
    exercise_config = exercises.get(exercise_name, list(exercises.values())[0])

    # Load model and image
    model = YOLO(model_path)
    image = cv2.imread(image_path)

    if image is None:
        raise ValueError(f"Could not load image: {image_path}")

    # Run inference
    results = model(image, verbose=False)

    # Extract keypoints
    keypoints = None
    if results and len(results) > 0 and results[0].keypoints is not None:
        keypoints = results[0].keypoints.data[0].cpu().numpy()

    # Calculate angle
    angle = None
    if keypoints is not None:
        angle = get_angle_from_keypoints(keypoints, exercise_config.keypoints)

    # Annotate image
    annotated = results[0].plot() if results else image.copy()

    if keypoints is not None and angle is not None:
        annotated = draw_angle_visualization(
            annotated, keypoints, exercise_config.keypoints, angle
        )

    # Add info text
    cv2.putText(annotated, f"Exercise: {exercise_config.name}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(annotated, f"Angle: {angle:.1f}" if angle else "No pose detected",
                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    # Save annotated image to output directory
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / (Path(image_path).stem + "_analyzed.jpg"))
    cv2.imwrite(output_path, annotated)
    print(f"Saved annotated image: {output_path}")

    # Display
    cv2.imshow("Single Frame Analysis", annotated)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    return {
        "image_path": image_path,
        "exercise": exercise_config.name,
        "angle": angle,
        "keypoints_detected": keypoints is not None,
        "output_path": output_path
    }


def analyze_webcam(exercise_name: str = "knee_extension",
                   config_path: str = "config.yaml",
                   model_path: str = "models/yolo11m-pose.pt",
                   camera_id: int = 0,
                   record_output: Optional[str] = None,
                   frame_skip: int = 1,
                   imgsz: int = 320,
                   patient_id: Optional[str] = None) -> ExerciseSession:
    """
    Real-time PT session monitoring using webcam.

    Controls:
    - 'q': Quit
    - 'r': Reset rep counter
    - 'p': Pause/Resume
    - 's': Save current frame
    - 'n': Next exercise (cycles through available)

    Args:
        exercise_name: Initial exercise to track
        config_path: Path to configuration
        model_path: Path to YOLO model
        camera_id: Camera device ID (0 for default)
        record_output: Optional path to save recording

    Returns:
        ExerciseSession with session metrics
    """
    # Load configuration
    exercises = load_config(config_path)
    exercise_names = list(exercises.keys())
    current_exercise_idx = exercise_names.index(exercise_name) if exercise_name in exercise_names else 0
    exercise_config = exercises[exercise_names[current_exercise_idx]]

    # Canonical record: validate the patient before loading the model
    store, patient_id = _open_recording(patient_id)

    # Load model
    print("Loading YOLO pose model...")
    model = YOLO(model_path)

    # Open webcam
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        raise ValueError(f"Could not open camera {camera_id}")

    # Optimize camera settings for better framerate
    # Use MJPG codec for faster capture (less CPU overhead than raw)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

    # Set resolution (lower = faster). 720p is good balance.
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    # Request 30 FPS from camera
    cap.set(cv2.CAP_PROP_FPS, 30)

    # Reduce buffer size to minimize latency (get most recent frame)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"\n{'='*60}")
    print(f"PT Assistant - Webcam Mode")
    print(f"{'='*60}")
    print(f"Camera: {width}x{height} @ {fps:.1f} FPS")
    print(f"Exercise: {exercise_config.name}")
    print(f"\nControls:")
    print(f"  q - Quit")
    print(f"  r - Reset reps")
    print(f"  p - Pause/Resume")
    print(f"  n - Next exercise")
    print(f"  s - Save frame")
    print(f"{'='*60}\n")

    # Initialize tracker
    tracker = ExerciseTracker(exercise_config, fps)

    # FormAnalyzer for detailed pose-based form assessment
    base_exercise = exercise_name.replace('_right', '').replace('_left', '')
    form_analyzer = FormAnalyzer(base_exercise)
    frame_num = 0
    last_keypoints = None
    last_angle = None
    last_assessment = None

    # Canonical session record (single writer; replaces the legacy loggers)
    recorder = SessionRecorder(store)
    recorder.start(patient_id, "webcam", str(camera_id), exercise_config,
                   exercise_key=exercise_names[current_exercise_idx],
                   extras={"camera_id": camera_id, "imgsz": imgsz, "frame_skip": frame_skip})

    # Setup recording
    writer = None
    if record_output:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(record_output, fourcc, fps, (width, height))

    paused = False

    try:
        while True:
            if not paused:
                ret, frame = cap.read()
                if not ret:
                    print("Failed to grab frame")
                    break

                frame_num += 1
                run_inference = (frame_num % frame_skip == 0) or (last_keypoints is None)

                if run_inference:
                    # Run pose estimation at reduced image size for speed
                    results = model(frame, imgsz=imgsz, verbose=False)

                    # Extract keypoints
                    keypoints = None
                    if results and len(results) > 0 and results[0].keypoints is not None:
                        if len(results[0].keypoints) > 0:
                            keypoints = results[0].keypoints.data[0].cpu().numpy()

                    last_keypoints = keypoints
                    angle = get_angle_from_keypoints(keypoints, exercise_config.keypoints) if keypoints is not None else None
                    last_angle = angle

                    # Run form analysis on detected keypoints
                    if keypoints is not None:
                        last_assessment = form_analyzer.analyze_frame(keypoints, frame_num)

                    # Draw skeleton from YOLO results
                    annotated_frame = results[0].plot() if results else frame.copy()
                else:
                    # Skipped frame — use current raw frame, reuse last keypoints/angle
                    keypoints = last_keypoints
                    angle = last_angle
                    annotated_frame = frame.copy()

                # Always draw angle visualization using last known data
                if last_keypoints is not None and last_angle is not None:
                    annotated_frame = draw_angle_visualization(
                        annotated_frame, last_keypoints, exercise_config.keypoints, last_angle
                    )

                # Update tracker
                metrics = tracker.update(angle)

                # Attach form assessment data to metrics dict
                if last_assessment is not None:
                    metrics['form_status'] = last_assessment.status.value
                    metrics['form_messages'] = [f.message for f in last_assessment.feedback_messages[:2]]

                # Canonical record: reps, partial reps, form events, angle samples
                recorder.observe(tracker, metrics, angle, frame_num, last_assessment)

                # Draw metrics panel
                annotated_frame = draw_metrics_panel(annotated_frame, metrics)

                # Recording indicator
                if writer:
                    cv2.circle(annotated_frame, (30, 30), 15, (0, 0, 255), -1)
                    cv2.putText(annotated_frame, "REC", (50, 38),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                # Write frame if recording
                if writer:
                    writer.write(annotated_frame)

            else:
                # Show paused indicator
                cv2.putText(annotated_frame, "PAUSED", (width//2 - 80, height//2),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 255), 3)

            # Display
            cv2.imshow("PT Assistant - Webcam", annotated_frame)

            # Handle key presses
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q'):
                break
            elif key == ord('r'):
                # Record an interrupted partial rep if mid-movement, then the reset
                tracker._record_partial_rep("interrupted")
                recorder.reset(tracker, frame_num)
                # Reset tracker and form analyzer
                tracker = ExerciseTracker(exercise_config, fps)
                form_analyzer.reset()
                last_keypoints = None
                last_angle = None
                last_assessment = None
                print("Rep counter reset")
            elif key == ord('p'):
                paused = not paused
                print("Paused" if paused else "Resumed")
            elif key == ord('n'):
                # Record an interrupted partial rep if mid-movement
                tracker._record_partial_rep("interrupted")
                # Switch to next exercise
                current_exercise_idx = (current_exercise_idx + 1) % len(exercise_names)
                exercise_config = exercises[exercise_names[current_exercise_idx]]
                recorder.switch(exercise_config, tracker, frame_num,
                                exercise_key=exercise_names[current_exercise_idx])
                tracker = ExerciseTracker(exercise_config, fps)
                base_exercise = exercise_names[current_exercise_idx].replace('_right', '').replace('_left', '')
                form_analyzer = FormAnalyzer(base_exercise)
                last_keypoints = None
                last_angle = None
                last_assessment = None
                print(f"Switched to: {exercise_config.name}")
            elif key == ord('s'):
                # Save current frame
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                frame_path = f"pt_frame_{timestamp}.jpg"
                cv2.imwrite(frame_path, annotated_frame)
                print(f"Saved: {frame_path}")

    finally:
        cap.release()
        if writer:
            writer.release()
        cv2.destroyAllWindows()

        # Finalize session and save the canonical record — must run even if the
        # loop exited via an exception so the record is left in a valid state.
        try:
            session = tracker.finalize_session()
        except Exception as e:
            print(f"Warning: session finalization error: {e}")
            session = tracker.session
        _close_recording(recorder, store, session, patient_id)

    return session

# =============================================================================
# ALTERNATIVE: USING ULTRALYTICS AIGYM SOLUTION
# =============================================================================

def analyze_with_aigym(video_path: str, exercise_type: str = "pushup",
                       output_path: Optional[str] = None) -> None:
    """
    Alternative analysis using Ultralytics' built-in AIGym solution.

    This uses the official Ultralytics solution which provides:
    - Automatic rep counting
    - Built-in exercise types (pushup, pullup, abworkout)

    Note: This is simpler but less customizable than our main() function.
    For PT-specific exercises with custom angle ranges, use main() instead.

    Args:
        video_path: Path to input video
        exercise_type: "pushup", "pullup", or "abworkout"
        output_path: Optional output video path
    """
    # Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    # Get video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Setup video writer
    writer = None
    if output_path:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    # Initialize AIGym
    # Keypoint indices depend on exercise type
    if exercise_type == "pushup":
        kpts = [6, 8, 10]  # shoulder-elbow-wrist (right side)
    elif exercise_type == "pullup":
        kpts = [6, 8, 10]
    elif exercise_type == "abworkout":
        kpts = [6, 12, 14]  # shoulder-hip-knee
    else:
        kpts = [6, 8, 10]  # default

    gym = AIGym(
        model="models/yolo11m-pose.pt",
        show=True,
        kpts=kpts
    )

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # Process frame with AIGym
            result_frame = gym(frame)

            if writer:
                writer.write(result_frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        cap.release()
        if writer:
            writer.release()
        cv2.destroyAllWindows()


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AI Physical Therapy Assistant - Pose Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a video file
  python analyze.py video --input session.mp4 --exercise knee_extension

  # Real-time webcam analysis
  python analyze.py webcam --exercise shoulder_flexion

  # Analyze single image
  python analyze.py image --input pose.jpg --exercise squat

  # Use AIGym for pushups
  python analyze.py aigym --input workout.mp4 --type pushup

  # Faster webcam on older machines: infer every 2nd frame at 320px
  python analyze.py webcam --exercise squat --skip-frames 2 --imgsz 320
        """
    )

    subparsers = parser.add_subparsers(dest="mode", help="Analysis mode")

    # Video mode
    video_parser = subparsers.add_parser("video", help="Analyze video file")
    video_parser.add_argument("--input", "-i", required=True, help="Input video path")
    video_parser.add_argument("--output", "-o", help="Output video path")
    video_parser.add_argument("--exercise", "-e", default="knee_extension",
                              help="Exercise name from config")
    video_parser.add_argument("--config", "-c", default="config.yaml", help="Config file")
    video_parser.add_argument("--model", "-m", default="models/yolo11m-pose.pt", help="YOLO model")
    video_parser.add_argument("--no-display", action="store_true", help="Don't show video")
    video_parser.add_argument("--patient", "-p", default=None,
                              help="Pseudonymous patient ID for the session record (default: unassigned)")

    # Webcam mode
    webcam_parser = subparsers.add_parser("webcam", help="Real-time webcam analysis")
    webcam_parser.add_argument("--exercise", "-e", default="knee_extension",
                               help="Initial exercise")
    webcam_parser.add_argument("--config", "-c", default="config.yaml", help="Config file")
    webcam_parser.add_argument("--model", "-m", default="models/yolo11m-pose.pt", help="YOLO model")
    webcam_parser.add_argument("--camera", type=int, default=0, help="Camera ID")
    webcam_parser.add_argument("--record", "-r", help="Record output to file")
    webcam_parser.add_argument("--skip-frames", type=int, default=1,
                               help="Run YOLO every Nth frame (1=all, 2=every other). Higher=faster but less smooth.")
    webcam_parser.add_argument("--imgsz", type=int, default=320,
                               help="YOLO inference image size (320=fast, 640=accurate). Default 320.")
    webcam_parser.add_argument("--patient", "-p", default=None,
                               help="Pseudonymous patient ID for the session record (default: unassigned)")

    # Image mode
    image_parser = subparsers.add_parser("image", help="Analyze single image")
    image_parser.add_argument("--input", "-i", required=True, help="Input image path")
    image_parser.add_argument("--exercise", "-e", default="knee_extension",
                              help="Exercise to analyze")
    image_parser.add_argument("--config", "-c", default="config.yaml", help="Config file")
    image_parser.add_argument("--model", "-m", default="models/yolo11m-pose.pt", help="YOLO model")

    # AIGym mode
    aigym_parser = subparsers.add_parser("aigym", help="Use Ultralytics AIGym")
    aigym_parser.add_argument("--input", "-i", required=True, help="Input video path")
    aigym_parser.add_argument("--output", "-o", help="Output video path")
    aigym_parser.add_argument("--type", "-t", default="pushup",
                              choices=["pushup", "pullup", "abworkout"],
                              help="Exercise type")

    args = parser.parse_args()

    if args.mode == "video":
        try:
            main(
                video_path=args.input,
                exercise_name=args.exercise,
                output_path=args.output,
                config_path=args.config,
                model_path=args.model,
                show_video=not args.no_display,
                patient_id=args.patient
            )
        except PatientNotFoundError:
            print(f"Patient '{args.patient}' not found. Register it with: patients add {args.patient}")
            raise SystemExit(1)

    elif args.mode == "webcam":
        try:
            analyze_webcam(
                exercise_name=args.exercise,
                config_path=args.config,
                model_path=args.model,
                camera_id=args.camera,
                record_output=args.record,
                frame_skip=args.skip_frames,
                imgsz=args.imgsz,
                patient_id=args.patient
            )
        except PatientNotFoundError:
            print(f"Patient '{args.patient}' not found. Register it with: patients add {args.patient}")
            raise SystemExit(1)

    elif args.mode == "image":
        analyze_single_frame(
            image_path=args.input,
            exercise_name=args.exercise,
            config_path=args.config,
            model_path=args.model
        )

    elif args.mode == "aigym":
        analyze_with_aigym(
            video_path=args.input,
            exercise_type=args.type,
            output_path=args.output
        )

    else:
        parser.print_help()
