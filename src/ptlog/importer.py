"""
One-time import of legacy session files into the canonical record (FR-025, FR-026).

Three JSON shapes are understood:
  * the per-session report (`session_summary` + `rep_details`) the retired report writer
    wrote into sessions/,
  * the observation log (`events` stream) the retired ObservationLogger wrote into
    observation_logs/,
  * the session tracker record (`session_id` + `exercises`, aggregates only). Its sets carry
    no per-rep data, so `reps_completed` rep rows are reconstructed from the set averages
    and marked with frame_num = -1 so later analysis can tell them apart.

Files are never moved or deleted. An import ledger keyed by SHA-256 makes the run
idempotent, and a (first exercise, start second, total reps) key catches the same session
saved in both folders.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .models import UNASSIGNED_ID, ControlEvent, ExerciseSetInfo, LedgerRow, PartialRepEvent, RepEvent
from .recorder import derive_exercise_key
from .store import REPO_ROOT, SessionStore

LEGACY_SOURCE_REF = "legacy-import"
DERIVED_SUFFIXES = {".csv", ".txt", ".log"}


# ------------------------------------------------------------------ report types

@dataclass
class ImportEntry:
    path: Path
    outcome: str                 # imported | duplicate | malformed | skipped
    detail: str = ""
    session_id: Optional[int] = None


@dataclass
class ImportReport:
    entries: List[ImportEntry] = field(default_factory=list)
    dry_run: bool = False

    def _count(self, outcome: str) -> int:
        return sum(1 for e in self.entries if e.outcome == outcome)

    @property
    def imported(self) -> int:
        return self._count("imported")

    @property
    def duplicates(self) -> int:
        return self._count("duplicate")

    @property
    def malformed(self) -> int:
        return self._count("malformed")

    @property
    def skipped(self) -> int:
        return self._count("skipped")


@dataclass
class SetDraft:
    info: ExerciseSetInfo
    start_time: str
    end_time: Optional[str] = None
    reps: List[RepEvent] = field(default_factory=list)
    partial_reps: List[PartialRepEvent] = field(default_factory=list)


@dataclass
class ParsedSession:
    source: str
    start_time: str
    end_time: Optional[str]
    sets: List[SetDraft]
    control_events: List[ControlEvent] = field(default_factory=list)
    patient_id: Optional[str] = None
    total_reps: int = 0
    status: str = "completed"

    @property
    def first_exercise(self) -> str:
        return self.sets[0].info.exercise_name if self.sets else ""

    def dedup_key(self) -> tuple:
        return (self.first_exercise.lower(), (self.start_time or "")[:19], int(self.total_reps))


# ------------------------------------------------------------------ helpers

def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_CATALOG: Optional[Dict[str, Dict[str, Any]]] = None


def exercise_catalog(config_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Display name (lower) -> {key, side, up_angle, down_angle, target_reps} from config.yaml."""
    global _CATALOG
    if _CATALOG is not None and config_path is None:
        return _CATALOG
    path = config_path or (REPO_ROOT / "config.yaml")
    catalog: Dict[str, Dict[str, Any]] = {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
        for key, ex in (data.get("exercises") or {}).items():
            name = str(ex.get("display_name", key))
            catalog[name.lower()] = {
                "key": key, "side": ex.get("side", "left"),
                "up_angle": float(ex.get("up_angle", 0.0)), "down_angle": float(ex.get("down_angle", 0.0)),
                "target_reps": int(ex.get("target_reps", 10)),
            }
    except (OSError, yaml.YAMLError):
        catalog = {}
    if config_path is None:
        _CATALOG = catalog
    return catalog


def set_info_for(name: str, target_reps: Optional[int] = None) -> ExerciseSetInfo:
    entry = exercise_catalog().get((name or "").lower())
    if entry:
        return ExerciseSetInfo(entry["key"], name, entry["side"], int(target_reps or entry["target_reps"]),
                               entry["up_angle"], entry["down_angle"])
    lowered = (name or "").lower()
    side = "right" if "(right)" in lowered else ("bilateral" if any(w in lowered for w in ("squat", "push", "trunk")) else "left")
    return ExerciseSetInfo(derive_exercise_key(name or "unknown"), name or "Unknown", side, int(target_reps or 10), 0.0, 0.0)


def _iso(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing {what}")
    datetime.fromisoformat(value)   # validates
    return value


def _rep(d: Dict[str, Any], number: int, ts: str, frame: int = 0) -> RepEvent:
    return RepEvent(rep_number=int(d.get("rep_number", number)), min_angle=float(d["min_angle"]),
                    max_angle=float(d["max_angle"]), rom=float(d["rom"]),
                    duration_seconds=float(d["duration_seconds"]), form_score=float(d["form_score"]),
                    timestamp=ts, frame_num=frame)


# ------------------------------------------------------------------ parsers

def detect_shape(data: Any) -> str:
    if not isinstance(data, dict):
        raise ValueError("top level is not a JSON object")
    if "session_summary" in data and "rep_details" in data:
        return "report"
    if "events" in data and "session_id" in data:
        return "observation"
    if "exercises" in data and "session_id" in data and "date" in data:
        return "tracker"
    raise ValueError("unrecognized session file shape")


def parse_session_report(data: Dict[str, Any]) -> ParsedSession:
    summary = data["session_summary"]
    start = _iso(summary.get("start_time"), "session_summary.start_time")
    end = summary.get("end_time") or None
    if end:
        end = _iso(end, "session_summary.end_time")
    name = str(summary.get("exercise") or "Unknown")
    draft = SetDraft(set_info_for(name, summary.get("target_reps")), start, end)
    for i, d in enumerate(data.get("rep_details") or [], 1):
        draft.reps.append(_rep(d, i, _iso(d.get("timestamp") or start, "rep timestamp")))
    return ParsedSession(source=str(data.get("source") or "video"), start_time=start, end_time=end,
                         sets=[draft], total_reps=int(summary.get("total_reps", len(draft.reps))))


def parse_observation_log(data: Dict[str, Any]) -> ParsedSession:
    start = _iso(data.get("start_time"), "start_time")
    source = str(data.get("source") or "video")
    events = data.get("events")
    if not isinstance(events, list):
        raise ValueError("events is not a list")
    sets: List[SetDraft] = []
    controls: List[ControlEvent] = []
    current = SetDraft(set_info_for(str(data.get("initial_exercise") or "Unknown"), data.get("target_reps")), start)
    sets.append(current)
    end: Optional[str] = data.get("end_time") or None
    for ev in events:
        kind = ev.get("type")
        ts = _iso(ev.get("timestamp") or start, f"{kind} timestamp")
        if kind == "rep":
            current.reps.append(_rep(ev, len(current.reps) + 1, ts))
        elif kind == "partial_rep":
            current.partial_reps.append(PartialRepEvent(
                reason=str(ev.get("reason") or "insufficient_rom"), min_angle=float(ev.get("min_angle", 0.0)),
                max_angle=float(ev.get("max_angle", 0.0)), rom=float(ev.get("rom", 0.0)),
                duration_seconds=float(ev.get("duration_seconds", 0.0)), timestamp=ts))
        elif kind == "exercise_change":
            current.end_time = ts
            controls.append(ControlEvent("switch", ts, 0, from_exercise=ev.get("from_exercise"), to_exercise=ev.get("to_exercise")))
            current = SetDraft(set_info_for(str(ev.get("to_exercise") or "Unknown"), data.get("target_reps")), ts)
            sets.append(current)
        elif kind == "reset":
            controls.append(ControlEvent("reset", ts, 0, rep_count_at_reset=int(ev.get("rep_count_at_reset", 0))))
        elif kind == "session_end":
            end = end or ts
    total = int((data.get("summary") or {}).get("total_reps", sum(len(s.reps) for s in sets)))
    status = "completed" if end else "interrupted"
    return ParsedSession(source=source, start_time=start, end_time=end, sets=sets, control_events=controls,
                         total_reps=total, status=status)


def parse_tracker_json(data: Dict[str, Any]) -> ParsedSession:
    date = str(data.get("date") or "")
    start = _iso(f"{date}T{data.get('start_time') or '00:00:00'}", "date/start_time")
    end = f"{date}T{data['end_time']}" if data.get("end_time") else None
    if end:
        end = _iso(end, "end_time")
    sets: List[SetDraft] = []
    total = 0
    for ex in data.get("exercises") or []:
        name = str(ex.get("exercise_name") or "Unknown")
        draft = SetDraft(set_info_for(name, ex.get("target_reps")), start, end)
        n = int(ex.get("reps_completed", 0))
        for i in range(1, n + 1):   # aggregate-only file: reconstruct rows from the set averages
            draft.reps.append(RepEvent(rep_number=i, min_angle=float(ex.get("min_rom", 0.0)),
                                       max_angle=float(ex.get("max_rom", 0.0)), rom=float(ex.get("rom_range", 0.0)),
                                       duration_seconds=float(ex.get("avg_rep_duration", 0.0)),
                                       form_score=float(ex.get("avg_form_score", 0.0)), timestamp=start, frame_num=-1))
        total += n
        sets.append(draft)
    if not sets:
        raise ValueError("no exercises in tracker record")
    return ParsedSession(source=str((data.get("metadata") or {}).get("source") or "video"), start_time=start,
                         end_time=end, sets=sets, patient_id=data.get("patient_id"), total_reps=total)


PARSERS = {"report": parse_session_report, "observation": parse_observation_log, "tracker": parse_tracker_json}


# ------------------------------------------------------------------ the import

def import_legacy(store: SessionStore, sessions_dir: Optional[Path], obs_dir: Optional[Path],
                  dry_run: bool = False) -> ImportReport:
    report = ImportReport(dry_run=dry_run)
    files: List[Path] = []
    for d in (sessions_dir, obs_dir):
        if d and Path(d).is_dir():
            files += sorted(p for p in Path(d).iterdir() if p.is_file() and not p.name.startswith("."))
    existing_keys = store.imported_session_keys()
    seen_keys: set = set()

    for path in files:
        if path.suffix.lower() != ".json":
            if path.suffix.lower() in DERIVED_SUFFIXES:
                report.entries.append(ImportEntry(path, "skipped", "derived format, not a session record"))
            continue
        sha = file_sha256(path)
        prior = store.ledger_lookup(sha)
        if prior is not None:
            if prior.outcome == "malformed":
                report.entries.append(ImportEntry(path, "malformed", prior.reason or "unreadable (already reported)"))
            else:
                report.entries.append(ImportEntry(path, "duplicate", "already imported", prior.session_id))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            parsed = PARSERS[detect_shape(data)](data)
        except (ValueError, KeyError, TypeError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            report.entries.append(ImportEntry(path, "malformed", reason))
            if not dry_run:
                store.ledger_add(LedgerRow(sha, str(path), None, "malformed", reason=reason[:200]))
            continue
        key = parsed.dedup_key()
        if key in existing_keys or key in seen_keys:
            report.entries.append(ImportEntry(path, "duplicate", "same session found in both folders"))
            if not dry_run:
                store.ledger_add(LedgerRow(sha, str(path), None, "duplicate", reason="same session found in both folders"))
            continue
        seen_keys.add(key)
        if dry_run:
            report.entries.append(ImportEntry(path, "imported", "dry run"))
            continue
        patient = parsed.patient_id if parsed.patient_id and store.get_patient(parsed.patient_id) else UNASSIGNED_ID
        sid = store.import_session(
            patient_id=patient, source=parsed.source, source_ref=LEGACY_SOURCE_REF,
            start_time=parsed.start_time, end_time=parsed.end_time, status=parsed.status,
            sets=[{"info": s.info, "start_time": s.start_time, "end_time": s.end_time,
                   "reps": s.reps, "partial_reps": s.partial_reps} for s in parsed.sets],
            control_events=parsed.control_events,
        )
        store.ledger_add(LedgerRow(sha, str(path), sid, "imported"))
        report.entries.append(ImportEntry(path, "imported", f"session {sid}", sid))
    return report
