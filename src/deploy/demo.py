"""
Resetting the hosted demo (feature 020, FR-010 and FR-012). The demo is built from the simulated seed on this
machine, then loaded into the hosted record. Schema changes on the hosted demo are applied this way too, never by
migrating in place.

Over the network, libSQL's `executescript` stops at the first failing statement without raising an error, and a
`PRAGMA` doesn't carry from one statement to the next (gate G1 and slice A). So the load runs one statement at a
time, with every error raised: tables first, then rows with parents before children, then indexes.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Callable, Dict, Iterator, List, Optional

from src.ptlog import backend

REPO = Path(__file__).resolve().parent.parent.parent
HOSTED_AI_CAP = 10                      # AI calls per account per day: the demo's password is public


_HOSTED_SETTINGS = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "LIMBER_DB_BACKEND", "LIMBER_R2_ACCOUNT_ID",
                    "LIMBER_R2_BUCKET", "LIMBER_R2_ACCESS_KEY_ID", "LIMBER_R2_SECRET_ACCESS_KEY")


@contextmanager
def _local_build() -> Iterator[None]:
    """Build the seed as a plain local SQLite file with local files: with the hosted settings present, opening it
    would go through Turso and its files straight to R2 while it is still being built."""
    saved = {k: os.environ.pop(k) for k in _HOSTED_SETTINGS if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _seed_module():
    spec = importlib.util.spec_from_file_location("seed_demo", REPO / "scripts" / "seed_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fk_order(src: sqlite3.Connection) -> List[str]:
    """Tables with every table they refer to before them."""
    tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    refers = {t: {r[2] for r in src.execute(f'PRAGMA foreign_key_list("{t}")') if r[2] != t} for t in tables}
    order: List[str] = []

    def visit(t: str, path: tuple = ()) -> None:
        if t in order:
            return
        if t in path:
            raise RuntimeError(f"Foreign keys form a cycle through {t}")
        for parent in sorted(refers.get(t, ())):
            if parent in refers:
                visit(parent, path + (t,))
        order.append(t)

    for t in sorted(tables):
        visit(t)
    return order


def _check_target(conn) -> None:
    """The hosted-demo guard, before anything is changed: only an empty record or the marked demo is replaced."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "patients" not in tables:
        return
    real = conn.execute("SELECT COUNT(*) FROM patients WHERE is_builtin = 0").fetchone()[0]
    marked = conn.execute("SELECT value FROM clinic_settings WHERE key = ?", (backend.MARKER,)).fetchone() \
        if "clinic_settings" in tables else None
    if real and not (marked and marked[0] == "1"):
        raise backend.HostedRecordRefused("The hosted record has patients but no simulated-data marker, so it may not "
                                          "be the demo. The reset refuses to replace it.")


def reset(target_db: Path, connect: Optional[Callable] = None, seed: int = 7, files_target=None) -> Dict:
    """Replace the hosted record and its files with a fresh simulated demo. Returns the patient count, the rows
    loaded, the files copied, the time taken, and the new access codes (shown once)."""
    from src.media import files
    target_files = files_target or files.at(Path(target_db).parent / "media")
    conn = (connect or backend.connect_primary)()
    _check_target(conn)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="limber-demo-") as tmp:
        built = Path(tmp) / "demo.db"
        seed_demo = _seed_module()
        from src.assist import assistant
        from src.ptlog.store import SessionStore
        with _local_build():
            seed_demo.build(built, seed)
            codes = {pid: code for pid, _about, code in seed_demo.demo_logins(built)}
            with SessionStore(built).open() as s:
                assistant.set_daily_cap(s, HOSTED_AI_CAP)
            built_files = files.LocalFiles(built.parent / "media")
        src = sqlite3.connect(str(built))
        order = _fk_order(src)
        existing = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        for table in list(reversed(order)) + [t for t in existing if t not in order]:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.commit()
        schema = dict(src.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        for table in order:
            conn.execute(schema[table])
        conn.commit()
        rows = 0
        for table in order:
            columns = [c[1] for c in src.execute(f'PRAGMA table_info("{table}")')]
            names = ", ".join(f'"{c}"' for c in columns)
            insert = f'INSERT INTO "{table}" ({names}) VALUES ({", ".join("?" * len(columns))})'
            for values in src.execute(f'SELECT {names} FROM "{table}" ORDER BY rowid'):
                conn.execute(insert, tuple(values))
                rows += 1
                if rows % 200 == 0:
                    conn.commit()
            conn.commit()
        for (sql,) in src.execute("SELECT sql FROM sqlite_master WHERE type IN ('index', 'trigger', 'view') AND sql IS NOT NULL"):
            conn.execute(sql)
        conn.commit()
        for name, seq in src.execute("SELECT name, seq FROM sqlite_sequence"):
            if conn.execute("SELECT 1 FROM sqlite_sequence WHERE name = ?", (name,)).fetchone():
                conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (seq, name))
            else:
                conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (name, seq))
        conn.commit()
        patients = src.execute("SELECT COUNT(*) FROM patients WHERE is_builtin = 0").fetchone()[0]
        src.close()
        # The old demo's files go, and the new seed's files (its voice note) take their place.
        for rel in target_files.list(""):
            target_files.delete(rel)
        copied = 0
        for rel in built_files.list(""):
            target_files.put_bytes(rel, built_files.get_bytes(rel))
            copied += 1
    conn.close()
    return {"patients": patients, "rows": rows, "files": copied, "seconds": round(time.monotonic() - started, 1),
            "codes": codes}
