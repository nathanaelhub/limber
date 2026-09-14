"""
SessionStore — the single writer (and reader) of the canonical PT session log.

One SQLite file, WAL journal, synchronous=FULL, one committed transaction per event so
that every rep, partial rep, form event, and control event is durable within a second of
the engine reporting it (FR-010). Frame samples are batched. Schema changes are forward-
only migrations recorded in `schema_version` (constitution II).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from .privacy import validate_label, validate_patient_id
from .models import (
    UNASSIGNED_ID,
    UNASSIGNED_LABEL,
    BuiltinPatientError,
    ControlEvent,
    DeleteReport,
    DuplicatePatientError,
    ExerciseSet,
    ExerciseSetInfo,
    FormEvent,
    FrameSample,
    LedgerRow,
    LogRow,
    PartialRepEvent,
    Patient,
    PatientNotFoundError,
    RepEvent,
    Session,
    SessionNotFoundError,
    SessionSummaryRow,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1

SCHEMA_V1_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
    id          TEXT PRIMARY KEY COLLATE NOCASE,
    label       TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    is_builtin  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id          TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    schema_version      INTEGER NOT NULL,
    source              TEXT NOT NULL CHECK (source IN ('webcam', 'video')),
    source_ref          TEXT NOT NULL DEFAULT '',
    source_extras       TEXT,
    status              TEXT NOT NULL CHECK (status IN ('running', 'completed', 'interrupted')),
    start_time          TEXT NOT NULL,
    end_time            TEXT,
    total_reps          INTEGER,
    avg_form_score      REAL,
    avg_rom             REAL,
    duration_seconds    REAL,
    interrupted_reason  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_patient_start ON sessions(patient_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE TABLE IF NOT EXISTS exercise_sets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL,
    exercise_key    TEXT NOT NULL,
    exercise_name   TEXT NOT NULL,
    side            TEXT NOT NULL CHECK (side IN ('left', 'right', 'bilateral')),
    target_reps     INTEGER NOT NULL,
    up_angle        REAL NOT NULL,
    down_angle      REAL NOT NULL,
    start_time      TEXT NOT NULL,
    end_time        TEXT
);
CREATE INDEX IF NOT EXISTS idx_sets_session ON exercise_sets(session_id, ordinal);

CREATE TABLE IF NOT EXISTS reps (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id            INTEGER NOT NULL REFERENCES exercise_sets(id) ON DELETE CASCADE,
    rep_number        INTEGER NOT NULL,
    min_angle         REAL NOT NULL,
    max_angle         REAL NOT NULL,
    rom               REAL NOT NULL,
    duration_seconds  REAL NOT NULL,
    form_score        REAL NOT NULL,
    timestamp         TEXT NOT NULL,
    frame_num         INTEGER NOT NULL DEFAULT 0,
    out_of_range      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reps_set ON reps(set_id, timestamp, frame_num);

CREATE TABLE IF NOT EXISTS partial_reps (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id            INTEGER NOT NULL REFERENCES exercise_sets(id) ON DELETE CASCADE,
    reason            TEXT NOT NULL CHECK (reason IN ('insufficient_rom', 'reversed_early', 'interrupted')),
    min_angle         REAL NOT NULL,
    max_angle         REAL NOT NULL,
    rom               REAL NOT NULL,
    duration_seconds  REAL NOT NULL,
    timestamp         TEXT NOT NULL,
    frame_num         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_partials_set ON partial_reps(set_id, timestamp, frame_num);

CREATE TABLE IF NOT EXISTS form_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id      INTEGER NOT NULL REFERENCES exercise_sets(id) ON DELETE CASCADE,
    severity    TEXT NOT NULL CHECK (severity IN ('suggestion', 'warning', 'stop')),
    status      TEXT NOT NULL,
    message     TEXT NOT NULL,
    body_part   TEXT,
    timestamp   TEXT NOT NULL,
    frame_num   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_form_set ON form_events(set_id, timestamp, frame_num);

CREATE TABLE IF NOT EXISTS control_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind                TEXT NOT NULL CHECK (kind IN ('switch', 'reset')),
    from_exercise       TEXT,
    to_exercise         TEXT,
    rep_count_at_reset  INTEGER,
    timestamp           TEXT NOT NULL,
    frame_num           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_control_session ON control_events(session_id, timestamp, frame_num);

CREATE TABLE IF NOT EXISTS frame_samples (
    set_id      INTEGER NOT NULL REFERENCES exercise_sets(id) ON DELETE CASCADE,
    frame_num   INTEGER NOT NULL,
    timestamp   TEXT NOT NULL,
    angle       REAL NOT NULL,
    state       TEXT NOT NULL,
    rep_count   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_frame_samples_set_frame ON frame_samples(set_id, frame_num);

CREATE TABLE IF NOT EXISTS exports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    format      TEXT NOT NULL CHECK (format IN ('pta_log', 'observation_json', 'csv_report', 'text_log')),
    path        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_ledger (
    file_sha256  TEXT PRIMARY KEY,
    source_path  TEXT NOT NULL,
    session_id   INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    outcome      TEXT NOT NULL CHECK (outcome IN ('imported', 'duplicate', 'malformed')),
    reason       TEXT,
    imported_at  TEXT NOT NULL
);
"""

