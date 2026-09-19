"""T023 (+T029, T037, T048) — CLI contract for patients, sessions, export, import-legacy.

Runs interfaces/cli.py in a subprocess with PTASSIST_DB pointing at a temp database.
None of these commands load the pose model.
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "interfaces" / "cli.py"


def run_cli(env, *args, stdin=None):
    return subprocess.run([sys.executable, str(CLI), *args], env=env, input=stdin,
                          capture_output=True, text=True, cwd=REPO_ROOT, timeout=60)


def out(r):
    return r.stdout + r.stderr


def seed_session(env, patient="unassigned", reps=2):
    """Create one completed session directly through the store (no camera)."""
    script = f"""
import sys; sys.path.insert(0, {str(REPO_ROOT)!r})
from datetime import datetime, timedelta
from src.ptlog.store import SessionStore, default_db_path
from src.ptlog.models import ExerciseSetInfo, RepEvent
with SessionStore(default_db_path()).open() as s:
    sid = s.start_session({patient!r}, "video", "clip.mp4")
    set_id = s.open_set(sid, ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0))
    for n in range(1, {reps} + 1):
        s.add_rep(set_id, RepEvent(n, 10.2, 88.6, 78.4, 3.1, 95.0, (datetime.now() + timedelta(seconds=n)).isoformat(), 60 * n))
    s.end_session(sid)
    print(sid)
