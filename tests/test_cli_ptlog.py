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


class TestReviewCompare:
    def test_compare_table_and_refusal(self, cli_env, tmp_db):
        ids = seed_review_history(tmp_db)
        r = run_cli(cli_env, "review", "compare", str(ids[0]), str(ids[-1]))
        assert r.returncode == 0 and "better when" in r.stdout and "avg ROM" in r.stdout and "+12.0°" in r.stdout
        r = run_cli(cli_env, "review", "compare", str(ids[0]), str(ids[-1]), "--json")
        rows = json.loads(r.stdout)["rows"]
        assert any(row["name"] == "avg_rom" and row["change"] == 12.0 for row in rows)
        r = run_cli(cli_env, "review", "compare", str(ids[0]), "999")
        assert r.returncode == 1


class TestReviewGoals:
    def test_goal_set_update_clear_and_trend_line(self, cli_env, tmp_db):
        seed_review_history(tmp_db)
        r = run_cli(cli_env, "review", "goal", "set", "P-017", "--exercise", "Knee Extension", "--rom", "120", "--reps", "10")
        assert r.returncode == 0 and "Goal for Knee Extension: ROM 120° | reps 10" in out(r)
        r = run_cli(cli_env, "review", "goal", "set", "P-017", "--exercise", "Knee Extension", "--reps", "12")
        assert r.returncode == 0
        r = run_cli(cli_env, "review", "goals", "P-017")
        assert "ROM 120°" in r.stdout and "reps 12" in r.stdout
        rows = json.loads(run_cli(cli_env, "review", "goals", "P-017", "--json").stdout)
        assert rows[0]["target_rom"] == 120.0 and rows[0]["target_reps"] == 12
        r = run_cli(cli_env, "review", "goal", "set", "P-017", "--exercise", "Knee Extension", "--rom", "200")
        assert r.returncode == 1 and "1–180" in out(r)
        r = run_cli(cli_env, "review", "trends", "P-017", "--exercise", "Knee Extension")
        assert "Goal: ROM 120° (77% of goal) | reps 12" in r.stdout
        r = run_cli(cli_env, "review", "goal", "clear", "P-017", "--exercise", "Knee Extension")
        assert r.returncode == 0 and "Cleared goal for Knee Extension" in out(r)
        assert json.loads(run_cli(cli_env, "review", "goals", "P-017", "--json").stdout) == []


class TestReviewExport:
    def test_export_all_and_single(self, cli_env, tmp_db, tmp_path):
        seed_review_history(tmp_db)
        out_dir = tmp_path / "rev"
        r = run_cli(cli_env, "review", "export", "P-017", "--format", "all", "--out", str(out_dir))
        assert r.returncode == 0
        names = sorted(p.name for p in out_dir.iterdir())
        assert len(names) == 2 and names[0].startswith("P-017_review_all_") and names[0].endswith(".csv") and names[1].endswith(".txt")
        assert all(str(out_dir / n) in r.stdout for n in names)
        r = run_cli(cli_env, "review", "export", "P-017", "--format", "csv", "--period", "30d", "--out", str(out_dir))
        assert r.returncode == 0 and r.stdout.count("\n") == 1 and "_review_30d_" in r.stdout
        r = run_cli(cli_env, "review", "export", "ghost", "--format", "all", "--out", str(out_dir))
        assert r.returncode == 1


def seed_caseload(tmp_db):
    """A (declining form, one pending, knee_rehab assigned 21 days ago), B (quiet 20 days), C (discharged), D (none)."""
    from datetime import date
    from src.ptlog.store import SessionStore
    from src.ptlog.models import ExerciseSetInfo, RepEvent
    from tests.fixtures.golden.sequence import FixedClock
    knee = ExerciseSetInfo("knee_extension", "Knee Extension", "left", 1, 170.0, 90.0)
    clock = FixedClock(datetime.now())
    ids = {}
    with SessionStore(tmp_db, clock=clock).open() as s:
        for pid in ("P-017", "P-018", "P-019", "P-020"):
            s.add_patient(pid)

        def rec(pid, days_ago, form):
            start = datetime.now() - timedelta(days=days_ago)
            clock.set(start)
            sid = s.start_session(pid, "video", "clip.mp4")
            set_id = s.open_set(sid, knee)
            s.add_rep(set_id, RepEvent(1, 10.0, 88.0, 78.0, 3.0, form, (start + timedelta(seconds=5)).isoformat(), 60))
            clock.set(start + timedelta(seconds=30))
            s.end_session(sid)
            return sid

        ids["P-017"] = [rec("P-017", d, f) for d, f in ((18, 90), (12, 86), (5, 81), (2, 75))]
        for sid, step in zip(ids["P-017"][:3], ("continue", "continue", "hold")):
            s.set_review(sid, step)
        ids["P-018"] = [rec("P-018", 20, 88)]
        s.set_review(ids["P-018"][0], "continue")
        ids["P-019"] = [rec("P-019", 3, 88)]
        s.discharge("P-019", date.today(), "goals met")
        KEYS = ["knee_extension", "knee_extension_right", "partial_squat", "seated_hip_flexion", "seated_hip_flexion_right"]
        s.assign_program("P-017", "knee_rehab", "Knee Rehabilitation", KEYS, 3, date.today() - timedelta(days=21))
    return ids