# Forward-only migrations: (version, sql). Applied in order on open().
MIGRATIONS: List[tuple] = [
    (1, SCHEMA_V1_SQL),
]


def default_db_path() -> Path:
    """Database location: $PTASSIST_DB if set, else <repo>/data/ptassist.db."""
    env = os.environ.get("PTASSIST_DB")
    if env:
        return Path(env)
    return REPO_ROOT / "data" / "ptassist.db"


class SessionStore:
    """The single writer and reader of the canonical record."""

    def __init__(self, db_path: Path | str, clock: Callable[[], datetime] = datetime.now):
        self.db_path = Path(db_path)
        self.clock = clock
        self.conn: Optional[sqlite3.Connection] = None

    # ---------------------------------------------------------------- lifecycle

    def open(self) -> "SessionStore":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()
        self._ensure_builtin_patient()
        self._recover_running_sessions()
        return self

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "SessionStore":
        if self.conn is None:
            self.open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _now(self) -> str:
        return self.clock().isoformat()

    # ---------------------------------------------------------------- schema

    def _migrate(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        row = self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = row[0] or 0
        for version, sql in MIGRATIONS:
            if version <= current:
                continue
            self.conn.executescript(sql)
            self.conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, self._now()),
            )
            self.conn.commit()

    def _ensure_builtin_patient(self) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM patients WHERE id = ?", (UNASSIGNED_ID,)
        ).fetchone()
        if not exists:
            self.conn.execute(
                "INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES (?, ?, ?, ?, 1)",
                (UNASSIGNED_ID, UNASSIGNED_LABEL, "Sessions recorded without a chosen patient.", self._now()),
            )
            self.conn.commit()

    def _recover_running_sessions(self) -> None:
        """Mark sessions left 'running' by an interruption (FR-011)."""
        self._interrupt_running("recovered_on_open")

    def _interrupt_running(self, reason: str) -> None:
        rows = self.conn.execute("SELECT id, start_time FROM sessions WHERE status = 'running'").fetchall()
        for row in rows:
            end_time = self._last_activity_time(row["id"]) or row["start_time"]
            self._finish_session(row["id"], status="interrupted", end_time=end_time, reason=reason)

    # ---------------------------------------------------------------- patients (reads)

    @staticmethod
    def _row_to_patient(row: sqlite3.Row) -> Patient:
        keys = row.keys()
        return Patient(
            id=row["id"],
            label=row["label"],
            notes=row["notes"],
            created_at=row["created_at"],
            is_builtin=bool(row["is_builtin"]),
            session_count=row["session_count"] if "session_count" in keys else 0,
            last_session_at=row["last_session_at"] if "last_session_at" in keys else None,
        )

    def get_patient(self, patient_id: str) -> Optional[Patient]:
        row = self.conn.execute(
            """
            SELECT p.*, COUNT(s.id) AS session_count, MAX(s.start_time) AS last_session_at
            FROM patients p LEFT JOIN sessions s ON s.patient_id = p.id
            WHERE p.id = ? GROUP BY p.id
            """,
            (patient_id,),
        ).fetchone()
        return self._row_to_patient(row) if row else None

    def list_patients(self) -> List[Patient]:
        rows = self.conn.execute(
            """
            SELECT p.*, COUNT(s.id) AS session_count, MAX(s.start_time) AS last_session_at
            FROM patients p LEFT JOIN sessions s ON s.patient_id = p.id
            GROUP BY p.id
            ORDER BY p.is_builtin DESC, p.id COLLATE NOCASE ASC
            """
        ).fetchall()
        return [self._row_to_patient(r) for r in rows]

    # ---------------------------------------------------------------- sessions (write)

    def start_session(self, patient_id: str, source: str, source_ref: str,
                      extras: Optional[dict] = None) -> int:
        """Open a new running session. Any session still 'running' is marked interrupted first."""
        if self.get_patient(patient_id) is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        self._interrupt_running("superseded_by_new_session")
        cur = self.conn.execute(
            """
            INSERT INTO sessions (patient_id, schema_version, source, source_ref, source_extras, status, start_time)
            VALUES (?, ?, ?, ?, ?, 'running', ?)
            """,
            (patient_id, SCHEMA_VERSION, source, str(source_ref),
             json.dumps(extras) if extras else None, self._now()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def open_set(self, session_id: int, info: ExerciseSetInfo) -> int:
        ordinal = self.conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM exercise_sets WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        cur = self.conn.execute(
            """
            INSERT INTO exercise_sets (session_id, ordinal, exercise_key, exercise_name, side, target_reps,
                                       up_angle, down_angle, start_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, ordinal, info.exercise_key, info.exercise_name, info.side, int(info.target_reps),
             float(info.up_angle), float(info.down_angle), self._now()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def close_set(self, set_id: int, end_time: Optional[str] = None) -> None:
        self.conn.execute(
            "UPDATE exercise_sets SET end_time = ? WHERE id = ? AND end_time IS NULL",
            (end_time or self._now(), set_id),
        )
        self.conn.commit()

    def add_rep(self, set_id: int, rep: RepEvent) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reps (set_id, rep_number, min_angle, max_angle, rom, duration_seconds, form_score,
                              timestamp, frame_num, out_of_range)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (set_id, int(rep.rep_number), float(rep.min_angle), float(rep.max_angle), float(rep.rom),
             float(rep.duration_seconds), float(rep.form_score), rep.timestamp, int(rep.frame_num),
             int(rep.out_of_range)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_partial_rep(self, set_id: int, partial: PartialRepEvent) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO partial_reps (set_id, reason, min_angle, max_angle, rom, duration_seconds, timestamp, frame_num)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (set_id, partial.reason, float(partial.min_angle), float(partial.max_angle), float(partial.rom),
             float(partial.duration_seconds), partial.timestamp, int(partial.frame_num)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_form_event(self, set_id: int, event: FormEvent) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO form_events (set_id, severity, status, message, body_part, timestamp, frame_num)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (set_id, event.severity, event.status, event.message, event.body_part, event.timestamp,
             int(event.frame_num)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_control_event(self, session_id: int, event: ControlEvent) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO control_events (session_id, kind, from_exercise, to_exercise, rep_count_at_reset, timestamp, frame_num)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, event.kind, event.from_exercise, event.to_exercise, event.rep_count_at_reset,
             event.timestamp, int(event.frame_num)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_frame_samples(self, set_id: int, samples: List[FrameSample]) -> None:
        """Write a batch of downsampled angle observations in one transaction."""
        if not samples:
            return
        self.conn.executemany(
            "INSERT INTO frame_samples (set_id, frame_num, timestamp, angle, state, rep_count) VALUES (?, ?, ?, ?, ?, ?)",
            [(set_id, int(x.frame_num), x.timestamp, float(x.angle), x.state, int(x.rep_count)) for x in samples],
        )
        self.conn.commit()

    def end_session(self, session_id: int) -> Session:
        """Close a running session normally, computing its summary from stored events (FR-009)."""
        row = self.conn.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        if row["status"] == "running":
            now = self._now()
            last = self._last_activity_time(session_id)
            end_time = last if (last and _ts_key(last) > _ts_key(now)) else now   # never before the last event
            self._finish_session(session_id, status="completed", end_time=end_time)
        return self.load_session(session_id)

    def record_export(self, session_id: int, fmt: str, path: Path | str) -> int:
        cur = self.conn.execute(
            "INSERT INTO exports (session_id, format, path, created_at) VALUES (?, ?, ?, ?)",
            (session_id, fmt, str(path), self._now()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    # ---------------------------------------------------------------- summary helpers

    def _compute_summary(self, session_id: int) -> tuple:
        """(total_reps, avg_form_score, avg_rom) over reps not flagged out of range."""
        row = self.conn.execute(
            """
            SELECT COUNT(*), AVG(r.form_score), AVG(r.rom)
            FROM reps r JOIN exercise_sets s ON s.id = r.set_id
            WHERE s.session_id = ? AND r.out_of_range = 0
            """,
            (session_id,),
        ).fetchone()
        total = int(row[0] or 0)
        if total == 0:
            return 0, None, None
        return total, round(float(row[1]), 1), round(float(row[2]), 1)

    def _last_activity_time(self, session_id: int) -> Optional[str]:
        row = self.conn.execute(
            """
            SELECT MAX(ts) FROM (
                SELECT MAX(r.timestamp) AS ts FROM reps r JOIN exercise_sets s ON s.id = r.set_id WHERE s.session_id = ?
                UNION ALL SELECT MAX(p.timestamp) FROM partial_reps p JOIN exercise_sets s ON s.id = p.set_id WHERE s.session_id = ?
                UNION ALL SELECT MAX(f.timestamp) FROM form_events f JOIN exercise_sets s ON s.id = f.set_id WHERE s.session_id = ?
                UNION ALL SELECT MAX(c.timestamp) FROM control_events c WHERE c.session_id = ?
                UNION ALL SELECT MAX(x.timestamp) FROM frame_samples x JOIN exercise_sets s ON s.id = x.set_id WHERE s.session_id = ?
            )
            """,
            (session_id,) * 5,
        ).fetchone()
        return row[0]

    def _finish_session(self, session_id: int, status: str, end_time: str, reason: Optional[str] = None) -> None:
        start_time = self.conn.execute("SELECT start_time FROM sessions WHERE id = ?", (session_id,)).fetchone()[0]
        total, avg_form, avg_rom = self._compute_summary(session_id)
        duration = (datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)).total_seconds()
        self.conn.execute(
            """
            UPDATE sessions SET status = ?, end_time = ?, total_reps = ?, avg_form_score = ?, avg_rom = ?,
                                duration_seconds = ?, interrupted_reason = ?
            WHERE id = ?
            """,
            (status, end_time, total, avg_form, avg_rom, round(max(duration, 0.0), 3), reason, session_id),
        )
        self.conn.execute(
            "UPDATE exercise_sets SET end_time = ? WHERE session_id = ? AND end_time IS NULL",
            (end_time, session_id),
        )
        self.conn.commit()

    # ---------------------------------------------------------------- sessions (read)

    def load_session(self, session_id: int) -> Session:
        """Load the full object graph for one session."""
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        session = Session(
            id=row["id"], patient_id=row["patient_id"], schema_version=row["schema_version"],
            source=row["source"], source_ref=row["source_ref"], status=row["status"],
            start_time=row["start_time"], end_time=row["end_time"],
            source_extras=json.loads(row["source_extras"]) if row["source_extras"] else None,
            total_reps=row["total_reps"], avg_form_score=row["avg_form_score"], avg_rom=row["avg_rom"],
            duration_seconds=row["duration_seconds"], interrupted_reason=row["interrupted_reason"],
        )
        for s in self.conn.execute("SELECT * FROM exercise_sets WHERE session_id = ? ORDER BY ordinal", (session_id,)):
            es = ExerciseSet(
                id=s["id"], session_id=s["session_id"], ordinal=s["ordinal"], exercise_key=s["exercise_key"],
                exercise_name=s["exercise_name"], side=s["side"], target_reps=s["target_reps"],
                up_angle=s["up_angle"], down_angle=s["down_angle"], start_time=s["start_time"], end_time=s["end_time"],
            )
            es.reps = [
                RepEvent(rep_number=r["rep_number"], min_angle=r["min_angle"], max_angle=r["max_angle"], rom=r["rom"],
                         duration_seconds=r["duration_seconds"], form_score=r["form_score"], timestamp=r["timestamp"],
                         frame_num=r["frame_num"], id=r["id"], set_id=r["set_id"])
                for r in self.conn.execute("SELECT * FROM reps WHERE set_id = ? ORDER BY timestamp, frame_num, id", (es.id,))
            ]
            es.partial_reps = [
                PartialRepEvent(reason=p["reason"], min_angle=p["min_angle"], max_angle=p["max_angle"], rom=p["rom"],
                                duration_seconds=p["duration_seconds"], timestamp=p["timestamp"], frame_num=p["frame_num"],
                                id=p["id"], set_id=p["set_id"])
                for p in self.conn.execute("SELECT * FROM partial_reps WHERE set_id = ? ORDER BY timestamp, frame_num, id", (es.id,))
            ]
            es.form_events = [
                FormEvent(severity=f["severity"], status=f["status"], message=f["message"], timestamp=f["timestamp"],
                          frame_num=f["frame_num"], body_part=f["body_part"], id=f["id"], set_id=f["set_id"])
                for f in self.conn.execute("SELECT * FROM form_events WHERE set_id = ? ORDER BY timestamp, frame_num, id", (es.id,))
            ]
            es.samples = [
                FrameSample(frame_num=x["frame_num"], timestamp=x["timestamp"], angle=x["angle"], state=x["state"],
                            rep_count=x["rep_count"], set_id=x["set_id"])
                for x in self.conn.execute("SELECT * FROM frame_samples WHERE set_id = ? ORDER BY frame_num", (es.id,))
            ]
            session.sets.append(es)
        session.control_events = [
            ControlEvent(kind=c["kind"], timestamp=c["timestamp"], frame_num=c["frame_num"],
                         from_exercise=c["from_exercise"], to_exercise=c["to_exercise"],
                         rep_count_at_reset=c["rep_count_at_reset"], id=c["id"], session_id=c["session_id"])
            for c in self.conn.execute(
                "SELECT * FROM control_events WHERE session_id = ? ORDER BY timestamp, frame_num, id", (session_id,))
        ]
        return session

    # ---------------------------------------------------------------- patients (write)

    def add_patient(self, patient_id: str, label: Optional[str] = None,
                    notes: Optional[str] = None) -> Patient:
        """Register a pseudonymous patient. Raises PatientValidationError / DuplicatePatientError."""
        pid = validate_patient_id(patient_id)
        label = validate_label(label)
        if self.conn.execute("SELECT 1 FROM patients WHERE id = ?", (pid,)).fetchone():
            raise DuplicatePatientError(f"Patient ID '{pid}' is already in use (IDs are case-insensitive)")
        self.conn.execute(
            "INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES (?, ?, ?, ?, 0)",
            (pid, label, (notes or None), self._now()),
        )
        self.conn.commit()
        return self.get_patient(pid)

    def update_patient(self, patient_id: str, label: Optional[str] = None,
                       notes: Optional[str] = None) -> Patient:
        """Change label and/or notes; a None argument leaves that field unchanged."""
        current = self.get_patient(patient_id)
        if current is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        new_label = current.label if label is None else validate_label(label)
        new_notes = current.notes if notes is None else (notes or None)
        self.conn.execute("UPDATE patients SET label = ?, notes = ? WHERE id = ?",
                          (new_label, new_notes, current.id))
        self.conn.commit()
        return self.get_patient(current.id)

    def delete_patient(self, patient_id: str) -> DeleteReport:
        """Remove the patient and everything tied to them, including export files (FR-017)."""
        current = self.get_patient(patient_id)
        if current is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        if current.is_builtin:
            raise BuiltinPatientError("The built-in 'unassigned' patient cannot be deleted")
        pid = current.id
        sessions = [r[0] for r in self.conn.execute("SELECT id FROM sessions WHERE patient_id = ?", (pid,))]
        events = 0
        export_paths: List[str] = []
        if sessions:
            marks = ",".join("?" * len(sessions))
            for sql in (
                f"SELECT COUNT(*) FROM reps r JOIN exercise_sets s ON s.id = r.set_id WHERE s.session_id IN ({marks})",
                f"SELECT COUNT(*) FROM partial_reps p JOIN exercise_sets s ON s.id = p.set_id WHERE s.session_id IN ({marks})",
                f"SELECT COUNT(*) FROM form_events f JOIN exercise_sets s ON s.id = f.set_id WHERE s.session_id IN ({marks})",
                f"SELECT COUNT(*) FROM control_events WHERE session_id IN ({marks})",
            ):
                events += self.conn.execute(sql, sessions).fetchone()[0]
            export_paths = [r[0] for r in self.conn.execute(
                f"SELECT path FROM exports WHERE session_id IN ({marks})", sessions)]
        self.conn.execute("DELETE FROM patients WHERE id = ?", (pid,))   # cascades through every child table
        self.conn.commit()
        removed_files = 0
        for path in export_paths:
            try:
                Path(path).unlink()
                removed_files += 1
            except FileNotFoundError:
                continue
        return DeleteReport(patient_id=pid, sessions=len(sessions), events=events, export_files=removed_files)

    def reassign_session(self, session_id: int, patient_id: str) -> None:
        target = self.get_patient(patient_id)
        if target is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        if self.conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        self.conn.execute("UPDATE sessions SET patient_id = ? WHERE id = ?", (target.id, session_id))
        self.conn.commit()

    # ---------------------------------------------------------------- history and event log

    def list_sessions(self, patient_id: Optional[str] = None) -> List[SessionSummaryRow]:
        """Sessions newest first, with the exercises performed and summary numbers."""
        if patient_id is None:
            rows = self.conn.execute("SELECT * FROM sessions ORDER BY start_time DESC, id DESC").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM sessions WHERE patient_id = ? ORDER BY start_time DESC, id DESC", (patient_id,)
            ).fetchall()
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        marks = ",".join("?" * len(ids))
        names: dict = {}
        for s in self.conn.execute(
            f"SELECT session_id, exercise_name FROM exercise_sets WHERE session_id IN ({marks}) ORDER BY session_id, ordinal",
            ids,
        ):
            names.setdefault(s["session_id"], []).append(s["exercise_name"])
        return [
            SessionSummaryRow(
                id=r["id"], patient_id=r["patient_id"], start_time=r["start_time"], end_time=r["end_time"],
                source=r["source"], status=r["status"], exercises=names.get(r["id"], []),
                total_reps=r["total_reps"], avg_form_score=r["avg_form_score"],
            )
            for r in rows
        ]

    def session_ordinal(self, session_id: int) -> int:
        """1-based position of the session among its patient's sessions (PTA-Log file numbering)."""
        row = self.conn.execute("SELECT patient_id, start_time FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE patient_id = ? AND (start_time < ? OR (start_time = ? AND id <= ?))",
            (row["patient_id"], row["start_time"], row["start_time"], session_id),
        ).fetchone()[0]

    # Ordering of rows that share a timestamp and frame (mirrors the legacy loop order).
    _RANK = {"session_start": -1, "sample": 0, "rep": 1, "partial_rep": 2, "form": 3, "switch": 4, "reset": 5, "session_end": 9}

    def event_log(self, session_id: int) -> List[LogRow]:
        """Chronological union of every event plus synthetic session_start / session_end rows."""
        session = self.load_session(session_id)
        rows: List[LogRow] = []
        first = session.sets[0] if session.sets else None
        rows.append(LogRow("session_start", session.start_time, 0, first.ordinal if first else None, {
            "exercise": first.exercise_name if first else None,
            "target_reps": first.target_reps if first else None,
            "side": first.side if first else None,
            "source": session.source, "source_ref": session.source_ref,
        }))
        for es in session.sets:
            for r in es.reps:
                rows.append(LogRow("rep", r.timestamp, r.frame_num, es.ordinal, {
                    "rep_number": r.rep_number, "exercise": es.exercise_name, "min_angle": r.min_angle,
                    "max_angle": r.max_angle, "rom": r.rom, "duration_seconds": r.duration_seconds,
                    "form_score": r.form_score, "out_of_range": r.out_of_range}))
            for pr in es.partial_reps:
                rows.append(LogRow("partial_rep", pr.timestamp, pr.frame_num, es.ordinal, {
                    "reason": pr.reason, "exercise": es.exercise_name, "min_angle": pr.min_angle,
                    "max_angle": pr.max_angle, "rom": pr.rom, "duration_seconds": pr.duration_seconds}))
            for f in es.form_events:
                rows.append(LogRow("form", f.timestamp, f.frame_num, es.ordinal, {
                    "severity": f.severity, "status": f.status, "message": f.message,
                    "body_part": f.body_part, "exercise": es.exercise_name}))
        for c in session.control_events:
            es = self._set_open_at(session, c.timestamp, closing=c.from_exercise if c.kind == "switch" else None)
            data = {"exercise": es.exercise_name if es else None}
            if c.kind == "switch":
                data.update({"from_exercise": c.from_exercise, "to_exercise": c.to_exercise})
            else:
                data.update({"rep_count_at_reset": c.rep_count_at_reset})
            rows.append(LogRow(c.kind, c.timestamp, c.frame_num, es.ordinal if es else None, data))
        if session.status != "running" and session.end_time:
            rows.append(LogRow("session_end", session.end_time, 10 ** 9, None, {
                "total_reps": session.total_reps, "avg_form_score": session.avg_form_score,
                "avg_rom": session.avg_rom, "duration_seconds": session.duration_seconds,
                "status": session.status}))
        rows.sort(key=lambda r: (_ts_key(r.timestamp), r.frame_num, self._RANK.get(r.type, 8)))
        return rows

    @staticmethod
    def _set_open_at(session: Session, timestamp: str, closing: Optional[str] = None):
        """The exercise set open at `timestamp`: the last set started at or before it.

        For a switch, `closing` names the exercise being left, so the event attaches to
        the set it closed rather than the one that opened at the same instant.
        """
        key = _ts_key(timestamp)
        candidates = [es for es in session.sets if _ts_key(es.start_time) <= key]
        if closing is not None:
            named = [es for es in candidates if es.exercise_name == closing]
            if named:
                return named[-1]
        if candidates:
            return candidates[-1]
        return session.sets[0] if session.sets else None

    # ---------------------------------------------------------------- legacy import support

    def import_session(self, patient_id: str, source: str, source_ref: str, start_time: str,
                       end_time: Optional[str], sets: List[dict], control_events: List[ControlEvent],
                       status: str = "completed") -> int:
        """Create a finished session from parsed legacy data (importer only).

        `sets` items: {"info": ExerciseSetInfo, "start_time", "end_time", "reps": [RepEvent],
        "partial_reps": [PartialRepEvent], "form_events": [FormEvent]}.
        """
        if self.get_patient(patient_id) is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        cur = self.conn.execute(
            """
            INSERT INTO sessions (patient_id, schema_version, source, source_ref, status, start_time)
            VALUES (?, ?, ?, ?, 'running', ?)
            """,
            (patient_id, SCHEMA_VERSION, source, source_ref, start_time),
        )
        sid = int(cur.lastrowid)
        for ordinal, item in enumerate(sets, 1):
            info: ExerciseSetInfo = item["info"]
            c2 = self.conn.execute(
                """
                INSERT INTO exercise_sets (session_id, ordinal, exercise_key, exercise_name, side, target_reps,
                                           up_angle, down_angle, start_time, end_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, ordinal, info.exercise_key, info.exercise_name, info.side, int(info.target_reps),
                 float(info.up_angle), float(info.down_angle), item["start_time"], item.get("end_time")),
            )
            set_id = int(c2.lastrowid)
            for rep in item.get("reps", []):
                self.add_rep(set_id, rep)
            for partial in item.get("partial_reps", []):
                self.add_partial_rep(set_id, partial)
            for fe in item.get("form_events", []):
                self.add_form_event(set_id, fe)
        for c in control_events:
            self.add_control_event(sid, c)
        self.conn.commit()
        self._finish_session(sid, status=status, end_time=end_time or self._last_activity_time(sid) or start_time)
        return sid

    def imported_session_keys(self) -> set:
        """(first exercise name lower, start time to the second, total reps) of every imported session."""
        keys = set()
        rows = self.conn.execute(
            "SELECT id, start_time, total_reps FROM sessions WHERE source_ref = 'legacy-import'").fetchall()
        for r in rows:
            first = self.conn.execute(
                "SELECT exercise_name FROM exercise_sets WHERE session_id = ? ORDER BY ordinal LIMIT 1", (r["id"],)
            ).fetchone()
            keys.add(((first["exercise_name"] if first else "").lower(), (r["start_time"] or "")[:19], int(r["total_reps"] or 0)))
        return keys

    def ledger_lookup(self, sha256: str) -> Optional[LedgerRow]:
        row = self.conn.execute("SELECT * FROM import_ledger WHERE file_sha256 = ?", (sha256,)).fetchone()
        if row is None:
            return None
        return LedgerRow(file_sha256=row["file_sha256"], source_path=row["source_path"], session_id=row["session_id"],
                         outcome=row["outcome"], imported_at=row["imported_at"], reason=row["reason"])

    def ledger_add(self, row: LedgerRow) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO import_ledger (file_sha256, source_path, session_id, outcome, reason, imported_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (row.file_sha256, row.source_path, row.session_id, row.outcome, row.reason, row.imported_at or self._now()),
        )
        self.conn.commit()


def _ts_key(ts: Optional[str]):
    """Sort key for ISO timestamps that may or may not carry microseconds."""
    if not ts:
        return datetime.min
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.min