"""
    r = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


class TestPatientsCommands:
    def test_add_and_list(self, cli_env):
        r = run_cli(cli_env, "patients", "add", "P-017", "--label", "Post-op knee")
        assert r.returncode == 0 and "Registered patient P-017" in out(r)
        r = run_cli(cli_env, "patients", "list", "--json")
        assert r.returncode == 0
        rows = json.loads(r.stdout)
        assert [p["id"] for p in rows] == ["unassigned", "P-017"]
        assert rows[1]["label"] == "Post-op knee" and rows[1]["session_count"] == 0
        r = run_cli(cli_env, "patients", "list")
        assert "P-017" in r.stdout and "Post-op knee" in r.stdout

    def test_add_rejects_identifying_id(self, cli_env):
        r = run_cli(cli_env, "patients", "add", "John Smith")
        assert r.returncode == 1 and "name" in out(r)

    def test_add_duplicate(self, cli_env):
        run_cli(cli_env, "patients", "add", "P-017")
        r = run_cli(cli_env, "patients", "add", "p-017")
        assert r.returncode == 1 and "already" in out(r)

    def test_edit(self, cli_env):
        run_cli(cli_env, "patients", "add", "P-017")
        r = run_cli(cli_env, "patients", "edit", "P-017", "--label", "Post-op knee", "--notes", "Week 3")
        assert r.returncode == 0 and "Updated patient P-017" in out(r)
        rows = json.loads(run_cli(cli_env, "patients", "list", "--json").stdout)
        assert rows[1]["label"] == "Post-op knee" and rows[1]["notes"] == "Week 3"
        r = run_cli(cli_env, "patients", "edit", "ghost", "--label", "x")
        assert r.returncode == 1 and "not found" in out(r)

    def test_delete_builtin_refused(self, cli_env):
        r = run_cli(cli_env, "patients", "delete", "unassigned", "--yes")
        assert r.returncode == 1 and "The built-in 'unassigned' patient cannot be deleted" in out(r)

    def test_delete_prompt_declined_deletes_nothing(self, cli_env):
        run_cli(cli_env, "patients", "add", "P-017")
        seed_session(cli_env, "P-017")
        r = run_cli(cli_env, "patients", "delete", "P-017", stdin="n\n")
        assert r.returncode == 0 and "Delete patient P-017 and 1 sessions? [y/N]" in r.stdout
        rows = json.loads(run_cli(cli_env, "patients", "list", "--json").stdout)
        assert any(p["id"] == "P-017" for p in rows)

    def test_delete_yes(self, cli_env):
        run_cli(cli_env, "patients", "add", "P-017")
        seed_session(cli_env, "P-017")
        r = run_cli(cli_env, "patients", "delete", "P-017", "--yes")
        assert r.returncode == 0 and "Deleted patient P-017" in out(r) and "1 session" in out(r)
        rows = json.loads(run_cli(cli_env, "patients", "list", "--json").stdout)
        assert not any(p["id"] == "P-017" for p in rows)

    def test_reassign(self, cli_env):
        run_cli(cli_env, "patients", "add", "P-017", "--label", "Post-op knee")
        sid = seed_session(cli_env, "unassigned")
        r = run_cli(cli_env, "patients", "reassign", str(sid), "--to", "P-017")
        assert r.returncode == 0 and f"Reassigned session {sid} to P-017" in out(r)
        rows = json.loads(run_cli(cli_env, "patients", "list", "--json").stdout)
        assert next(p for p in rows if p["id"] == "P-017")["session_count"] == 1

    def test_error_output_never_echoes_label(self, cli_env):
        run_cli(cli_env, "patients", "add", "P-017", "--label", "Post-op knee")
        r = run_cli(cli_env, "patients", "reassign", "999", "--to", "P-017")
        assert r.returncode == 1 and "999" in out(r)
        assert "Post-op knee" not in out(r)
        r = run_cli(cli_env, "patients", "reassign", "999", "--to", "ghost")
        assert r.returncode == 1 and "Post-op knee" not in out(r)


class TestSessionsCommands:
    def test_list_newest_first_and_filter(self, cli_env):
        run_cli(cli_env, "patients", "add", "P-017")
        a = seed_session(cli_env, "unassigned", reps=1)
        b = seed_session(cli_env, "P-017", reps=3)
        r = run_cli(cli_env, "sessions", "list", "--json")
        assert r.returncode == 0
        rows = json.loads(r.stdout)
        assert [x["id"] for x in rows] == [b, a]
        assert rows[0]["patient_id"] == "P-017" and rows[0]["total_reps"] == 3 and rows[0]["exercises"] == ["Knee Extension"]
        r = run_cli(cli_env, "sessions", "list", "--patient", "P-017")
        assert r.returncode == 0 and "Knee Extension" in r.stdout
        ids = [line.split()[0] for line in r.stdout.strip().splitlines()[1:]]
        assert ids == [str(b)]

    def test_show_prints_header_events_summary(self, cli_env):
        sid = seed_session(cli_env, "unassigned", reps=2)
        r = run_cli(cli_env, "sessions", "show", str(sid))
        assert r.returncode == 0
        assert f"Session {sid}" in r.stdout and "video (clip.mp4)" in r.stdout
        assert "REP 1 | ROM 78.4° | form 95/100 | 3.1 s | 10.2°–88.6°" in r.stdout
        assert "SESSION END | 2 reps" in r.stdout and "STATUS: completed" in r.stdout
        r = run_cli(cli_env, "sessions", "show", str(sid), "--json")
        d = json.loads(r.stdout)
        assert d["session"]["id"] == sid and [e["type"] for e in d["events"]][:2] == ["session_start", "rep"]

    def test_show_unknown_id(self, cli_env):
        r = run_cli(cli_env, "sessions", "show", "999")
        assert r.returncode == 1 and "999" in out(r)


class TestExportCommand:
    def test_export_all_and_single(self, cli_env, tmp_path):
        sid = seed_session(cli_env, "unassigned", reps=2)
        out = tmp_path / "exports"
        r = run_cli(cli_env, "export", str(sid), "--format", "all", "--out", str(out))
        assert r.returncode == 0
        names = sorted(p.name for p in out.iterdir())
        assert sorted(n.rsplit(".", 1)[1] for n in names) == ["csv", "json", "log", "txt"]
        assert all(str(out / n) in r.stdout for n in names)
        r = run_cli(cli_env, "export", str(sid), "--format", "csv_report", "--out", str(out))
        assert r.returncode == 0 and r.stdout.count("\n") == 1

    def test_export_unknown_session(self, cli_env, tmp_path):
        r = run_cli(cli_env, "export", "999", "--format", "all", "--out", str(tmp_path))
        assert r.returncode == 1 and "999" in out(r)


class TestImportLegacyCommand:
    def test_import_lines_and_totals(self, cli_env, tmp_path):
        import shutil
        legacy = REPO_ROOT / "tests" / "fixtures" / "legacy"
        shutil.copytree(legacy / "sessions", tmp_path / "sessions")
        shutil.copytree(legacy / "observation_logs", tmp_path / "observation_logs")
        args = ["import-legacy", "--sessions-dir", str(tmp_path / "sessions"), "--obs-dir", str(tmp_path / "observation_logs")]
        r = run_cli(cli_env, *args, "--dry-run")
        assert r.returncode == 0 and "dry run" in r.stdout.lower()
        assert json.loads(run_cli(cli_env, "sessions", "list", "--json").stdout) == []
        r = run_cli(cli_env, *args)
        assert r.returncode == 0
        assert "pt_session_knee_extension_20260127_134857.json: imported" in r.stdout
        assert "malformed.json: malformed" in r.stdout
        assert "duplicate (same session found in both folders)" in r.stdout
        assert "imported 4" in r.stdout and "duplicate 1" in r.stdout and "malformed 1" in r.stdout
        r = run_cli(cli_env, *args)
        assert r.stdout.count("duplicate (already imported)") == 5 and "imported 0" in r.stdout


def seed_review_history(tmp_db, patient="P-017"):
    """Four Knee Extension sessions (40, 20, 10, 1 days ago) written in-process with the real clock offsets."""
    from src.ptlog.store import SessionStore
    from src.ptlog.models import ExerciseSetInfo, RepEvent
    from tests.fixtures.golden.sequence import FixedClock
    values = [(85, 80.0, 2.4), (86, 84.0, 2.3), (88, 88.0, 2.2), (90, 92.0, 2.1)]
    clock = FixedClock(datetime.now())
    ids = []
    with SessionStore(tmp_db, clock=clock).open() as s:
        if s.get_patient(patient) is None:
            s.add_patient(patient)
        for days, (form, rom, dur) in zip((40, 20, 10, 1), values):
            start = datetime.now() - timedelta(days=days)
            clock.set(start)
            sid = s.start_session(patient, "video", "clip.mp4")
            set_id = s.open_set(sid, ExerciseSetInfo("knee_extension", "Knee Extension", "left", 10, 170.0, 90.0))
            for n in range(1, 3):
                s.add_rep(set_id, RepEvent(n, 10.0, 10.0 + rom, rom, dur, form, (start + timedelta(seconds=5 * n)).isoformat(), 60 * n))
            clock.set(start + timedelta(seconds=30))
            s.end_session(sid)
            ids.append(sid)
    return ids


class TestReviewTrends:
    def test_trends_table_and_summary(self, cli_env, tmp_db):
        seed_review_history(tmp_db)
        r = run_cli(cli_env, "review", "trends", "P-017", "--exercise", "Knee Extension", "--period", "all")
        assert r.returncode == 0, out(r)
        assert "avg ROM (°)" in r.stdout and "tempo sd (s)" in r.stdout
        assert r.stdout.count("completed") == 4
        assert "avg ROM: 80.0° → 92.0° (+12.0°)" in r.stdout
        r = run_cli(cli_env, "review", "trends", "P-017", "--exercise", "Knee Extension", "--period", "14d")
        assert r.stdout.count("completed") == 2

    def test_trends_json(self, cli_env, tmp_db):
        seed_review_history(tmp_db)
        r = run_cli(cli_env, "review", "trends", "P-017", "--exercise", "Knee Extension", "--json")
        d = json.loads(r.stdout)
        assert len(d["points"]) == 4 and d["summary"]["avg_rom"]["change"] == 12.0

    def test_unknown_exercise_lists_available(self, cli_env, tmp_db):
        seed_review_history(tmp_db)
        r = run_cli(cli_env, "review", "trends", "P-017", "--exercise", "Squat")
        assert r.returncode == 1 and "Knee Extension" in out(r)

    def test_progress_command_removed(self, cli_env):
        r = run_cli(cli_env, "progress", "--exercise", "Knee Extension")
        assert r.returncode == 2


class TestReviewSessions:
    def test_pending_mark_session(self, cli_env, tmp_db):
        ids = seed_review_history(tmp_db)
        r = run_cli(cli_env, "review", "pending", "P-017")
        assert r.returncode == 0
        listed = [line.split()[0] for line in r.stdout.strip().splitlines()[1:]]
        assert listed == [str(i) for i in reversed(ids)]
        r = run_cli(cli_env, "review", "mark", str(ids[0]), "--next-step", "progress", "--notes", "post-op week 3")
        assert r.returncode == 0 and f"Reviewed session {ids[0]} (next step: progress)" in out(r)
        r = run_cli(cli_env, "review", "mark", str(ids[0]), "--next-step", "hold", "--notes", "seen by Jane Doe")
        assert r.returncode == 1 and "name" in out(r)
        r = run_cli(cli_env, "review", "mark", str(ids[0]), "--next-step", "stop")
        assert r.returncode == 2
        r = run_cli(cli_env, "review", "session", str(ids[0]))
        assert r.returncode == 0 and "REVIEW: reviewed" in r.stdout and "post-op week 3" in r.stdout and "Per-session summary" in r.stdout
        r = run_cli(cli_env, "review", "session", str(ids[1]))
        assert "REVIEW: pending" in r.stdout
        r = run_cli(cli_env, "review", "pending", "P-017")
        assert str(ids[0]) not in [line.split()[0] for line in r.stdout.strip().splitlines()[1:]]
        r = run_cli(cli_env, "review", "session", str(ids[0]), "--json")
        d = json.loads(r.stdout)
        assert d["review"]["next_step"] == "progress" and "key_flags" in d["summary"]


class TestReviewFlags:
    def test_flags_and_settings(self, cli_env, tmp_db):
        ids = seed_review_history(tmp_db)   # reps 2/10 in the last three sessions -> target rule; 20/10/9-day gaps
        r = run_cli(cli_env, "review", "flags", "P-017")
        assert r.returncode == 0 and "target_reps_not_reached" in r.stdout and "practice_gap" in r.stdout
        assert all(str(i) in r.stdout for i in ids[1:])
        r = run_cli(cli_env, "review", "flags", "P-017", "--json")
        assert any(f["rule"] == "target_reps_not_reached" for f in json.loads(r.stdout)["flags"])
        r = run_cli(cli_env, "review", "settings", "P-017")
        assert r.returncode == 0 and "Gap threshold: 7 days" in r.stdout
        r = run_cli(cli_env, "review", "settings", "P-017", "--gap-days", "5")
        assert r.returncode == 0 and "Gap threshold: 5 days" in r.stdout
        r = run_cli(cli_env, "review", "settings", "P-017", "--gap-days", "0")
        assert r.returncode == 1
