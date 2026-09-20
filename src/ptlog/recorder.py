"""
SessionRecorder — the only engine-facing adapter of the canonical record.

It reads nothing but the engine's public outputs (constitution I): the dictionary
returned by ExerciseTracker.update(), the tracker's public `session` (ExerciseSession
with RepMetrics / PartialRepMetrics), `current_state`, `rep_count`, and the
OverallFormAssessment produced by FormAnalyzer. It never reads tracker internals and
never changes engine behaviour. See specs/001-unified-session-log/contracts/recorder.md.
"""

from __future__ import annotations

import os
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .models import (
    UNASSIGNED_ID,
    ControlEvent,
    ExerciseSetInfo,
    FormEvent,
    FrameSample,
    PartialRepEvent,
    PatientNotFoundError,
    RepEvent,
    Session,
)
from .store import SessionStore

logger = logging.getLogger("ptlog")

_FORM_STATUSES_RECORDED = ("warning", "poor", "stop")


def _r1(value: Any) -> float:
    return round(float(value), 1)


def _r2(value: Any) -> float:
    return round(float(value), 2)


def derive_exercise_key(display_name: str) -> str:
    """'Knee Extension (Right)' -> 'knee_extension_right' (matches config.yaml keys)."""
    cleaned = re.sub(r"[()]", "", display_name.strip().lower())
    return re.sub(r"\s+", "_", cleaned)


def map_severity(status: str, priority: Any) -> str:
    """Map the engine's FormStatus + FeedbackPriority to suggestion | warning | stop."""
    pname = getattr(priority, "name", None) if priority is not None else None
    if status == "stop" or pname == "CRITICAL":
        return "stop"
    if pname == "WARNING" or status == "poor":
        return "warning"
    if pname in ("INFO", "SUGGESTION"):
        return "suggestion"
    return "warning"