class TestTrackerRoster:
    def test_roster_sorts_and_filters(self, cli_env, tmp_db):
        seed_caseload(tmp_db)
        r = run_cli(cli_env, "tracker", "roster")
        assert r.returncode == 0, out(r)
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        assert "adherence" in lines[0].lower() and "pending" in lines[0].lower()
        rows = [l.split()[0] for l in lines[1:]]
        assert rows == ["P-017", "P-018", "P-020"]
        r = run_cli(cli_env, "tracker", "roster", "--sort", "id")
        assert [l.split()[0] for l in r.stdout.strip().splitlines()[1:]] == ["P-017", "P-018", "P-020"]
        r = run_cli(cli_env, "tracker", "roster", "--needs-attention")
        assert [l.split()[0] for l in r.stdout.strip().splitlines()[1:]] == ["P-017", "P-018"]
        r = run_cli(cli_env, "tracker", "roster", "--program", "knee_rehab")
        assert [l.split()[0] for l in r.stdout.strip().splitlines()[1:]] == ["P-017"]
        rows = json.loads(run_cli(cli_env, "tracker", "roster", "--json").stdout)
        a = next(x for x in rows if x["patient_id"] == "P-017")
        assert a["pending_reviews"] == 1 and a["open_flags"] == 1 and a["adherence_pct"] == 44 and a["last_next_step"] == "hold"

    def test_programs(self, cli_env):
        r = run_cli(cli_env, "tracker", "programs")
        assert r.returncode == 0 and "knee_rehab" in r.stdout and "Knee Rehabilitation" in r.stdout and "custom" in r.stdout
        rows = json.loads(run_cli(cli_env, "tracker", "programs", "--json").stdout)
        assert [p["id"] for p in rows] == ["knee_rehab", "shoulder_mobility", "hip_strengthening", "general_conditioning", "custom"]


class TestTrackerAssign:
    def test_assign_supersede_history_and_validation(self, cli_env, tmp_db):
        from datetime import date
        run_cli(cli_env, "patients", "add", "P-017")
        r = run_cli(cli_env, "tracker", "assign", "P-017", "--program", "knee_rehab", "--per-week", "3", "--start", "2026-03-01")
        assert r.returncode == 0 and "Assigned Knee Rehabilitation to P-017: 3 sessions/week from 2026-03-01" in out(r)
        r = run_cli(cli_env, "tracker", "assign", "P-017", "--exercises", "squat,pushup", "--start", "2026-03-15")
        assert r.returncode == 0 and "Assigned Custom to P-017: 3 sessions/week from 2026-03-15" in out(r)
        assert "Ended previous assignment (Knee Rehabilitation) on 2026-03-14" in out(r)
        r = run_cli(cli_env, "tracker", "assignments", "P-017")
        lines = [l for l in r.stdout.strip().splitlines() if l.startswith("2026")]
        assert lines[0].startswith("2026-03-15") and "Custom" in lines[0] and lines[1].startswith("2026-03-01") and "Knee Rehabilitation" in lines[1]
        assert "superseded" in lines[1] or "completed" in lines[1]
        rows = json.loads(run_cli(cli_env, "tracker", "assignments", "P-017", "--json").stdout)
        assert [x["program_id"] for x in rows] == ["custom", "knee_rehab"] and rows[1]["end_date"] == "2026-03-14"
        r = run_cli(cli_env, "tracker", "assign", "P-017", "--exercises", "bogus")
        assert r.returncode == 1 and "bogus" in out(r)
        r = run_cli(cli_env, "tracker", "assign", "P-017", "--program", "knee_rehab", "--per-week", "15")
        assert r.returncode == 1
        r = run_cli(cli_env, "tracker", "assign", "P-017", "--program", "knee_rehab", "--start", "2026-03-01", "--end", "2026-02-01")
        assert r.returncode == 1 and "end date" in out(r)
        r = run_cli(cli_env, "tracker", "assign", "unassigned", "--program", "knee_rehab")
        assert r.returncode == 1
        r = run_cli(cli_env, "tracker", "assign", "P-017", "--program", "nope")
        assert r.returncode == 1 and "nope" in out(r)


