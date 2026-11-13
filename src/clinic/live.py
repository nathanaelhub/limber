"""The therapist's live session (feature 019 slice 7, FR-013): the patient in the clinic, the therapist's browser
finding the body points with MoveNet, and the engine counting here, recorded under the chosen patient.

Modelled on the patient's home session (src/portal/live.py): the same frame contract, rate meter and lease, and
the same resume across connections that a host cuts (feature 020). Unlike it, the therapist chooses any exercise
and target, and can switch exercise, reset the count, or change the target mid-session. Sessions are browser-pose
measured, so they carry the `browser` origin (019 G2 decision) and never mix with the clinic model's numbers.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import numpy as np

from src.live_session import LiveSession
from src.portal import frames
from src.ptlog.models import PortalError
from src.ptlog.store import SessionStore

NOMINAL_FPS = 15
DEFAULT_POSE_MODEL = "movenet-lightning-4"
ORIGIN = "clinic-live"
MESSAGE_TYPES = ("start", "resume", "frame", "stop", "switch", "reset", "target")
_DUMMY_FRAME = np.zeros((1, 1, 3), dtype=np.uint8)


class LiveRefused(PortalError):
    MESSAGES = {
        "running": "A session is already being recorded for this patient. Stop it first.",
        "plan_archived": "This patient's plan of care is archived, so nothing new can be recorded.",
        "unknown_exercise": "Choose an exercise.",
        "not_resumable": "That session can't be continued. Start a new one.",
    }

    def __init__(self, reason: str):
        super().__init__(self.MESSAGES.get(reason, reason))
        self.reason = reason


def _exercise_names(config_path: str = "config.yaml") -> Dict[str, str]:
    from analyze import load_config
    return {k: c.name for k, c in load_config(config_path).items()}


def _target(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100 else None


class ClinicLiveSession:
    """One connection's view of a live session. Every public method is safe from any thread."""

    def _setup(self, patient_id: str, clock, rate_cap: int, pose_model) -> None:
        self.patient_id, self.clock = patient_id, clock
        self.bad_frames = 0
        self._lock = threading.RLock()
        self._keypoints = None
        self._result: Optional[Dict[str, Any]] = None
        self._rep_offset = 0
        self.meter = frames.RateMeter(clock=clock, nominal=NOMINAL_FPS, cap=rate_cap)
        self.model = str(pose_model)[:40] if isinstance(pose_model, str) and pose_model else DEFAULT_POSE_MODEL
        self.names = _exercise_names()

    def _live(self, store, key: str, target: Optional[int]) -> LiveSession:
        return LiveSession(store, self.patient_id, key, target, "clinic", self._infer, fps=float(NOMINAL_FPS),
                           draw=False, clock=self.clock,
                           extras={"origin": ORIGIN, "pose_model": self.model, "pose_source": "browser",
                                   "fps_nominal": NOMINAL_FPS, "camera_id": "browser"})

    @classmethod
    def start(cls, db_path: Path, patient_id: str, exercise_key: Any, target_reps: Any = None,
              pose_model: Any = None, clock: Callable[[], datetime] = datetime.now,
              rate_cap: int = 20) -> "ClinicLiveSession":
        """The caller has checked the therapist may see the patient."""
        self = object.__new__(cls)
        self._setup(patient_id, clock, rate_cap, pose_model)
        if exercise_key not in self.names:
            raise LiveRefused("unknown_exercise")
        store = SessionStore(db_path, clock=clock, check_same_thread=False).open()
        try:
            if store.current_plan(patient_id) is None and store.plans(patient_id):
                raise LiveRefused("plan_archived")
            if store.conn.execute("SELECT 1 FROM sessions WHERE patient_id = ? AND status = 'running'",
                                  (patient_id,)).fetchone():
                raise LiveRefused("running")        # a home session, or this one open in another tab
            self.store = store
            self.live = self._live(store, exercise_key, _target(target_reps))
            self.session_id = self.live.start()
        except Exception:
            store.close()
            raise
        return self

    @classmethod
    def resume(cls, db_path: Path, patient_id: str, session_id: Any, pose_model: Any = None,
               clock: Callable[[], datetime] = datetime.now, rate_cap: int = 20) -> "ClinicLiveSession":
        """Carry on a clinic live session after the host cut the connection (feature 020)."""
        self = object.__new__(cls)
        self._setup(patient_id, clock, rate_cap, pose_model)
        store = SessionStore(db_path, clock=clock, check_same_thread=False).open()
        try:
            row = None
            if isinstance(session_id, int) and not isinstance(session_id, bool):
                row = store.conn.execute("SELECT patient_id, status, source_extras FROM sessions WHERE id = ?",
                                         (session_id,)).fetchone()
            extras = json.loads(row["source_extras"] or "{}") if row else {}
            if row is None or row["patient_id"] != patient_id or row["status"] != "running" \
                    or extras.get("origin") != ORIGIN:
                raise LiveRefused("not_resumable")
            open_set = store.session_open_set(session_id)
            set_row = store.conn.execute("SELECT exercise_key, target_reps FROM exercise_sets WHERE id = ?",
                                         (open_set,)).fetchone() if open_set else None
            if set_row is None or set_row["exercise_key"] not in self.names:
                raise LiveRefused("not_resumable")
            self._rep_offset = store.conn.execute(
                "SELECT COUNT(*) FROM reps r JOIN exercise_sets s ON s.id = r.set_id "
                "WHERE s.session_id = ? AND s.exercise_key = ? AND r.out_of_range = 0",
                (session_id, set_row["exercise_key"])).fetchone()[0]
            self.store = store
            target = set_row["target_reps"]
            self.live = self._live(store, set_row["exercise_key"], max(1, target - self._rep_offset) if target else None)
            self._full_target = target
            self.session_id = self.live.resume(session_id)
        except Exception:
            store.close()
            raise
        return self

    def _infer(self, _frame):
        return self._keypoints

    @property
    def ended(self) -> bool:
        return self._result is not None

    def handle_frame(self, message: Any) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self.ended:
                return None
            try:
                keypoints, width, height = frames.validate_frame(message)
            except frames.FrameError:
                self.bad_frames += 1
                raise
            if not self.meter.accept():
                return None
            self._keypoints = frames.to_engine_keypoints(keypoints, width, height)
            self.live.process(_DUMMY_FRAME)
            return self.state()

    def state(self) -> Dict[str, Any]:
        with self._lock:
            m = self.live.metrics or {}
            reps = self._rep_offset + int(m.get("rep_count", 0))
            target = getattr(self, "_full_target", None) or self.live.config.target_reps
            seen = self._keypoints is not None
            angle = m.get("current_angle")
            return {"type": "state", "session_id": self.session_id, "exercise_key": self.live.exercise_key,
                    "exercise": self.live.exercise_name, "target_reps": target, "rep_count": reps,
                    "phase": str(m.get("state", "neutral")),
                    "angle": round(float(angle), 1) if seen and angle is not None else None,
                    "form_status": m.get("form_status"), "form_messages": list(m.get("form_messages", []))[:2],
                    "feedback": m.get("feedback") or "", "set_complete": bool(target) and reps >= target,
                    "seen": seen, "notice": "low_rate" if self.meter.low_rate else (
                        None if seen or not self.meter.accepted else "no_person")}

    def switch(self, exercise_key: Any, target_reps: Any = None) -> Dict[str, Any]:
        """Change exercise: the next set starts at 0 reps."""
        with self._lock:
            if not self.ended and exercise_key in self.names and exercise_key != self.live.exercise_key:
                self.live.target_reps = _target(target_reps)   # None: the new exercise's own default target
                self.live.switch(exercise_key)
                self._rep_offset, self._full_target, self._keypoints = 0, None, None
            return self.state()

    def reset(self) -> Dict[str, Any]:
        with self._lock:
            if not self.ended:
                self.live.reset()
                self._rep_offset = 0
            return self.state()

    def set_target(self, target_reps: Any) -> Dict[str, Any]:
        with self._lock:
            if not self.ended and _target(target_reps):
                # The engine applies a target to sets opened from now on (as Streamlit did); the screen shows the
                # new target straight away, so "Target reached" follows what the therapist just set.
                self.live.set_target_reps(_target(target_reps))
                self._full_target = _target(target_reps)
            return self.state()

    def _finish(self, stored) -> Dict[str, Any]:
        per_set = [{"name": s.exercise_name, "reps": sum(1 for r in s.reps if not r.out_of_range)} for s in stored.sets]
        self._result = {"type": "ended", "status": stored.status, "session_id": stored.id,
                        "summary": {"exercises": per_set, "total_reps": stored.total_reps or 0,
                                    "avg_form_score": stored.avg_form_score}}
        self.store.close()
        return self._result

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            if self.ended:
                return self._result
            return self._finish(self.live.end())

    def interrupt(self, reason: str) -> Dict[str, Any]:
        with self._lock:
            if self.ended:
                return self._result
            return self._finish(self.live.interrupt(reason))

    def detach(self) -> Dict[str, Any]:
        """Write what is buffered and leave the session running for a `resume` on a new connection."""
        with self._lock:
            if self.ended:
                return self._result
            self.live.detach()
            self._result = {"type": "segment", "session_id": self.session_id}
            self.store.close()
            return self._result