class SessionRecorder:
    """Turns engine outputs into canonical events through the single store."""

    def __init__(
        self,
        store: SessionStore,
        clock: Callable[[], datetime] = datetime.now,
        sample_every: int = 15,
        form_throttle_frames: int = 60,
        form_throttle_seconds: float = 2.0,
        sample_flush_seconds: float = 1.0,
    ):
        self.store = store
        self.clock = clock
        self.sample_every = sample_every
        self.form_throttle_frames = form_throttle_frames
        self.form_throttle_seconds = form_throttle_seconds
        self.sample_flush_seconds = sample_flush_seconds

        self._session_id: Optional[int] = None
        self._set_id: Optional[int] = None
        self._set_name: Optional[str] = None
        self._seen_reps = 0
        self._seen_partials = 0
        self._samples: List[FrameSample] = []
        self._last_flush: Optional[datetime] = None
        self._last_form_frame = -(10 ** 9)
        self._last_form_msg: Optional[str] = None
        self._last_form_time: Optional[datetime] = None

        self.degraded = False
        self._first_error: Optional[BaseException] = None

    # ------------------------------------------------------------------ properties

    @property
    def session_id(self) -> Optional[int]:
        return self._session_id

    @property
    def set_id(self) -> Optional[int]:
        return self._set_id

    @property
    def pending_sample_count(self) -> int:
        return len(self._samples)

    # ------------------------------------------------------------------ lifecycle

    def start(self, patient_id: Optional[str], source: str, source_ref: str, exercise_config: Any,
              exercise_key: Optional[str] = None, extras: Optional[Dict[str, Any]] = None) -> int:
        """Open the session and its first exercise set. Raises PatientNotFoundError."""
        pid = patient_id or UNASSIGNED_ID
        if self.store.get_patient(pid) is None:
            raise PatientNotFoundError(f"Patient '{pid}' not found")
        # The recording process id lets recovery tell a live session from an abandoned one.
        extras = {**(extras or {}), "pid": os.getpid()}
        self._session_id = self.store.start_session(pid, source, str(source_ref), extras)
        self._last_flush = self.clock()
        self._open_set(exercise_config, exercise_key)
        return self._session_id

    def observe(self, tracker: Any, metrics: Dict[str, Any], angle: Optional[float],
                frame_num: int, assessment: Any) -> None:
        """Call once per inference frame, right after `metrics = tracker.update(angle)`."""
        if self._session_id is None:
            return
        now = self.clock()
        ts = now.isoformat()
        try:
            had_event = self._drain(tracker, ts, frame_num)
            had_event = self._record_form(assessment, now, ts, frame_num) or had_event
            if angle is not None and frame_num % self.sample_every == 0:
                self._samples.append(FrameSample(
                    frame_num=int(frame_num), timestamp=ts, angle=float(angle),
                    state=str(getattr(tracker, "current_state", "neutral")),
                    rep_count=int(metrics.get("rep_count", 0)),
                ))
            if had_event or self._flush_due(now):
                self.flush(now)
        except Exception as err:  # noqa: BLE001 — the on-screen session must never die because of logging
            self._degrade(err)

    def switch(self, new_exercise_config: Any, tracker: Any, frame_num: int = 0,
               exercise_key: Optional[str] = None) -> None:
        """Close the current set and open one for `new_exercise_config`.

        Call with the OLD tracker (before it is replaced) so partial reps recorded at
        switch time are captured.
        """
        if self._session_id is None:
            return
        now = self.clock()
        ts = now.isoformat()
        try:
            self._drain(tracker, ts, frame_num)
            self.flush(now)
            self.store.close_set(self._set_id, ts)
            self.store.add_control_event(self._session_id, ControlEvent(
                kind="switch", timestamp=ts, frame_num=int(frame_num),
                from_exercise=self._set_name, to_exercise=new_exercise_config.name))
            self._open_set(new_exercise_config, exercise_key, start_time=ts)
        except Exception as err:  # noqa: BLE001
            self._degrade(err)

    def reset(self, tracker: Any, frame_num: int = 0) -> None:
        """Record a counter reset. Call with the tracker about to be replaced."""
        if self._session_id is None:
            return
        now = self.clock()
        ts = now.isoformat()
        try:
            self._drain(tracker, ts, frame_num)
            self.flush(now)
            self.store.add_control_event(self._session_id, ControlEvent(
                kind="reset", timestamp=ts, frame_num=int(frame_num),
                rep_count_at_reset=int(getattr(tracker, "rep_count", 0))))
        except Exception as err:  # noqa: BLE001
            self._degrade(err)
        self._seen_reps = 0
        self._seen_partials = 0

    def end(self, session: Any = None) -> Optional[Session]:
        """Finish the session. Re-raises the first store error if recording was degraded."""
        result: Optional[Session] = None
        if self._session_id is not None:
            try:
                self.flush()
                if self._set_id is not None:
                    self.store.close_set(self._set_id)
                result = self.store.end_session(self._session_id)
            except Exception as err:  # noqa: BLE001
                self._degrade(err)
        if self._first_error is not None:
            raise self._first_error
        return result

    def flush(self, now: Optional[datetime] = None) -> None:
        """Write buffered frame samples in one transaction."""
        if self._samples and self._set_id is not None:
            self.store.add_frame_samples(self._set_id, self._samples)
            self._samples = []
        self._last_flush = now or self.clock()

    # ------------------------------------------------------------------ internals

    def _open_set(self, cfg: Any, exercise_key: Optional[str], start_time: Optional[str] = None) -> None:
        info = ExerciseSetInfo(
            exercise_key=exercise_key or derive_exercise_key(cfg.name),
            exercise_name=cfg.name,
            side=getattr(cfg, "side", "left") or "left",
            target_reps=int(cfg.target_reps),
            up_angle=float(cfg.up_angle),
            down_angle=float(cfg.down_angle),
        )
        self._set_id = self.store.open_set(self._session_id, info)
        self._set_name = cfg.name
        self._seen_reps = 0
        self._seen_partials = 0
        self._last_form_frame = -(10 ** 9)
        self._last_form_msg = None
        self._last_form_time = None

    def _drain(self, tracker: Any, ts: str, frame_num: int) -> bool:
        """Store RepMetrics / PartialRepMetrics appended to the tracker's session since last call."""
        had_event = False
        session = getattr(tracker, "session", None)
        if session is None:
            return False
        # The engine reports numpy float32 values; round the way the legacy loggers did
        # (angles, ROM, form score to 1 decimal; duration to 2) so stored values are clean.
        reps = list(getattr(session, "rep_metrics", []))
        for r in reps[self._seen_reps:]:
            self.store.add_rep(self._set_id, RepEvent(
                rep_number=int(r.rep_number), min_angle=_r1(r.min_angle), max_angle=_r1(r.max_angle),
                rom=_r1(r.rom), duration_seconds=_r2(r.duration_seconds), form_score=_r1(r.form_score),
                timestamp=ts, frame_num=int(frame_num)))
            had_event = True
        self._seen_reps = len(reps)

        partials = list(getattr(session, "partial_rep_metrics", []))
        for p in partials[self._seen_partials:]:
            self.store.add_partial_rep(self._set_id, PartialRepEvent(
                reason=str(p.reason), min_angle=_r1(p.min_angle), max_angle=_r1(p.max_angle),
                rom=_r1(p.rom), duration_seconds=_r2(p.duration_seconds), timestamp=ts, frame_num=int(frame_num)))
            had_event = True
        self._seen_partials = len(partials)
        return had_event

    def _record_form(self, assessment: Any, now: datetime, ts: str, frame_num: int) -> bool:
        if assessment is None:
            return False
        status = getattr(getattr(assessment, "status", None), "value", None)
        if status not in _FORM_STATUSES_RECORDED:
            return False
        if frame_num - self._last_form_frame < self.form_throttle_frames:
            return False
        messages = list(getattr(assessment, "feedback_messages", []) or [])
        first = messages[0] if messages else None
        message = getattr(first, "message", "") if first is not None else ""
        if (message == self._last_form_msg and self._last_form_time is not None
                and (now - self._last_form_time).total_seconds() < self.form_throttle_seconds):
            return False
        self.store.add_form_event(self._set_id, FormEvent(
            severity=map_severity(status, getattr(first, "priority", None)),
            status=status, message=message, timestamp=ts, frame_num=int(frame_num),
            body_part=getattr(first, "body_part", None) if first is not None else None))
        self._last_form_frame = frame_num
        self._last_form_msg = message
        self._last_form_time = now
        return True

    def _flush_due(self, now: datetime) -> bool:
        if not self._samples:
            return False
        if self._last_flush is None:
            return True
        return (now - self._last_flush).total_seconds() >= self.sample_flush_seconds

    def _degrade(self, err: BaseException) -> None:
        if not self.degraded:
            self.degraded = True
            self._first_error = err
            logger.error(
                "recording failed for session %s; the on-screen session continues without persistence: %s",
                self._session_id, err,
            )