class TestTrackerAdherence:
    def test_adherence_rows_and_percentage(self, cli_env, tmp_db):
        seed_caseload(tmp_db)
        r = run_cli(cli_env, "tracker", "adherence", "P-017")
        assert r.returncode == 0 and "Knee Rehabilitation" in r.stdout and "3 sessions/week" in r.stdout
        assert r.stdout.count("week ") >= 4 and "in progress" in r.stdout
        assert "Adherence: 44% over 3 complete weeks" in r.stdout
        d = json.loads(run_cli(cli_env, "tracker", "adherence", "P-017", "--json").stdout)
        assert d["percentage"] == 44 and len(d["weeks"]) == 4 and d["weeks"][2]["in_progress"] is False
        r = run_cli(cli_env, "tracker", "adherence", "P-018")
        assert r.returncode == 0 and "No program assigned" in r.stdout
        r = run_cli(cli_env, "tracker", "adherence", "ghost")
        assert r.returncode == 1


class TestTrackerQueueAndSettings:
    def test_queue_sections_and_threshold(self, cli_env, tmp_db):
        ids = seed_caseload(tmp_db)
        r = run_cli(cli_env, "tracker", "queue")
        assert r.returncode == 0 and "Pending reviews" in r.stdout and "Attention flags" in r.stdout
        assert f"session:{ids['P-017'][3]}" in r.stdout and "P-018" in r.stdout
        d = json.loads(run_cli(cli_env, "tracker", "queue", "--json").stdout)
        assert d["totals"]["pending_review"] == 1 and d["totals"]["practice_gap"] >= 1
        r = run_cli(cli_env, "tracker", "settings")
        assert r.returncode == 0 and "Adherence threshold: 60%" in r.stdout
        r = run_cli(cli_env, "tracker", "settings", "--adherence-threshold", "30")
        assert r.returncode == 0 and "Adherence threshold: 30%" in r.stdout
        r = run_cli(cli_env, "tracker", "settings", "--adherence-threshold", "0")
        assert r.returncode == 1

    def test_empty_queue_message(self, cli_env):
        r = run_cli(cli_env, "tracker", "queue")
        assert r.returncode == 0 and "Caseload is up to date." in r.stdout


class TestTrackerDischarge:
    def test_discharge_reactivate_lists(self, cli_env, tmp_db):
        from datetime import date
        seed_caseload(tmp_db)
        r = run_cli(cli_env, "tracker", "discharge", "P-018", "--reason", "goals met")
        assert r.returncode == 0 and f"Discharged P-018 on {date.today().isoformat()}" in out(r)
        r = run_cli(cli_env, "tracker", "roster")
        assert "P-018" not in r.stdout
        r = run_cli(cli_env, "tracker", "queue")
        assert "P-018" not in r.stdout
        r = run_cli(cli_env, "tracker", "discharged")
        assert r.returncode == 0 and "P-018" in r.stdout and "goals met" in r.stdout and "P-019" in r.stdout
        r = run_cli(cli_env, "tracker", "discharge", "P-017", "--reason", "moved to Jane Doe clinic")
        assert r.returncode == 1 and "name" in out(r)
        r = run_cli(cli_env, "tracker", "discharge", "unassigned")
        assert r.returncode == 1
        r = run_cli(cli_env, "tracker", "reactivate", "P-018")
        assert r.returncode == 0 and "Reactivated P-018" in out(r)
        r = run_cli(cli_env, "tracker", "reactivate", "P-018")
        assert r.returncode == 0 and "P-018 is already active" in out(r)
        r = run_cli(cli_env, "sessions", "list", "--patient", "P-018")
        assert r.returncode == 0 and "Knee Extension" in r.stdout


class TestTrackerExport:
    def test_export_roster(self, cli_env, tmp_db, tmp_path):
        seed_caseload(tmp_db)
        r = run_cli(cli_env, "tracker", "export-roster", "--out", str(tmp_path))
        assert r.returncode == 0
        path = Path(r.stdout.strip())
        assert path.exists() and path.name.startswith("roster_") and path.suffix == ".csv"
        text = path.read_text()
        assert text.startswith("patient_id,label,program,program_status,days_since_last_session,")
        assert "P-017" in text and "P-019" not in text


