"""LiveSession: the engine-facing adapter behind the web app's live-session page (feature 004).

It runs, for frames delivered by a callback, the same per-frame steps as the command-line
webcam loop in analyze.py: infer -> joint angle -> ExerciseTracker.update -> FormAnalyzer ->
SessionRecorder.observe -> angle and panel drawing. It uses only the engine's public classes
and functions; analyze.py is not edited (constitution I). A parity test guards the two
runners against drift.
"""

from __future__ import annotations

import dataclasses
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import cv2
import numpy as np

from analyze import (ExerciseTracker, draw_angle_visualization, draw_metrics_panel,
                     get_angle_from_keypoints, load_config)
from src.form_assessment import FormAnalyzer
from src.ptlog.models import Session
from src.ptlog.privacy import validate_patient_id
from src.ptlog.recorder import SessionRecorder
from src.ptlog.store import SessionStore

UNASSIGNED = "unassigned"


def base_exercise(exercise_key: str) -> str:
    """The form analyzer's exercise type for a configuration key (as the command-line loop derives it)."""
    return exercise_key.replace("_right", "").replace("_left", "")


PANEL_DESIGN_HEIGHT = 720   # the engine's panel uses fixed pixel sizes laid out for a 720p frame


def _panel_at_design_size(frame: np.ndarray, metrics: Dict[str, Any]) -> np.ndarray:
    """Draw the engine's panel so it takes the same share of the picture at any stream resolution.

    Browser streams are often smaller than 720p (WebRTC lowers resolution under load); drawn
    directly, the fixed-size panel would cover half the frame and lose its last lines. Smaller
    frames are scaled up for drawing and back down, so the stream keeps its size."""
    height, width = frame.shape[:2]
    if height >= PANEL_DESIGN_HEIGHT:
        return draw_metrics_panel(frame, metrics)
    scale = PANEL_DESIGN_HEIGHT / height
    enlarged = cv2.resize(frame, (int(round(width * scale)), PANEL_DESIGN_HEIGHT), interpolation=cv2.INTER_LINEAR)
    enlarged = draw_metrics_panel(enlarged, metrics)
    return cv2.resize(enlarged, (width, height), interpolation=cv2.INTER_AREA)


