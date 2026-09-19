"""
AI Physical Therapy Assistant
=============================

A comprehensive pose estimation system for monitoring physical therapy exercises
using Ultralytics YOLO11.

Modules:
    - analyze: Core video/image analysis with pose estimation
    - form_assessment: Biomechanical form checking and feedback
    - ptlog: The canonical session record (patients, sessions, events, exports)
    - session_summary: Clinical summary of one session
    - utils: Helper functions for angle calculation and visualization
"""

from .utils import calculate_angle, extract_keypoint, get_angle_from_keypoints

__version__ = "1.0.0"
__author__ = "AI PT Assistant"