class TestReviewThresholds:
    """Feature 005 US1: `review thresholds <patient>`."""

    def test_list_shows_value_unit_origin_default_and_meaning(self, cli_env, tmp_db):
        seed_review_history(tmp_db)
        r = run_cli(cli_env, "review", "thresholds", "P-017")
        assert r.returncode == 0, out(r)
        lines = [line for line in r.stdout.splitlines() if " (default" in line or "; default" in line]
        assert len(lines) == 8
        assert any(line.startswith("ROM regression: 10 degrees (default)") and "previous three" in line for line in lines)
        d = json.loads(run_cli(cli_env, "review", "thresholds", "P-017", "--json").stdout)
        assert d["rom_regression"] == {"value": 10, "origin": "default", "default": 10, "unit": "degrees"}

    def test_set_reset_and_flags_follow(self, cli_env, tmp_db):
        seed_review_history(tmp_db)
        assert "practice_gap" in run_cli(cli_env, "review", "flags", "P-017", "--json").stdout
        r = run_cli(cli_env, "review", "thresholds", "P-017", "--set", "practice_gap=30", "rom_regression=5")
        assert r.returncode == 0, out(r)
        assert "Practice gap: 30 days (patient; default 7)" in r.stdout
        assert "ROM regression: 5 degrees (patient; default 10)" in r.stdout
        assert "practice_gap" not in run_cli(cli_env, "review", "flags", "P-017", "--json").stdout
        assert "Gap threshold: 30 days" in run_cli(cli_env, "review", "settings", "P-017").stdout
        r = run_cli(cli_env, "review", "thresholds", "P-017", "--reset", "practice_gap")
        assert "Practice gap: 7 days (default)" in r.stdout and "ROM regression: 5 degrees (patient" in r.stdout
        r = run_cli(cli_env, "review", "thresholds", "P-017", "--reset-all")
        assert r.returncode == 0 and "(patient" not in r.stdout

    def test_invalid_values_change_nothing(self, cli_env, tmp_db):
        seed_review_history(tmp_db)
        r = run_cli(cli_env, "review", "thresholds", "P-017", "--set", "rom_regression=5", "form_drop=0")
        assert r.returncode == 1 and "1-50 points" in out(r)
        assert "(patient" not in run_cli(cli_env, "review", "thresholds", "P-017").stdout
        for bad in ("speed=3", "form_drop", "form_drop=abc"):
            assert run_cli(cli_env, "review", "thresholds", "P-017", "--set", bad).returncode == 1
        assert run_cli(cli_env, "review", "thresholds", "ghost").returncode == 1
        assert run_cli(cli_env, "review", "thresholds").returncode == 1          # a patient or --installation is required


class TestAdherenceThresholdShown:
    def test_adherence_view_states_threshold_and_origin(self, cli_env, tmp_db):
        seed_caseload(tmp_db)
        assert "Attention threshold: 60% (default)" in run_cli(cli_env, "tracker", "adherence", "P-017").stdout
        run_cli(cli_env, "review", "thresholds", "P-017", "--set", "adherence=50")
        r = run_cli(cli_env, "tracker", "adherence", "P-017")
        assert "Attention threshold: 50% (patient)" in r.stdout
        d = json.loads(run_cli(cli_env, "tracker", "adherence", "P-017", "--json").stdout)
        assert d["threshold"] == {"value": 50, "origin": "patient"}


class TestInstallationThresholds:
    """Feature 005 US3: `review thresholds --installation`."""

    def test_set_list_reset_restore(self, cli_env, tmp_db):
        seed_review_history(tmp_db)
        run_cli(cli_env, "review", "thresholds", "P-017", "--set", "form_drop=12")
        r = run_cli(cli_env, "review", "thresholds", "--installation", "--set", "form_drop=8", "adherence=50")
        assert r.returncode == 0, out(r)
        assert "Form drop: 8 points (installation; default 10)" in r.stdout
        assert "Adherence threshold: 50%" in run_cli(cli_env, "tracker", "settings").stdout
        patient = run_cli(cli_env, "review", "thresholds", "P-017").stdout
        assert "Form drop: 12 points (patient; default 8)" in patient          # the default a reset would give
        assert "Adherence: 50 percent (installation; default 50)" in patient
        r = run_cli(cli_env, "review", "thresholds", "--installation", "--reset", "adherence")
        assert "Adherence: 60 percent (default)" in r.stdout and "Form drop: 8 points (installation" in r.stdout
        r = run_cli(cli_env, "review", "thresholds", "--installation", "--restore-defaults")
        assert r.returncode == 0 and "(installation" not in r.stdout
        assert "Form drop: 12 points (patient; default 10)" in run_cli(cli_env, "review", "thresholds", "P-017").stdout

    def test_misuse_is_rejected(self, cli_env, tmp_db):
        seed_review_history(tmp_db)
        assert run_cli(cli_env, "review", "thresholds", "P-017", "--installation").returncode == 1
        assert run_cli(cli_env, "review", "thresholds", "--installation", "--reset-all").returncode == 1
        assert run_cli(cli_env, "review", "thresholds", "P-017", "--restore-defaults").returncode == 1
        r = run_cli(cli_env, "review", "thresholds", "--installation", "--set", "adherence=101")
        assert r.returncode == 1 and "1-100 percent" in out(r)