class LiveSession:
    """One recorded live session. Every public method is safe to call from any thread."""

    def __init__(self, store: SessionStore, patient_id: Optional[str], exercise_key: str,
                 target_reps: Optional[int], source_ref: str,
                 infer: Callable[[np.ndarray], Any], fps: float = 30.0,
                 config_path: str = "config.yaml", imgsz: int = 320,
                 form_analyzer_factory: Optional[Callable[[str], Any]] = None, draw: bool = True,
                 clock: Callable[[], datetime] = datetime.now):
        self.store = store
        self.patient_id = patient_id or UNASSIGNED
        self.source_ref = str(source_ref)
        self.infer = infer
        self.fps = fps
        self.imgsz = imgsz
        self.draw = draw
        self.target_reps = int(target_reps) if target_reps else None
        self._analyzer_factory = form_analyzer_factory or FormAnalyzer
        self.exercises = load_config(config_path)
        self.exercise_key = exercise_key
        self.config = self._config_for(exercise_key)

        self.recorder = SessionRecorder(store, clock=clock)
        self.tracker = ExerciseTracker(self.config, fps)
        self.form_analyzer = self._analyzer_factory(base_exercise(exercise_key))
        self.frame_num = 0
        self.last_assessment = None
        self.metrics: Dict[str, Any] = {}
        self.last_frame: Optional[np.ndarray] = None
        self.ended = False
        self._started = False
        self._result: Optional[Session] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ helpers

    def _config_for(self, exercise_key: str):
        if exercise_key not in self.exercises:
            raise ValueError(f"Unknown exercise '{exercise_key}'")
        cfg = self.exercises[exercise_key]
        return dataclasses.replace(cfg, target_reps=self.target_reps) if self.target_reps else cfg

    @property
    def session_id(self) -> Optional[int]:
        return self.recorder.session_id if self._started else None

    @property
    def exercise_name(self) -> str:
        return self.config.name

    @property
    def error(self) -> Optional[str]:
        err = getattr(self.recorder, "_first_error", None)
        return str(err) if err is not None else None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> int:
        """Open the session and its first set. Idempotent. Raises PatientNotFoundError."""
        with self._lock:
            if not self._started:
                self.recorder.start(
                    self.patient_id, "webcam", self.source_ref, self.config, exercise_key=self.exercise_key,
                    extras={"camera_id": self.source_ref, "imgsz": self.imgsz, "frame_skip": 1,
                            "origin": "web", "pid": os.getpid()})
                self._started = True
            return self.recorder.session_id

    def process(self, frame: np.ndarray, frame_num: Optional[int] = None) -> np.ndarray:
        """Run the engine on one frame, record what happened, and return the annotated frame."""
        with self._lock:
            if not self._started or self.ended:
                return frame
            self.frame_num = int(frame_num) if frame_num is not None else self.frame_num + 1

            result = self.infer(frame)
            keypoints, plotted = result if isinstance(result, tuple) else (result, None)
            angle = get_angle_from_keypoints(keypoints, self.config.keypoints) if keypoints is not None else None
            if keypoints is not None:
                self.last_assessment = self.form_analyzer.analyze_frame(keypoints, self.frame_num)

            annotated = plotted if plotted is not None else frame.copy()
            if self.draw and keypoints is not None and angle is not None:
                annotated = draw_angle_visualization(annotated, keypoints, self.config.keypoints, angle)

            metrics = self.tracker.update(angle)
            if self.last_assessment is not None:
                metrics["form_status"] = self.last_assessment.status.value
                metrics["form_messages"] = [f.message for f in self.last_assessment.feedback_messages[:2]]

            self.recorder.observe(self.tracker, metrics, angle, self.frame_num, self.last_assessment)

            if self.draw:
                annotated = _panel_at_design_size(annotated, metrics)
            self.metrics = metrics
            self.last_frame = annotated
            return annotated

    def set_target_reps(self, target_reps: int) -> None:
        """Applies to sets opened from now on; the running set keeps its target."""
        with self._lock:
            self.target_reps = int(target_reps)

    def _active(self) -> bool:
        return self._started and not self.ended

    def _clear_frame_state(self) -> None:
        self.last_assessment = None
        self.metrics = {}

    def switch(self, exercise_key: str) -> None:
        """Like the command-line 'n' key: interrupted partial rep, switch event, new set and tracker."""
        with self._lock:
            if not self._active():
                return
            new_config = self._config_for(exercise_key)          # raises before anything is recorded
            self.tracker._record_partial_rep("interrupted")      # same call the command-line loop makes
            self.recorder.switch(new_config, self.tracker, self.frame_num, exercise_key=exercise_key)
            self.exercise_key, self.config = exercise_key, new_config
            self.tracker = ExerciseTracker(new_config, self.fps)
            self.form_analyzer = self._analyzer_factory(base_exercise(exercise_key))
            self._clear_frame_state()

    def reset(self) -> None:
        """Like the command-line 'r' key: interrupted partial rep, reset event, fresh counter, same set."""
        with self._lock:
            if not self._active():
                return
            self.tracker._record_partial_rep("interrupted")
            self.recorder.reset(self.tracker, self.frame_num)
            self.tracker = ExerciseTracker(self.config, self.fps)
            self.form_analyzer.reset()
            self._clear_frame_state()

    def end(self) -> Optional[Session]:
        """Finalize the tracker and end the recorded session. Idempotent."""
        with self._lock:
            if not self._started:
                return None
            if self.ended:
                return self._result
            self.ended = True
            try:
                engine_session = self.tracker.finalize_session()
            except Exception:  # noqa: BLE001 — a finalization error must not lose the record
                engine_session = self.tracker.session
            self._result = self.recorder.end(engine_session)
            return self._result


def save_screenshot(frame: Optional[np.ndarray], patient_id: Optional[str],
                    out_dir: Optional[Path] = None, now: Optional[datetime] = None) -> Path:
    """Write the annotated frame as `<pseudonymous id>_<YYYYMMDD_HHMMSS>.png` under the export location."""
    if frame is None:
        raise ValueError("No frame to save")
    from src.ptlog import exports
    pid = validate_patient_id(patient_id or UNASSIGNED)
    out = Path(out_dir) if out_dir else exports.default_export_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{pid}_{(now or datetime.now()):%Y%m%d_%H%M%S}.png"
    if not cv2.imwrite(str(path), frame):
        raise ValueError(f"Could not write {path}")
    return path
