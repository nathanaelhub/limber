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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional

from .privacy import validate_label, validate_notes, validate_patient_id
from . import thresholds
from .models import (
    PTLogError,
    Media,
    Entry,
    Message,
    AccessStatus,
    AuditEntry,
    PortalError,
    PortalSignIn,
    ThresholdChange,
    ThresholdValidationError,
    ADHERENCE_THRESHOLD_DEFAULT,
    GAP_DAYS_DEFAULT,
    Assignment,
    AssignmentValidationError,
    Discharge,
    NEXT_STEPS,
    UNASSIGNED_ID,
    UNASSIGNED_LABEL,
    BuiltinPatientError,
    Goal,
    GoalValidationError,
    Review,
    ReviewValidationError,
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
SCHEMA_VERSION = 10

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

SCHEMA_V2_SQL = """
CREATE TABLE IF NOT EXISTS reviews (
    session_id   INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    reviewed_at  TEXT NOT NULL,
    notes        TEXT,
    next_step    TEXT NOT NULL CHECK (next_step IN ('continue', 'progress', 'regress', 'hold'))
);

CREATE TABLE IF NOT EXISTS goals (
    patient_id     TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    exercise_name  TEXT NOT NULL,
    target_rom     REAL CHECK (target_rom IS NULL OR (target_rom >= 1 AND target_rom <= 180)),
    target_reps    INTEGER CHECK (target_reps IS NULL OR target_reps >= 1),
    set_at         TEXT NOT NULL,
    PRIMARY KEY (patient_id, exercise_name),
    CHECK (target_rom IS NOT NULL OR target_reps IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS review_settings (
    patient_id  TEXT PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    gap_days    INTEGER NOT NULL DEFAULT 7 CHECK (gap_days BETWEEN 1 AND 90)
);

CREATE TABLE IF NOT EXISTS review_exports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    format      TEXT NOT NULL CHECK (format IN ('review_report', 'review_csv')),
    period      TEXT NOT NULL,
    path        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""

# Forward-only migrations: (version, sql). Applied in order on open().
SCHEMA_V3_SQL = """
CREATE TABLE IF NOT EXISTS assignments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id         TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    program_id         TEXT NOT NULL,
    program_name       TEXT NOT NULL,
    exercise_keys      TEXT NOT NULL,
    sessions_per_week  INTEGER NOT NULL CHECK (sessions_per_week BETWEEN 1 AND 14),
    start_date         TEXT NOT NULL,
    end_date           TEXT,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assignments_patient ON assignments(patient_id, start_date);

CREATE TABLE IF NOT EXISTS discharges (
    patient_id     TEXT PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    discharged_on  TEXT NOT NULL,
    reason         TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracker_settings (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    adherence_threshold  INTEGER NOT NULL DEFAULT 60 CHECK (adherence_threshold BETWEEN 1 AND 100)
);
INSERT OR IGNORE INTO tracker_settings (id, adherence_threshold) VALUES (1, 60);
"""

# v4 (feature 005): attention thresholds. The old per-patient gap and installation adherence
# settings are copied; their tables stay in place and are no longer read.
SCHEMA_V4_SQL = """
CREATE TABLE IF NOT EXISTS patient_thresholds (
    patient_id  TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    key         TEXT NOT NULL,
    value       INTEGER NOT NULL CHECK (typeof(value) = 'integer'),
    PRIMARY KEY (patient_id, key)
);
CREATE TABLE IF NOT EXISTS installation_thresholds (
    key    TEXT PRIMARY KEY,
    value  INTEGER NOT NULL CHECK (typeof(value) = 'integer')
);
INSERT OR IGNORE INTO patient_thresholds (patient_id, key, value)
    SELECT patient_id, 'practice_gap', gap_days FROM review_settings;
INSERT OR IGNORE INTO installation_thresholds (key, value)
    SELECT 'adherence', adherence_threshold FROM tracker_settings WHERE adherence_threshold <> 60;
"""

# v5 (feature 006): per-exercise threshold overrides and the history of threshold changes.
SCHEMA_V5_SQL = """
CREATE TABLE IF NOT EXISTS exercise_thresholds (
    patient_id     TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    exercise_name  TEXT NOT NULL,
    key            TEXT NOT NULL,
    value          INTEGER NOT NULL CHECK (typeof(value) = 'integer'),
    PRIMARY KEY (patient_id, exercise_name, key)
);
CREATE TABLE IF NOT EXISTS threshold_changes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at     TEXT NOT NULL,
    scope          TEXT NOT NULL CHECK (scope IN ('patient', 'exercise', 'installation')),
    patient_id     TEXT REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    exercise_name  TEXT,
    key            TEXT NOT NULL,
    old_value      INTEGER,
    new_value      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_threshold_changes_patient ON threshold_changes(patient_id, id);
"""

# v6 (feature 007): the patient portal's access codes, sign-ins, and access history.
SCHEMA_V6_SQL = """
CREATE TABLE IF NOT EXISTS portal_access (
    patient_id    TEXT PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    code_lookup   TEXT NOT NULL UNIQUE,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    revoked_at    TEXT,
    last_used_at  TEXT
);
CREATE TABLE IF NOT EXISTS portal_sessions (
    token_hash    TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    created_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portal_sessions_patient ON portal_sessions(patient_id);
CREATE TABLE IF NOT EXISTS portal_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    patient_id  TEXT REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    event       TEXT NOT NULL CHECK (event IN ('code_created', 'code_revoked', 'login_ok', 'login_failed',
                'locked_out', 'logout', 'live_start', 'live_end', 'live_interrupted', 'live_refused')),
    client      TEXT,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_portal_audit_patient ON portal_audit(patient_id, id);
"""

# v7 (feature 007, US6): the therapist password, therapist sign-ins and single-use passes, and their history.
SCHEMA_V7_SQL = """
CREATE TABLE IF NOT EXISTS portal_admin (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    salt           TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_signins (
    token_hash  TEXT PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('pass', 'signin')),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_audit (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,
    event   TEXT NOT NULL CHECK (event IN ('password_set', 'password_cleared', 'login_ok', 'login_failed',
            'locked_out', 'logout')),
    client  TEXT
);
"""

# v8 (feature 008): one conversation per patient with the therapist.
SCHEMA_V8_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    patient_id  TEXT PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    enabled     INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    sender      TEXT NOT NULL CHECK (sender IN ('patient', 'therapist')),
    body        TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    read_at     TEXT,
    removed_at  TEXT,
    warned      INTEGER NOT NULL DEFAULT 0 CHECK (warned IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_messages_patient ON messages(patient_id, id);
CREATE TABLE IF NOT EXISTS message_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    patient_id  TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    event       TEXT NOT NULL CHECK (event IN ('enabled', 'disabled', 'sent', 'sent_despite_warning', 'read', 'removed')),
    sender      TEXT,
    message_id  INTEGER
);
"""

# v9 (feature 010): patient-reported entries, and new access-history events. SQLite cannot alter a
# CHECK constraint, so portal_audit is rebuilt by the documented recipe: foreign keys off (outside a
# transaction), copy, drop, rename, check. A test upgrades a real v8 record and counts every row.
SCHEMA_V9_SQL = """
PRAGMA foreign_keys=OFF;
BEGIN;
CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('checkin', 'questionnaire', 'medication', 'sleep')),
    schema_version INTEGER NOT NULL DEFAULT 1,
    recorded_at   TEXT NOT NULL,
    received_at   TEXT NOT NULL,
    phase         TEXT NOT NULL CHECK (phase IN ('before', 'after', 'standalone')),
    session_id    INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    score         REAL,
    payload       TEXT NOT NULL,
    client_id     TEXT NOT NULL,
    warned        INTEGER NOT NULL DEFAULT 0 CHECK (warned IN (0, 1)),
    time_adjusted INTEGER NOT NULL DEFAULT 0 CHECK (time_adjusted IN (0, 1)),
    note_removed  INTEGER NOT NULL DEFAULT 0 CHECK (note_removed IN (0, 1)),
    reviewed_at   TEXT,
    UNIQUE (patient_id, client_id)
);
CREATE INDEX IF NOT EXISTS idx_entries_patient_time ON entries(patient_id, kind, recorded_at);
CREATE TABLE portal_audit_v9 (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    patient_id  TEXT REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    event       TEXT NOT NULL CHECK (event IN ('code_created', 'code_revoked', 'login_ok', 'login_failed',
                'locked_out', 'logout', 'live_start', 'live_end', 'live_interrupted', 'live_refused',
                'entry_stored', 'entry_note_removed')),
    client      TEXT,
    detail      TEXT
);
INSERT INTO portal_audit_v9 (id, at, patient_id, event, client, detail)
    SELECT id, at, patient_id, event, client, detail FROM portal_audit;
DROP TABLE portal_audit;
ALTER TABLE portal_audit_v9 RENAME TO portal_audit;
CREATE INDEX IF NOT EXISTS idx_portal_audit_patient ON portal_audit(patient_id, id);
COMMIT;
PRAGMA foreign_keys=ON;
"""

# v10 (feature 011): media uploads. Files live under data/media/<patient>/<id>.<ext>; these rows
# are their only index. The access-history table is rebuilt again for the media events.
SCHEMA_V10_SQL = """
PRAGMA foreign_keys=OFF;
BEGIN;
CREATE TABLE IF NOT EXISTS media (
    id            TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('clip', 'voice')),
    ext           TEXT NOT NULL,
    container     TEXT NOT NULL,
    codec         TEXT NOT NULL,
    bytes         INTEGER NOT NULL,
    duration      REAL NOT NULL,
    width         INTEGER NOT NULL DEFAULT 0,
    height        INTEGER NOT NULL DEFAULT 0,
    sha256        TEXT NOT NULL,
    caption       TEXT NOT NULL DEFAULT '',
    warned        INTEGER NOT NULL DEFAULT 0 CHECK (warned IN (0, 1)),
    created_at    TEXT NOT NULL,
    reviewed_at   TEXT,
    deleted_at    TEXT,
    deleted_by    TEXT CHECK (deleted_by IN ('patient', 'therapist', 'retention', 'missing')),
    message_id    INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    backed_up_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_media_patient ON media(patient_id, created_at);
CREATE TABLE IF NOT EXISTS media_uploads (
    id            TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('clip', 'voice')),
    total_bytes   INTEGER NOT NULL,
    chunk_bytes   INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);
CREATE TABLE portal_audit_v10 (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    patient_id  TEXT REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    event       TEXT NOT NULL CHECK (event IN ('code_created', 'code_revoked', 'login_ok', 'login_failed',
                'locked_out', 'logout', 'live_start', 'live_end', 'live_interrupted', 'live_refused',
                'entry_stored', 'entry_note_removed',
                'upload_started', 'upload_stored', 'upload_rejected', 'media_viewed', 'media_reviewed',
                'media_deleted')),
    client      TEXT,
    detail      TEXT
);
INSERT INTO portal_audit_v10 (id, at, patient_id, event, client, detail)
    SELECT id, at, patient_id, event, client, detail FROM portal_audit;
DROP TABLE portal_audit;
ALTER TABLE portal_audit_v10 RENAME TO portal_audit;
CREATE INDEX IF NOT EXISTS idx_portal_audit_patient ON portal_audit(patient_id, id);
COMMIT;
PRAGMA foreign_keys=ON;
"""

MIGRATIONS: List[tuple] = [
    (1, SCHEMA_V1_SQL),
    (2, SCHEMA_V2_SQL),
    (3, SCHEMA_V3_SQL),
    (4, SCHEMA_V4_SQL),
    (5, SCHEMA_V5_SQL),
    (6, SCHEMA_V6_SQL),
    (7, SCHEMA_V7_SQL),
    (8, SCHEMA_V8_SQL),
    (9, SCHEMA_V9_SQL),
    (10, SCHEMA_V10_SQL),
]


def default_db_path() -> Path:
    """Database location: $PTASSIST_DB if set, else <repo>/data/ptassist.db."""
    env = os.environ.get("PTASSIST_DB")
    if env:
        return Path(env)
    return REPO_ROOT / "data" / "ptassist.db"


class SessionStore:
    """The single writer and reader of the canonical record."""

    def __init__(self, db_path: Path | str, clock: Callable[[], datetime] = datetime.now,
                 check_same_thread: bool = True, media_dir: Optional[Path] = None):
        self.db_path = Path(db_path)
        self.media_dir = Path(media_dir) if media_dir else self.db_path.parent / "media"     # uploaded clips (feature 011)
        self.clock = clock
        # False only for the live web session, whose callbacks run on worker threads (the caller locks).
        self.check_same_thread = check_same_thread
        self.conn: Optional[sqlite3.Connection] = None

    # ---------------------------------------------------------------- lifecycle

    def open(self) -> "SessionStore":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=5.0, check_same_thread=self.check_same_thread)
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
        self._interrupt_running("recovered_on_open", skip_living_owner=True)

    def _interrupt_running(self, reason: str, skip_living_owner: bool = False,
                           patient_id: Optional[str] = None) -> None:
        """Mark running sessions interrupted: all of them (recovery on open), or one patient's."""
        sql, args = "SELECT id, start_time, source_extras FROM sessions WHERE status = 'running'", ()
        if patient_id is not None:
            sql, args = sql + " AND patient_id = ?", (patient_id,)
        rows = self.conn.execute(sql, args).fetchall()
        for row in rows:
            if skip_living_owner and _owner_alive(row["source_extras"]):
                continue   # still being recorded by a living process (live web session)
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
        """Open a new running session. The same patient's running sessions are marked interrupted
        first; other patients' sessions are left alone, so two people can exercise at once
        (feature 007 changed feature 004's one-per-installation rule to one per patient)."""
        if self.get_patient(patient_id) is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        self._interrupt_running("superseded_by_new_session", patient_id=patient_id)
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

    def last_activity_time(self, session_id: int) -> Optional[str]:
        """Timestamp of the latest stored event or sample of a session (None when it has none)."""
        return self._last_activity_time(session_id)

    def interrupt_session(self, session_id: int, reason: str) -> None:
        """Mark one running session interrupted; a no-op for a session already finished."""
        row = self.conn.execute("SELECT status, start_time FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        if row["status"] == "running":
            end_time = self._last_activity_time(session_id) or row["start_time"]
            self._finish_session(session_id, status="interrupted", end_time=end_time, reason=reason)

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
        export_paths += [r[0] for r in self.conn.execute(
            "SELECT path FROM review_exports WHERE patient_id = ?", (pid,))]
        media_files = self.conn.execute("SELECT COUNT(*) FROM media WHERE patient_id = ? AND deleted_at IS NULL", (pid,)).fetchone()[0]
        self.conn.execute("DELETE FROM patients WHERE id = ?", (pid,))   # cascades through every child table
        self.conn.commit()
        import shutil
        shutil.rmtree(self.media_dir / pid, ignore_errors=True)         # the patient's uploaded files (feature 011)
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
                origin="home" if '"origin": "portal"' in (r["source_extras"] or "") else "clinic",
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

    # ---------------------------------------------------------------- review over time (feature 002)

    def set_goal(self, patient_id: str, exercise_name: str, target_rom: Optional[float] = None,
                 target_reps: Optional[int] = None) -> Goal:
        """Set or update a goal; a None argument keeps the existing value (FR-019)."""
        patient = self.get_patient(patient_id)
        if patient is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        current = self.get_goal(patient.id, exercise_name)
        rom = current.target_rom if (target_rom is None and current) else target_rom
        reps = current.target_reps if (target_reps is None and current) else target_reps
        if rom is not None and not (1 <= float(rom) <= 180):
            raise GoalValidationError("target_rom must be 1–180 degrees")
        if reps is not None and int(reps) < 1:
            raise GoalValidationError("target_reps must be at least 1")
        if rom is None and reps is None:
            raise GoalValidationError("a goal needs at least one target (range of motion or reps)")
        self.conn.execute(
            "INSERT OR REPLACE INTO goals (patient_id, exercise_name, target_rom, target_reps, set_at) VALUES (?, ?, ?, ?, ?)",
            (patient.id, exercise_name, float(rom) if rom is not None else None,
             int(reps) if reps is not None else None, self._now()),
        )
        self.conn.commit()
        return self.get_goal(patient.id, exercise_name)

    def get_goal(self, patient_id: str, exercise_name: str) -> Optional[Goal]:
        row = self.conn.execute(
            "SELECT * FROM goals WHERE patient_id = ? AND exercise_name = ?", (patient_id, exercise_name)).fetchone()
        return Goal(row["patient_id"], row["exercise_name"], row["target_rom"], row["target_reps"], row["set_at"]) if row else None

    def list_goals(self, patient_id: str) -> List[Goal]:
        rows = self.conn.execute(
            "SELECT * FROM goals WHERE patient_id = ? ORDER BY exercise_name COLLATE NOCASE", (patient_id,)).fetchall()
        return [Goal(r["patient_id"], r["exercise_name"], r["target_rom"], r["target_reps"], r["set_at"]) for r in rows]

    def clear_goal(self, patient_id: str, exercise_name: str) -> bool:
        cur = self.conn.execute("DELETE FROM goals WHERE patient_id = ? AND exercise_name = ?", (patient_id, exercise_name))
        self.conn.commit()
        return cur.rowcount > 0

    def get_gap_days(self, patient_id: str) -> int:
        """The practice-gap threshold in use for the patient (days)."""
        return self.effective_thresholds(patient_id).practice_gap

    def set_gap_days(self, patient_id: str, days: int) -> int:
        return self.set_patient_threshold(patient_id, "practice_gap", days)

    # ---------------------------------------------------------------- attention thresholds (feature 005)

    def _require_patient(self, patient_id: str) -> None:
        if self.get_patient(patient_id) is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")

    def _log_change(self, scope: str, patient_id: Optional[str], exercise_name: Optional[str],
                    key: str, old: Optional[int], new: Optional[int]) -> None:
        """One history row per effective change; the caller commits it together with the change."""
        if old == new:
            return
        self.conn.execute(
            "INSERT INTO threshold_changes (changed_at, scope, patient_id, exercise_name, key, old_value, new_value) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (self._now(), scope, patient_id, exercise_name, key, old, new))

    def _known_key(self, key: str) -> None:
        if key not in thresholds.THRESHOLDS:
            thresholds.validate(key, 0)                       # raises with the list of known keys

    # patient level

    def get_patient_thresholds(self, patient_id: str) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT key, value FROM patient_thresholds WHERE patient_id = ? ORDER BY key", (patient_id,)).fetchall()
        return {r["key"]: int(r["value"]) for r in rows}

    def set_patient_thresholds(self, patient_id: str, values: Dict[str, Any]) -> Dict[str, int]:
        """Validate every pair, then write them all (nothing is written when one is invalid)."""
        checked = {key: thresholds.validate(key, value) for key, value in values.items()}
        self._require_patient(patient_id)
        stored = self.get_patient_thresholds(patient_id)
        for key, number in checked.items():
            self.conn.execute("INSERT OR REPLACE INTO patient_thresholds (patient_id, key, value) VALUES (?, ?, ?)",
                              (patient_id, key, number))
            self._log_change("patient", patient_id, None, key, stored.get(key), number)
        self.conn.commit()
        return checked

    def set_patient_threshold(self, patient_id: str, key: str, value) -> int:
        return self.set_patient_thresholds(patient_id, {key: value})[key]

    def reset_patient_threshold(self, patient_id: str, key: str) -> bool:
        self._known_key(key)
        self._require_patient(patient_id)
        old = self.get_patient_thresholds(patient_id).get(key)
        if old is None:
            return False
        self.conn.execute("DELETE FROM patient_thresholds WHERE patient_id = ? AND key = ?", (patient_id, key))
        self._log_change("patient", patient_id, None, key, old, None)
        self.conn.commit()
        return True

    def reset_patient_thresholds(self, patient_id: str) -> int:
        """Remove every override of the patient, exercise overrides included. Returns how many were removed."""
        self._require_patient(patient_id)
        removed = 0
        for key, old in self.get_patient_thresholds(patient_id).items():
            self._log_change("patient", patient_id, None, key, old, None)
            removed += 1
        for exercise_name, values in self.get_exercise_thresholds(patient_id).items():
            for key, old in values.items():
                self._log_change("exercise", patient_id, exercise_name, key, old, None)
                removed += 1
        self.conn.execute("DELETE FROM patient_thresholds WHERE patient_id = ?", (patient_id,))
        self.conn.execute("DELETE FROM exercise_thresholds WHERE patient_id = ?", (patient_id,))
        self.conn.commit()
        return removed

    # exercise level (feature 006)

    @staticmethod
    def _exercise_name(exercise_name: str) -> str:
        name = (exercise_name or "").strip()
        if not name or len(name) > 80:
            raise ThresholdValidationError("Exercise name must be 1-80 characters")
        return name

    def get_exercise_thresholds(self, patient_id: str) -> Dict[str, Dict[str, int]]:
        rows = self.conn.execute(
            "SELECT exercise_name, key, value FROM exercise_thresholds WHERE patient_id = ? ORDER BY exercise_name, key",
            (patient_id,)).fetchall()
        result: Dict[str, Dict[str, int]] = {}
        for r in rows:
            result.setdefault(r["exercise_name"], {})[r["key"]] = int(r["value"])
        return result

    def set_exercise_thresholds(self, patient_id: str, exercise_name: str, values: Dict[str, Any]) -> Dict[str, int]:
        checked = {key: thresholds.validate_exercise_key(key, value) for key, value in values.items()}
        name = self._exercise_name(exercise_name)
        self._require_patient(patient_id)
        stored = self.get_exercise_thresholds(patient_id).get(name, {})
        for key, number in checked.items():
            self.conn.execute(
                "INSERT OR REPLACE INTO exercise_thresholds (patient_id, exercise_name, key, value) VALUES (?, ?, ?, ?)",
                (patient_id, name, key, number))
            self._log_change("exercise", patient_id, name, key, stored.get(key), number)
        self.conn.commit()
        return checked

    def set_exercise_threshold(self, patient_id: str, exercise_name: str, key: str, value) -> int:
        return self.set_exercise_thresholds(patient_id, exercise_name, {key: value})[key]

    def reset_exercise_threshold(self, patient_id: str, exercise_name: str, key: str) -> bool:
        self._known_key(key)
        self._require_patient(patient_id)
        name = self._exercise_name(exercise_name)
        old = self.get_exercise_thresholds(patient_id).get(name, {}).get(key)
        if old is None:
            return False
        self.conn.execute("DELETE FROM exercise_thresholds WHERE patient_id = ? AND exercise_name = ? AND key = ?",
                          (patient_id, name, key))
        self._log_change("exercise", patient_id, name, key, old, None)
        self.conn.commit()
        return True

    def reset_exercise_thresholds(self, patient_id: str, exercise_name: str) -> int:
        self._require_patient(patient_id)
        name = self._exercise_name(exercise_name)
        stored = self.get_exercise_thresholds(patient_id).get(name, {})
        for key, old in stored.items():
            self._log_change("exercise", patient_id, name, key, old, None)
        self.conn.execute("DELETE FROM exercise_thresholds WHERE patient_id = ? AND exercise_name = ?", (patient_id, name))
        self.conn.commit()
        return len(stored)

    # installation level

    def get_installation_thresholds(self) -> Dict[str, int]:
        rows = self.conn.execute("SELECT key, value FROM installation_thresholds ORDER BY key").fetchall()
        return {r["key"]: int(r["value"]) for r in rows}

    def set_installation_thresholds(self, values: Dict[str, Any]) -> Dict[str, int]:
        checked = {key: thresholds.validate(key, value) for key, value in values.items()}
        stored = self.get_installation_thresholds()
        for key, number in checked.items():
            self.conn.execute("INSERT OR REPLACE INTO installation_thresholds (key, value) VALUES (?, ?)", (key, number))
            self._log_change("installation", None, None, key, stored.get(key), number)
        self.conn.commit()
        return checked

    def set_installation_threshold(self, key: str, value) -> int:
        return self.set_installation_thresholds({key: value})[key]

    def reset_installation_threshold(self, key: str) -> bool:
        self._known_key(key)
        old = self.get_installation_thresholds().get(key)
        if old is None:
            return False
        self.conn.execute("DELETE FROM installation_thresholds WHERE key = ?", (key,))
        self._log_change("installation", None, None, key, old, None)
        self.conn.commit()
        return True

    def restore_builtin_thresholds(self) -> int:
        """Remove every installation value; patient overrides are untouched."""
        stored = self.get_installation_thresholds()
        for key, old in stored.items():
            self._log_change("installation", None, None, key, old, None)
        self.conn.execute("DELETE FROM installation_thresholds")
        self.conn.commit()
        return len(stored)

    # resolution

    def effective_thresholds(self, patient_id: str, exercise_name: Optional[str] = None) -> "thresholds.Thresholds":
        """The set in use for the patient, or for one of the patient's exercises."""
        self._require_patient(patient_id)
        exercise = self.get_exercise_thresholds(patient_id).get(exercise_name) if exercise_name else None
        return thresholds.resolve(self.get_patient_thresholds(patient_id), self.get_installation_thresholds(), exercise)

    def effective_thresholds_by_exercise(self, patient_id: str) -> Dict[str, "thresholds.Thresholds"]:
        """Only exercises that have an override; every other exercise uses `effective_thresholds(patient)`."""
        self._require_patient(patient_id)
        patient, installation = self.get_patient_thresholds(patient_id), self.get_installation_thresholds()
        return {name: thresholds.resolve(patient, installation, values)
                for name, values in self.get_exercise_thresholds(patient_id).items()}

    def _all_patient_values(self) -> Dict[str, Dict[str, int]]:
        per_patient: Dict[str, Dict[str, int]] = {}
        for r in self.conn.execute("SELECT patient_id, key, value FROM patient_thresholds"):
            per_patient.setdefault(r["patient_id"], {})[r["key"]] = int(r["value"])
        return per_patient

    def effective_thresholds_all(self) -> Dict[str, "thresholds.Thresholds"]:
        """The set in use for every patient, from two queries (roster and queue)."""
        installation = self.get_installation_thresholds()
        per_patient = self._all_patient_values()
        shared = thresholds.resolve(None, installation)
        ids = [r[0] for r in self.conn.execute("SELECT id FROM patients")]
        return {pid: (thresholds.resolve(per_patient[pid], installation) if pid in per_patient else shared)
                for pid in ids}

    def effective_thresholds_by_exercise_all(self) -> Dict[str, Dict[str, "thresholds.Thresholds"]]:
        """Exercise-specific sets for every patient that has any, from one pass over each table."""
        installation = self.get_installation_thresholds()
        per_patient = self._all_patient_values()
        raw: Dict[str, Dict[str, Dict[str, int]]] = {}
        for r in self.conn.execute("SELECT patient_id, exercise_name, key, value FROM exercise_thresholds"):
            raw.setdefault(r["patient_id"], {}).setdefault(r["exercise_name"], {})[r["key"]] = int(r["value"])
        return {pid: {name: thresholds.resolve(per_patient.get(pid), installation, values) for name, values in ex.items()}
                for pid, ex in raw.items()}

    def threshold_history(self, patient_id: Optional[str], limit: Optional[int] = None) -> List[ThresholdChange]:
        """Newest first. For a patient: the patient's and their exercises' changes plus installation
        changes (they alter the patient's effective values). For None: installation changes only."""
        if patient_id is None:
            sql, args = "SELECT * FROM threshold_changes WHERE scope = 'installation' ORDER BY id DESC", ()
        else:
            self._require_patient(patient_id)
            sql = "SELECT * FROM threshold_changes WHERE patient_id = ? OR scope = 'installation' ORDER BY id DESC"
            args = (patient_id,)
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [ThresholdChange(id=r["id"], changed_at=r["changed_at"], scope=r["scope"], patient_id=r["patient_id"],
                                exercise_name=r["exercise_name"], key=r["key"], old_value=r["old_value"],
                                new_value=r["new_value"]) for r in self.conn.execute(sql, args)]

    def sessions_in_period(self, patient_id: str, since: Optional[datetime]) -> List[Session]:
        """Full session graphs for a patient, oldest first, started at or after `since` (all when None)."""
        if since is None:
            rows = self.conn.execute(
                "SELECT id FROM sessions WHERE patient_id = ? ORDER BY start_time ASC, id ASC", (patient_id,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id FROM sessions WHERE patient_id = ? AND start_time >= ? ORDER BY start_time ASC, id ASC",
                (patient_id, since.isoformat())).fetchall()
        return [self.load_session(r["id"]) for r in rows]

    def exercise_names(self, patient_id: str) -> List[str]:
        """Distinct exercise names recorded for the patient, in first-seen order."""
        rows = self.conn.execute(
            """
            SELECT es.exercise_name, MIN(s.start_time) AS first_seen
            FROM exercise_sets es JOIN sessions s ON s.id = es.session_id
            WHERE s.patient_id = ? GROUP BY es.exercise_name ORDER BY first_seen ASC, es.exercise_name
            """, (patient_id,)).fetchall()
        return [r["exercise_name"] for r in rows]

    def record_review_export(self, patient_id: str, fmt: str, period: str, path: Path | str) -> int:
        cur = self.conn.execute(
            "INSERT INTO review_exports (patient_id, format, period, path, created_at) VALUES (?, ?, ?, ?, ?)",
            (patient_id, fmt, period, str(path), self._now()))
        self.conn.commit()
        return int(cur.lastrowid)

    def set_review(self, session_id: int, next_step: str, notes: Optional[str] = None) -> Review:
        """Record (or replace) the PT's review of a session (FR-008, FR-009, FR-010)."""
        if next_step not in NEXT_STEPS:
            raise ReviewValidationError(f"next step must be one of {', '.join(NEXT_STEPS)}")
        try:
            clean_notes = validate_notes(notes)
        except PTLogError as exc:
            raise ReviewValidationError(str(exc)) from exc
        if self.conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        self.conn.execute(
            "INSERT OR REPLACE INTO reviews (session_id, reviewed_at, notes, next_step) VALUES (?, ?, ?, ?)",
            (session_id, self._now(), clean_notes, next_step))
        self.conn.commit()
        return self.get_review(session_id)

    def get_review(self, session_id: int) -> Optional[Review]:
        row = self.conn.execute("SELECT * FROM reviews WHERE session_id = ?", (session_id,)).fetchone()
        return Review(row["session_id"], row["reviewed_at"], row["notes"], row["next_step"]) if row else None

    def pending_reviews(self, patient_id: str) -> List[SessionSummaryRow]:
        """Sessions of the patient without a review, newest first (FR-011)."""
        reviewed = {r[0] for r in self.conn.execute(
            "SELECT r.session_id FROM reviews r JOIN sessions s ON s.id = r.session_id WHERE s.patient_id = ?", (patient_id,))}
        return [row for row in self.list_sessions(patient_id) if row.id not in reviewed]

    # ---------------------------------------------------------------- tracker (feature 003)

    @staticmethod
    def _to_date(value) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    @staticmethod
    def _assignment_from_row(row: sqlite3.Row) -> Assignment:
        return Assignment(row["id"], row["patient_id"], row["program_id"], row["program_name"],
                          json.loads(row["exercise_keys"]), row["sessions_per_week"], row["start_date"],
                          row["end_date"], row["created_at"])

    def assign_program(self, patient_id: str, program_id: str, program_name: str, exercise_keys: List[str],
                       sessions_per_week: int = 3, start_date=None, end_date=None) -> Assignment:
        """Assign a program; any assignment still open on the new start ends the day before (FR-006, FR-007)."""
        from .programs import validate_exercise_keys
        patient = self.get_patient(patient_id)
        if patient is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        if patient.is_builtin:
            raise BuiltinPatientError("The built-in 'unassigned' patient cannot be assigned a program")
        keys = validate_exercise_keys(list(exercise_keys))
        if not (1 <= int(sessions_per_week) <= 14):
            raise AssignmentValidationError("sessions per week must be 1–14")
        start = self._to_date(start_date) or self.clock().date()
        end = self._to_date(end_date)
        if end is not None and end < start:
            raise AssignmentValidationError("end date must not be before the start date")
        previous_day = (start - timedelta(days=1)).isoformat()
        self.conn.execute(
            "UPDATE assignments SET end_date = ? WHERE patient_id = ? AND (end_date IS NULL OR end_date >= ?)",
            (previous_day, patient.id, start.isoformat()))
        cur = self.conn.execute(
            """
            INSERT INTO assignments (patient_id, program_id, program_name, exercise_keys, sessions_per_week,
                                     start_date, end_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (patient.id, program_id, program_name, json.dumps(keys), int(sessions_per_week), start.isoformat(),
             end.isoformat() if end else None, self._now()))
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM assignments WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._assignment_from_row(row)

    def active_assignment(self, patient_id: str, on=None) -> Optional[Assignment]:
        on_date = (self._to_date(on) or self.clock().date()).isoformat()
        row = self.conn.execute(
            """
            SELECT * FROM assignments WHERE patient_id = ? AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)
            ORDER BY start_date DESC, id DESC LIMIT 1
            """, (patient_id, on_date, on_date)).fetchone()
        return self._assignment_from_row(row) if row else None

    def assignment_history(self, patient_id: str) -> List[Assignment]:
        rows = self.conn.execute(
            "SELECT * FROM assignments WHERE patient_id = ? ORDER BY start_date DESC, id DESC", (patient_id,)).fetchall()
        return [self._assignment_from_row(r) for r in rows]

    def discharge(self, patient_id: str, on=None, reason: Optional[str] = None) -> Discharge:
        patient = self.get_patient(patient_id)
        if patient is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        if patient.is_builtin:
            raise BuiltinPatientError("The built-in 'unassigned' patient cannot be discharged")
        clean = validate_notes(reason, what="Discharge reason")
        on_date = (self._to_date(on) or self.clock().date()).isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO discharges (patient_id, discharged_on, reason, created_at) VALUES (?, ?, ?, ?)",
            (patient.id, on_date, clean, self._now()))
        self.conn.commit()
        return self.get_discharge(patient.id)

    def reactivate(self, patient_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM discharges WHERE patient_id = ?", (patient_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_discharge(self, patient_id: str) -> Optional[Discharge]:
        row = self.conn.execute("SELECT * FROM discharges WHERE patient_id = ?", (patient_id,)).fetchone()
        return Discharge(row["patient_id"], row["discharged_on"], row["reason"], row["created_at"]) if row else None

    def active_patients(self) -> List[Patient]:
        discharged = {r[0] for r in self.conn.execute("SELECT patient_id FROM discharges")}
        return [p for p in self.list_patients() if p.id not in discharged]

    def discharged_patients(self) -> List[tuple]:
        rows = self.conn.execute("SELECT patient_id FROM discharges ORDER BY discharged_on DESC, patient_id").fetchall()
        result = []
        for r in rows:
            patient = self.get_patient(r["patient_id"])
            if patient is not None:
                result.append((patient, self.get_discharge(patient.id)))
        return result

    def get_adherence_threshold(self) -> int:
        """The installation's adherence threshold (percent); patients may override it."""
        return thresholds.resolve(None, self.get_installation_thresholds()).adherence

    def set_adherence_threshold(self, value: int) -> int:
        return self.set_installation_threshold("adherence", value)

    # ---------------------------------------------------------------- patient portal (feature 007)

    def _access_status(self, patient_id: str, row) -> AccessStatus:
        if row is None:
            return AccessStatus(patient_id=patient_id, state="none")
        if row["revoked_at"]:
            state = "revoked"
        elif _ts_key(row["expires_at"]) <= _ts_key(self._now()):
            state = "expired"
        else:
            state = "active"
        return AccessStatus(patient_id=patient_id, state=state, created_at=row["created_at"],
                            expires_at=row["expires_at"], revoked_at=row["revoked_at"],
                            last_used_at=row["last_used_at"])

    def portal_set_code(self, patient_id: str, code_lookup: str, expires_at: datetime) -> AccessStatus:
        """Store the patient's one access code (as its lookup hash). Replaces any earlier code and
        ends every sign-in of the patient."""
        patient = self.get_patient(patient_id)
        if patient is None:
            raise PatientNotFoundError(f"Patient '{patient_id}' not found")
        if patient.is_builtin:
            raise PortalError("Home access cannot be given to the built-in patient")
        if self.get_discharge(patient_id) is not None:
            raise PortalError(f"Patient '{patient_id}' is discharged; reactivate them before giving home access")
        try:
            self.conn.execute("DELETE FROM portal_sessions WHERE patient_id = ?", (patient_id,))
            # Plain INSERT after deleting this patient's row: "OR REPLACE" would resolve a duplicate
            # lookup hash by deleting another patient's access.
            self.conn.execute("DELETE FROM portal_access WHERE patient_id = ?", (patient_id,))
            self.conn.execute(
                "INSERT INTO portal_access (patient_id, code_lookup, created_at, expires_at, revoked_at, last_used_at) "
                "VALUES (?, ?, ?, ?, NULL, NULL)", (patient_id, code_lookup, self._now(), expires_at.isoformat()))
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            raise
        return self.portal_status(patient_id)

    def portal_status(self, patient_id: str) -> AccessStatus:
        row = self.conn.execute("SELECT * FROM portal_access WHERE patient_id = ?", (patient_id,)).fetchone()
        return self._access_status(patient_id, row)

    def portal_lookup(self, code_lookup: str) -> Optional[AccessStatus]:
        row = self.conn.execute("SELECT * FROM portal_access WHERE code_lookup = ?", (code_lookup,)).fetchone()
        return self._access_status(row["patient_id"], row) if row else None

    def portal_list(self) -> List[AccessStatus]:
        """Every non-built-in patient with their home access state, by ID."""
        rows = {r["patient_id"]: r for r in self.conn.execute("SELECT * FROM portal_access")}
        ids = [r[0] for r in self.conn.execute("SELECT id FROM patients WHERE is_builtin = 0 ORDER BY id")]
        return [self._access_status(pid, rows.get(pid)) for pid in ids]

    def portal_revoke(self, patient_id: str) -> bool:
        cur = self.conn.execute(
            "UPDATE portal_access SET revoked_at = ? WHERE patient_id = ? AND revoked_at IS NULL",
            (self._now(), patient_id))
        self.conn.execute("DELETE FROM portal_sessions WHERE patient_id = ?", (patient_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def portal_touch(self, patient_id: str) -> None:
        self.conn.execute("UPDATE portal_access SET last_used_at = ? WHERE patient_id = ?", (self._now(), patient_id))
        self.conn.commit()

    def portal_signin_create(self, token_hash: str, patient_id: str, expires_at: datetime, keep: int = 3) -> None:
        now = self._now()
        self.conn.execute(
            "INSERT INTO portal_sessions (token_hash, patient_id, created_at, last_seen_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (token_hash, patient_id, now, now, expires_at.isoformat()))
        self.conn.execute(
            "DELETE FROM portal_sessions WHERE patient_id = ? AND token_hash NOT IN ("
            "SELECT token_hash FROM portal_sessions WHERE patient_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
            (patient_id, patient_id, int(keep)))
        self.conn.commit()

    def portal_signin_get(self, token_hash: str) -> Optional[PortalSignIn]:
        row = self.conn.execute("SELECT * FROM portal_sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        if row is None:
            return None
        return PortalSignIn(patient_id=row["patient_id"], created_at=row["created_at"],
                            last_seen_at=row["last_seen_at"], expires_at=row["expires_at"])

    def portal_signin_touch(self, token_hash: str) -> None:
        self.conn.execute("UPDATE portal_sessions SET last_seen_at = ? WHERE token_hash = ?", (self._now(), token_hash))
        self.conn.commit()

    def portal_signin_delete(self, token_hash: str) -> None:
        self.conn.execute("DELETE FROM portal_sessions WHERE token_hash = ?", (token_hash,))
        self.conn.commit()

    def portal_audit_add(self, event: str, patient_id: Optional[str], client: Optional[str],
                         detail: Optional[str] = None) -> None:
        try:
            self.conn.execute("INSERT INTO portal_audit (at, patient_id, event, client, detail) VALUES (?, ?, ?, ?, ?)",
                              (self._now(), patient_id, event, client, detail))
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            raise

    def portal_audit_list(self, patient_id: Optional[str] = None, limit: int = 200) -> List[AuditEntry]:
        sql, args = "SELECT * FROM portal_audit", ()
        if patient_id is not None:
            sql, args = sql + " WHERE patient_id = ?", (patient_id,)
        rows = self.conn.execute(sql + f" ORDER BY id DESC LIMIT {int(limit)}", args).fetchall()
        return [AuditEntry(id=r["id"], at=r["at"], patient_id=r["patient_id"], event=r["event"],
                           client=r["client"], detail=r["detail"]) for r in rows]

    # therapist sign-in (feature 007, US6); the rules live in src/portal/admin.py

    def admin_get(self) -> Optional[tuple]:
        row = self.conn.execute("SELECT salt, password_hash, updated_at FROM portal_admin WHERE id = 1").fetchone()
        return (row["salt"], row["password_hash"], row["updated_at"]) if row else None

    def admin_set(self, salt: str, password_hash: str) -> None:
        """Store the therapist password's salted hash; every therapist sign-in and pass ends."""
        self.conn.execute("DELETE FROM portal_admin")
        self.conn.execute("INSERT INTO portal_admin (id, salt, password_hash, updated_at) VALUES (1, ?, ?, ?)",
                          (salt, password_hash, self._now()))
        self.conn.execute("DELETE FROM admin_signins")
        self.conn.commit()

    def admin_clear(self) -> bool:
        cur = self.conn.execute("DELETE FROM portal_admin")
        self.conn.execute("DELETE FROM admin_signins")
        self.conn.commit()
        return cur.rowcount > 0

    def admin_token_add(self, token_hash: str, kind: str, expires_at: datetime) -> None:
        self.conn.execute("DELETE FROM admin_signins WHERE expires_at <= ?", (self._now(),))
        self.conn.execute("INSERT INTO admin_signins (token_hash, kind, created_at, expires_at) VALUES (?, ?, ?, ?)",
                          (token_hash, kind, self._now(), expires_at.isoformat()))
        self.conn.commit()

    def admin_token_get(self, token_hash: str) -> Optional[tuple]:
        row = self.conn.execute("SELECT kind, expires_at FROM admin_signins WHERE token_hash = ?", (token_hash,)).fetchone()
        return (row["kind"], row["expires_at"]) if row else None

    def admin_token_delete(self, token_hash: str) -> bool:
        cur = self.conn.execute("DELETE FROM admin_signins WHERE token_hash = ?", (token_hash,))
        self.conn.commit()
        return cur.rowcount > 0

    def admin_audit_add(self, event: str, client: Optional[str] = None) -> None:
        self.conn.execute("INSERT INTO admin_audit (at, event, client) VALUES (?, ?, ?)", (self._now(), event, client))
        self.conn.commit()

    def admin_audit_list(self, limit: int = 200) -> List[dict]:
        rows = self.conn.execute(f"SELECT at, event, client FROM admin_audit ORDER BY id DESC LIMIT {int(limit)}").fetchall()
        return [{"at": r["at"], "event": r["event"], "client": r["client"]} for r in rows]

    # messages (feature 008); the rules live in src/portal/messages.py

    @staticmethod
    def _message(row) -> Message:
        removed = row["removed_at"] is not None
        return Message(id=row["id"], patient_id=row["patient_id"], sender=row["sender"],
                       body="" if removed else row["body"], sent_at=row["sent_at"], read_at=row["read_at"],
                       removed=removed, warned=bool(row["warned"]))

    def message_event(self, patient_id: str, event: str, sender: Optional[str] = None, message_id: Optional[int] = None) -> None:
        """History of what happened in a conversation. Never the text."""
        self.conn.execute("INSERT INTO message_events (at, patient_id, event, sender, message_id) VALUES (?, ?, ?, ?, ?)",
                          (self._now(), patient_id, event, sender, message_id))

    def message_events(self, patient_id: str, limit: int = 200) -> List[dict]:
        rows = self.conn.execute(
            f"SELECT at, event, sender, message_id FROM message_events WHERE patient_id = ? ORDER BY id DESC LIMIT {int(limit)}",
            (patient_id,)).fetchall()
        return [dict(r) for r in rows]

    def conversation_enabled(self, patient_id: str) -> bool:
        row = self.conn.execute("SELECT enabled FROM conversations WHERE patient_id = ?", (patient_id,)).fetchone()
        return bool(row and row["enabled"])

    def conversation_set_enabled(self, patient_id: str, enabled: bool) -> None:
        self._require_patient(patient_id)
        self.conn.execute(
            "INSERT INTO conversations (patient_id, enabled, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(patient_id) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at",
            (patient_id, 1 if enabled else 0, self._now()))
        self.message_event(patient_id, "enabled" if enabled else "disabled")
        self.conn.commit()

    def message_add(self, patient_id: str, sender: str, body: str, warned: bool) -> Message:
        cur = self.conn.execute(
            "INSERT INTO messages (patient_id, sender, body, sent_at, warned) VALUES (?, ?, ?, ?, ?)",
            (patient_id, sender, body, self._now(), 1 if warned else 0))
        self.message_event(patient_id, "sent", sender, cur.lastrowid)
        if warned:
            self.message_event(patient_id, "sent_despite_warning", sender, cur.lastrowid)
        self.conn.execute("UPDATE conversations SET updated_at = ? WHERE patient_id = ?", (self._now(), patient_id))
        self.conn.commit()
        return self._message(self.conn.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone())

    def message_count_since(self, patient_id: str, sender: str, since: datetime) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM messages WHERE patient_id = ? AND sender = ? AND sent_at > ?",
                                 (patient_id, sender, since.isoformat())).fetchone()[0]

    def message_thread(self, patient_id: str) -> List[Message]:
        rows = self.conn.execute("SELECT * FROM messages WHERE patient_id = ? ORDER BY id", (patient_id,)).fetchall()
        return [self._message(r) for r in rows]

    def messages_mark_read(self, patient_id: str, from_sender: str) -> int:
        cur = self.conn.execute(
            "UPDATE messages SET read_at = ? WHERE patient_id = ? AND sender = ? AND read_at IS NULL",
            (self._now(), patient_id, from_sender))
        if cur.rowcount:
            self.message_event(patient_id, "read", "therapist" if from_sender == "patient" else "patient")
        self.conn.commit()
        return cur.rowcount

    def messages_unread(self, from_sender: str, patient_id: Optional[str] = None) -> Dict[str, int]:
        """Unread messages written by `from_sender`, per patient (removed messages do not count)."""
        sql = "SELECT patient_id, COUNT(*) AS n FROM messages WHERE sender = ? AND read_at IS NULL AND removed_at IS NULL"
        args: tuple = (from_sender,)
        if patient_id is not None:
            sql, args = sql + " AND patient_id = ?", (from_sender, patient_id)
        return {r["patient_id"]: int(r["n"]) for r in self.conn.execute(sql + " GROUP BY patient_id", args)}

    def message_remove(self, message_id: int) -> bool:
        row = self.conn.execute("SELECT patient_id, removed_at FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None or row["removed_at"] is not None:
            return False
        self.conn.execute("UPDATE messages SET body = '', removed_at = ? WHERE id = ?", (self._now(), message_id))
        self.message_event(row["patient_id"], "removed", "therapist", message_id)
        self.conn.commit()
        return True

    def conversation_rows(self) -> List[dict]:
        """Every non-built-in patient with messaging state and the latest message, for the inbox."""
        rows = self.conn.execute("""
            SELECT p.id AS patient_id, COALESCE(c.enabled, 0) AS enabled,
                   m.id AS last_id, m.sender AS last_sender, m.body AS last_body, m.sent_at AS last_at,
                   m.removed_at AS last_removed
            FROM patients p
            LEFT JOIN conversations c ON c.patient_id = p.id
            LEFT JOIN messages m ON m.id = (SELECT MAX(id) FROM messages WHERE patient_id = p.id)
            WHERE p.is_builtin = 0""").fetchall()
        return [dict(r) for r in rows]

    # patient-reported entries (feature 010); the rules live in src/ptlog/entries.py

    @staticmethod
    def _entry(row) -> Entry:
        return Entry(id=row["id"], patient_id=row["patient_id"], kind=row["kind"], recorded_at=row["recorded_at"],
                     received_at=row["received_at"], phase=row["phase"], session_id=row["session_id"],
                     score=row["score"], payload=json.loads(row["payload"]), client_id=row["client_id"],
                     warned=bool(row["warned"]), time_adjusted=bool(row["time_adjusted"]),
                     note_removed=bool(row["note_removed"]), reviewed_at=row["reviewed_at"])

    def entry_add(self, patient_id: str, kind: str, payload: Dict[str, Any], score: Optional[float], recorded_at: str,
                  client_id: str, phase: str, session_id: Optional[int], warned: bool, time_adjusted: bool) -> Entry:
        """Store an entry. Resending the same client id for the same patient returns the stored entry."""
        self._require_patient(patient_id)
        existing = self.conn.execute("SELECT * FROM entries WHERE patient_id = ? AND client_id = ?",
                                     (patient_id, client_id)).fetchone()
        if existing is not None:
            return self._entry(existing)
        try:
            cur = self.conn.execute(
                "INSERT INTO entries (patient_id, kind, recorded_at, received_at, phase, session_id, score, payload, "
                "client_id, warned, time_adjusted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (patient_id, kind, recorded_at, self._now(), phase, session_id, score, json.dumps(payload),
                 client_id, 1 if warned else 0, 1 if time_adjusted else 0))
            self.conn.execute("INSERT INTO portal_audit (at, patient_id, event, client, detail) VALUES (?, ?, ?, NULL, ?)",
                              (self._now(), patient_id, "entry_stored", kind))
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            raise
        return self._entry(self.conn.execute("SELECT * FROM entries WHERE id = ?", (cur.lastrowid,)).fetchone())

    def entries(self, patient_id: str, kind: Optional[str] = None, newest_first: bool = False,
                limit: Optional[int] = None) -> List[Entry]:
        sql, args = "SELECT * FROM entries WHERE patient_id = ?", [patient_id]
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        sql += " ORDER BY recorded_at " + ("DESC, id DESC" if newest_first else "ASC, id ASC")
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._entry(r) for r in self.conn.execute(sql, args)]

    def entry_remove_note(self, entry_id: int) -> bool:
        """The therapist removes an entry's free text (for example identifying details); a marker stays."""
        row = self.conn.execute("SELECT patient_id, payload, note_removed FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None or row["note_removed"]:
            return False
        payload = json.loads(row["payload"])
        if "note" in payload:
            payload["note"] = ""
        self.conn.execute("UPDATE entries SET payload = ?, note_removed = 1 WHERE id = ?", (json.dumps(payload), entry_id))
        self.portal_audit_add("entry_note_removed", row["patient_id"], None)
        return True

    def entries_all(self, kind: str) -> Dict[str, List[Entry]]:
        """Every patient's entries of one kind, oldest first, from one query (roster and queue)."""
        result: Dict[str, List[Entry]] = {}
        for r in self.conn.execute("SELECT * FROM entries WHERE kind = ? ORDER BY patient_id, recorded_at, id", (kind,)):
            result.setdefault(r["patient_id"], []).append(self._entry(r))
        return result

    # media (feature 011); the rules live in src/portal/uploads.py

    @staticmethod
    def _media(row) -> Media:
        return Media(id=row["id"], patient_id=row["patient_id"], kind=row["kind"], ext=row["ext"], container=row["container"],
                     codec=row["codec"], bytes=row["bytes"], duration=row["duration"], width=row["width"], height=row["height"],
                     sha256=row["sha256"], caption=row["caption"], warned=bool(row["warned"]), created_at=row["created_at"],
                     reviewed_at=row["reviewed_at"], deleted_at=row["deleted_at"], deleted_by=row["deleted_by"],
                     message_id=row["message_id"], backed_up_at=row["backed_up_at"])

    def media_add(self, media: Media) -> Media:
        self.conn.execute(
            "INSERT INTO media (id, patient_id, kind, ext, container, codec, bytes, duration, width, height, sha256, caption, "
            "warned, created_at, message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (media.id, media.patient_id, media.kind, media.ext, media.container, media.codec, media.bytes, media.duration,
             media.width, media.height, media.sha256, media.caption, 1 if media.warned else 0, self._now(), media.message_id))
        self.conn.commit()
        return self.media_get(media.id)

    def media_get(self, media_id: str) -> Optional[Media]:
        row = self.conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        return self._media(row) if row else None

    def media_list(self, patient_id: Optional[str] = None, kind: Optional[str] = None, live_only: bool = False) -> List[Media]:
        sql, args = "SELECT * FROM media WHERE 1=1", []
        if patient_id is not None:
            sql += " AND patient_id = ?"; args.append(patient_id)
        if kind is not None:
            sql += " AND kind = ?"; args.append(kind)
        if live_only:
            sql += " AND deleted_at IS NULL"
        return [self._media(r) for r in self.conn.execute(sql + " ORDER BY created_at DESC, id DESC", args)]

    def media_update(self, media_id: str, **fields) -> None:
        allowed = {"reviewed_at", "deleted_at", "deleted_by", "caption", "warned", "backed_up_at", "message_id"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"cannot update {bad}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE media SET {sets} WHERE id = ?", (*fields.values(), media_id))
        self.conn.commit()

    def media_count_since(self, patient_id: str, kind: str, since: datetime) -> tuple:
        row = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM media WHERE patient_id = ? AND kind = ? AND created_at > ?",
                                (patient_id, kind, since.isoformat())).fetchone()
        return int(row[0]), int(row[1])

    def upload_add(self, upload_id: str, patient_id: str, kind: str, total_bytes: int, chunk_bytes: int, sha256: str,
                   expires_at: datetime) -> None:
        self.conn.execute("INSERT INTO media_uploads (id, patient_id, kind, total_bytes, chunk_bytes, sha256, started_at, expires_at) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (upload_id, patient_id, kind, total_bytes, chunk_bytes, sha256, self._now(), expires_at.isoformat()))
        self.conn.commit()

    def upload_get(self, upload_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM media_uploads WHERE id = ?", (upload_id,)).fetchone()
        return dict(row) if row else None

    def uploads_open(self, patient_id: Optional[str] = None) -> List[dict]:
        if patient_id is None:
            return [dict(r) for r in self.conn.execute("SELECT * FROM media_uploads")]
        return [dict(r) for r in self.conn.execute("SELECT * FROM media_uploads WHERE patient_id = ?", (patient_id,))]

    def upload_delete(self, upload_id: str) -> None:
        self.conn.execute("DELETE FROM media_uploads WHERE id = ?", (upload_id,))
        self.conn.commit()

    def latest_review(self, patient_id: str) -> Optional[Review]:
        row = self.conn.execute(
            """
            SELECT r.* FROM reviews r JOIN sessions s ON s.id = r.session_id
            WHERE s.patient_id = ? ORDER BY s.start_time DESC, s.id DESC LIMIT 1
            """, (patient_id,)).fetchone()
        return Review(row["session_id"], row["reviewed_at"], row["notes"], row["next_step"]) if row else None


def _owner_alive(source_extras: Optional[str]) -> bool:
    """True when the session's extras name the process recording it and that process is alive."""
    try:
        pid = int((json.loads(source_extras) if source_extras else {}).get("pid"))
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _ts_key(ts: Optional[str]):
    """Sort key for ISO timestamps that may or may not carry microseconds."""
    if not ts:
        return datetime.min
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.min
