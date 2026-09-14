"""
ptlog — the canonical PT session log.

One local SQLite record of patients, sessions, exercise sets, reps, partial reps,
form events, and control events, written by a single writer (SessionStore) and fed
by a single engine adapter (SessionRecorder). Every other file format is an export
derived from this record. See specs/001-unified-session-log/.
"""

__all__: list[str] = []
