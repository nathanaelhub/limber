"""
A patient's guided home session (feature 007, US2).

`PortalLiveSession` wraps the clinic's `LiveSession` adapter: the "inference" step simply returns
the body points the patient's browser sent with the current message, so the same rep state machine,
form analyzer, and recording path run at home as in the clinic. The service owns the frame counter,
every stored time, the order of exercises, and the targets; the browser only sends points and asks
to start, move on, or stop.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from src.live_session import LiveSession
from src.portal import frames, viewmodels
from src.ptlog.models import PortalError
from src.ptlog.store import SessionStore

NOMINAL_FPS = 15
DEFAULT_POSE_MODEL = "movenet-lightning-4"
_DUMMY_FRAME = np.zeros((1, 1, 3), dtype=np.uint8)       # nothing is drawn server-side; video never arrives


class LiveRefused(PortalError):
    MESSAGES = {
        "second_device": "A session is already running for you on another device. Stop it there first.",
        "busy": "Limber is busy right now. Please try again in a few minutes.",
        "no_program": "Your therapist has not assigned a program yet.",
        "plan_archived": "This plan of care is archived. Ask your therapist to open a new one.",
    }

    def __init__(self, reason: str):
        super().__init__(self.MESSAGES.get(reason, reason))
        self.reason = reason


class LiveRegistry:
    """One running home session per patient, and a cap on how many run at once."""

    def __init__(self, limit: int = 8):
        self.limit = limit
        self._active: Dict[str, "PortalLiveSession"] = {}
        self._lock = threading.Lock()

    def claim(self, patient_id: str, session: "PortalLiveSession") -> None:
        with self._lock:
            if patient_id in self._active:
                raise LiveRefused("second_device")
            if len(self._active) >= self.limit:
                raise LiveRefused("busy")
            self._active[patient_id] = session

    def release(self, patient_id: str, session: "PortalLiveSession") -> None:
        with self._lock:
            if self._active.get(patient_id) is session:
                del self._active[patient_id]

    def active(self, patient_id: str) -> Optional["PortalLiveSession"]:
        with self._lock:
            return self._active.get(patient_id)


class PortalLiveSession:
    def __init__(self):
        raise TypeError("use PortalLiveSession.start(...)")

    @classmethod
    def start(cls, db_path: Path, patient_id: str, registry: LiveRegistry, pose_model: str = DEFAULT_POSE_MODEL,
              form_analyzer_factory: Optional[Callable[[str], Any]] = None,
              clock: Callable[[], datetime] = datetime.now, rate_cap: int = 20) -> "PortalLiveSession":
        self = object.__new__(cls)
        self.patient_id, self.registry, self.clock = patient_id, registry, clock
        self.bad_frames = 0
        self._rep_offset = 0          # reps of this exercise done before a resume (feature 020)
        self._lock = threading.RLock()
        self._keypoints: Optional[np.ndarray] = None
        self._result: Optional[Dict[str, Any]] = None
        self.meter = frames.RateMeter(clock=clock, nominal=NOMINAL_FPS, cap=rate_cap)

        store = SessionStore(db_path, clock=clock, check_same_thread=False).open()
        try:
            now = clock()
            self.exercises: List[Dict[str, Any]] = viewmodels.program_exercises(store, patient_id, now.date())
            if not self.exercises:
                raise LiveRefused("no_program")
            if store.current_plan(patient_id) is None and store.plans(patient_id):
                raise LiveRefused("plan_archived")              # feature 017: nothing new in an archived plan
            # Another device may be recording on another hosted instance (feature 020). Opening the store has
            # already recovered abandoned sessions, so one still running here has a live owner.
            if store.conn.execute("SELECT 1 FROM sessions WHERE patient_id = ? AND status = 'running'",
                                  (patient_id,)).fetchone():
                raise LiveRefused("second_device")
            registry.claim(patient_id, self)
        except Exception:
            store.close()
            raise
        try:
            done = viewmodels.done_today_keys(store, patient_id, now)
            self.index = next((i for i, e in enumerate(self.exercises) if e["key"] not in done), 0)
            first = self.exercises[self.index]
            model = str(pose_model)[:40] if isinstance(pose_model, str) and pose_model else DEFAULT_POSE_MODEL
            self.store = store
            self.live = LiveSession(
                store, patient_id, first["key"], first["target_reps"], "home", self._infer, fps=float(NOMINAL_FPS),
                draw=False, clock=clock, form_analyzer_factory=form_analyzer_factory,
                extras={"origin": "portal", "pose_model": model, "fps_nominal": NOMINAL_FPS, "camera_id": "home"})
            self.session_id = self.live.start()
            store.portal_audit_add("live_start", patient_id, None, first["key"])
        except Exception:
            registry.release(patient_id, self)
            store.close()
            raise
        return self

    @classmethod
    def resume(cls, db_path: Path, patient_id: str, session_id: Any, registry: LiveRegistry,
               pose_model: str = DEFAULT_POSE_MODEL, form_analyzer_factory: Optional[Callable[[str], Any]] = None,
               clock: Callable[[], datetime] = datetime.now, rate_cap: int = 20) -> "PortalLiveSession":
        """Pick up the patient's own running home session after the host cut the connection (feature 020).
        The exercise carries on where it was, in a new set; the screen keeps counting from the reps already done."""
        import json
        self = object.__new__(cls)
        self.patient_id, self.registry, self.clock = patient_id, registry, clock
        self.bad_frames = 0
        self._lock = threading.RLock()
        self._keypoints: Optional[np.ndarray] = None
        self._result: Optional[Dict[str, Any]] = None
        self.meter = frames.RateMeter(clock=clock, nominal=NOMINAL_FPS, cap=rate_cap)
        store = SessionStore(db_path, clock=clock, check_same_thread=False).open()
        try:
            row = None
            if isinstance(session_id, int) and not isinstance(session_id, bool):
                row = store.conn.execute("SELECT patient_id, status, source_extras FROM sessions WHERE id = ?",
                                         (session_id,)).fetchone()
            extras = json.loads(row["source_extras"] or "{}") if row else {}
            if row is None or row["patient_id"] != patient_id or row["status"] != "running" \
                    or extras.get("origin") != "portal":
                raise LiveRefused("not_resumable")
            now = clock()
            self.exercises = viewmodels.program_exercises(store, patient_id, now.date())
            if not self.exercises:
                raise LiveRefused("no_program")
            open_set = store.session_open_set(session_id)
            key = store.conn.execute("SELECT exercise_key FROM exercise_sets WHERE id = ?",
                                     (open_set,)).fetchone()[0] if open_set else self.exercises[0]["key"]
            self.index = next((i for i, e in enumerate(self.exercises) if e["key"] == key), 0)
            current = self.exercises[self.index]
            self._rep_offset = store.conn.execute(
                "SELECT COUNT(*) FROM reps r JOIN exercise_sets s ON s.id = r.set_id "
                "WHERE s.session_id = ? AND s.exercise_key = ? AND r.out_of_range = 0",
                (session_id, current["key"])).fetchone()[0]
            registry.claim(patient_id, self)
        except Exception:
            store.close()
            raise
        try:
            model = str(pose_model)[:40] if isinstance(pose_model, str) and pose_model else DEFAULT_POSE_MODEL
            self.store = store
            self.live = LiveSession(
                store, patient_id, current["key"], max(1, current["target_reps"] - self._rep_offset), "home",
                self._infer, fps=float(NOMINAL_FPS), draw=False, clock=clock,
                form_analyzer_factory=form_analyzer_factory,
                extras={"origin": "portal", "pose_model": model, "fps_nominal": NOMINAL_FPS, "camera_id": "home"})
            self.session_id = self.live.resume(session_id)
        except Exception:
            registry.release(patient_id, self)
            store.close()
            raise
        return self

    def detach(self) -> Dict[str, Any]:
        """Hand the session over to a later `resume`: write what is buffered, keep it running (its lease holds it),
        and let go of this connection. Idempotent."""
        with self._lock:
            if self.ended:
                return self._result
            self.live.detach()
            self._result = {"type": "segment", "session_id": self.session_id}
            try:
                self.registry.release(self.patient_id, self)
            finally:
                self.store.close()
            return self._result

    # the engine's "inference": the body points that came with the current message
    def _infer(self, _frame):
        return self._keypoints

    @property
    def ended(self) -> bool:
        return self._result is not None

    def handle_frame(self, message: Any) -> Optional[Dict[str, Any]]:
        """Run the engine on one frame message. Returns the new state, or None when the frame was
        dropped (over the rate cap) or the session has ended. Raises FrameError for a bad message."""
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
            current = self.exercises[self.index]
            reps = self._rep_offset + int(m.get("rep_count", 0))
            seen = self._keypoints is not None
            notice = "low_rate" if self.meter.low_rate else (None if seen or not self.meter.accepted else "no_person")
            angle = m.get("current_angle")
            return {
                "type": "state", "exercise": current["name"], "index": self.index + 1, "total": len(self.exercises),
                "target_reps": current["target_reps"], "rep_count": reps, "phase": str(m.get("state", "neutral")),
                "angle": round(float(angle), 1) if seen and angle is not None else None,
                "form_status": m.get("form_status"), "form_messages": list(m.get("form_messages", []))[:2],
                "feedback": m.get("feedback") or "", "set_complete": reps >= current["target_reps"],
                "seen": seen, "notice": notice,
            }

    def next(self) -> Dict[str, Any]:
        """Move to the program's next exercise; on the last one nothing changes."""
        with self._lock:
            if not self.ended and self.index < len(self.exercises) - 1:
                self.index += 1
                self._rep_offset = 0
                upcoming = self.exercises[self.index]
                self.live.set_target_reps(upcoming["target_reps"])
                self.live.switch(upcoming["key"])
                self._keypoints = None
            return self.state()

    def _capture_detail(self) -> str:
        parts = [f"fps {self.meter.observed}", f"dropped {self.meter.dropped}"]
        if self.meter.was_low_rate:
            parts.append("low_rate")
        if self.bad_frames:
            parts.append(f"bad_frames {self.bad_frames}")
        return "; ".join(parts)

    def _finish(self, stored, event: str) -> Dict[str, Any]:
        per_set = [{"name": s.exercise_name, "reps": sum(1 for r in s.reps if not r.out_of_range)} for s in stored.sets]
        self._result = {"type": "ended", "status": stored.status,
                        "summary": {"exercises": per_set, "total_reps": stored.total_reps or 0,
                                    "avg_form_score": stored.avg_form_score}}
        try:
            self.store.portal_audit_add(event, self.patient_id, None, self._capture_detail())
        finally:
            self.registry.release(self.patient_id, self)
            self.store.close()
        return self._result

    def stop(self) -> Dict[str, Any]:
        """End as completed and return the summary. Idempotent."""
        with self._lock:
            if self.ended:
                return self._result
            return self._finish(self.live.end(), "live_end")

    def interrupt(self, reason: str) -> Dict[str, Any]:
        """The connection dropped or access was revoked: keep everything recorded, mark it interrupted."""
        with self._lock:
            if self.ended:
                return self._result
            return self._finish(self.live.interrupt(reason), "live_interrupted")
