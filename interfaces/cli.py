#!/usr/bin/env python3
"""
Command Line Interface for AI Physical Therapy Assistant
=========================================================

This module provides a clean, user-friendly CLI for all PT Assistant functions.

Commands:
    analyze     Process a video file for exercise analysis
    webcam      Start real-time webcam analysis
    patients    Register and manage pseudonymous patients
    sessions    List sessions and read a session's event log
    list        List available exercises
    export      Export a session in a legacy file format
    import-legacy  Import pre-existing session files once
    review      Trends, flags, comparisons, session reviews, goals, and review exports
    tracker     Caseload roster, programs, adherence, and the cross-patient queue
    calibrate   Help set up optimal camera positioning

Usage Examples:
    python cli.py analyze --video session.mp4 --exercise knee_extension
    python cli.py webcam --exercise shoulder_flexion --reps 10
    python cli.py patients add P-017 --label "Post-op knee"
    python cli.py sessions list --patient P-017
    python cli.py list-exercises
    python cli.py review trends P-017 --exercise "Knee Extension"

Author: AI PT Assistant
"""

import argparse
import sys
import os
from pathlib import Path
from typing import Optional
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ptlog.models import (  # noqa: E402
    BuiltinPatientError, DuplicatePatientError, PatientNotFoundError,
    PatientValidationError, PTLogError, SessionNotFoundError,
)
from src.ptlog.store import SessionStore, default_db_path  # noqa: E402
import json  # noqa: E402
import sqlite3  # noqa: E402

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def color_text(text: str, color: str) -> str:
    """Apply color to text if terminal supports it."""
    if sys.stdout.isatty():
        return f"{color}{text}{Colors.ENDC}"
    return text


def print_header(text: str):
    """Print a styled header."""
    print()
    print(color_text("=" * 60, Colors.CYAN))
    print(color_text(f"  {text}", Colors.BOLD + Colors.CYAN))
    print(color_text("=" * 60, Colors.CYAN))
    print()


def print_success(text: str):
    """Print success message."""
    print(color_text(f"✓ {text}", Colors.GREEN))


def print_warning(text: str):
    """Print warning message."""
    print(color_text(f"⚠ {text}", Colors.YELLOW))


def print_error(text: str):
    """Print error message."""
    print(color_text(f"✗ {text}", Colors.RED))


def print_info(text: str):
    """Print info message."""
    print(color_text(f"ℹ {text}", Colors.BLUE))


def print_progress_bar(progress: float, width: int = 40, prefix: str = "Progress"):
    """
    Print a progress bar.

    Args:
        progress: Progress value (0.0 to 1.0)
        width: Width of the bar in characters
        prefix: Text to show before the bar
    """
    filled = int(width * progress)
    bar = "█" * filled + "░" * (width - filled)
    percent = progress * 100

    # Color based on progress
    if progress >= 0.8:
        color = Colors.GREEN
    elif progress >= 0.5:
        color = Colors.YELLOW
    else:
        color = Colors.RED

    print(f"\r{prefix}: {color_text(bar, color)} {percent:5.1f}%", end="", flush=True)


def draw_ascii_skeleton(keypoints: dict, width: int = 40, height: int = 20) -> str:
    """
    Draw a simple ASCII representation of a skeleton.

    This is a simplified visualization for terminal display.
    """
    # This is a simplified ASCII skeleton - actual implementation would
    # map keypoint coordinates to character positions

    skeleton = """
           O          <- Head
          /|\\         <- Shoulders/Arms
         / | \\
        /  |  \\
           |          <- Spine
          / \\         <- Hips
         /   \\
        /     \\       <- Legs
       /       \\
      |         |     <- Feet
    """
    return skeleton


# =============================================================================
# COMMAND IMPLEMENTATIONS
# =============================================================================

def cmd_analyze(args):
    """Handle the analyze command."""
    print_header("AI PT Assistant - Video Analysis")

    # Validate inputs
    if not os.path.exists(args.video):
        print_error(f"Video file not found: {args.video}")
        return 1

    print_info(f"Input video: {args.video}")
    print_info(f"Exercise: {args.exercise}")
    print_info(f"Output: {args.output or 'No output video (analysis only)'}")
    print()

    try:
        # Import analysis module
        from analyze import main, load_config

        # Validate exercise
        exercises = load_config()
        if args.exercise not in exercises:
            print_warning(f"Exercise '{args.exercise}' not found in config.")
            print_info(f"Available exercises: {', '.join(exercises.keys())}")
            return 1

        # Run analysis
        print_info("Starting analysis...")
        print()

        session = main(
            video_path=args.video,
            exercise_name=args.exercise,
            output_path=args.output,
            show_video=not args.headless,
            patient_id=args.patient
        )

        # Print results
        print()
        print_header("Analysis Complete")

        # Display results with colors
        completion = session.total_reps / session.target_reps if session.target_reps > 0 else 0
        completion_color = Colors.GREEN if completion >= 0.8 else (Colors.YELLOW if completion >= 0.5 else Colors.RED)

        print(f"  Exercise: {color_text(session.exercise_name, Colors.CYAN)}")
        print(f"  Reps: {color_text(f'{session.total_reps}/{session.target_reps}', completion_color)}")
        print(f"  Average ROM: {color_text(f'{session.avg_rom}°', Colors.BLUE)}")
        print(f"  Maximum ROM: {color_text(f'{session.max_rom}°', Colors.BLUE)}")

        form_color = Colors.GREEN if session.avg_form_score >= 80 else (
            Colors.YELLOW if session.avg_form_score >= 60 else Colors.RED
        )
        print(f"  Form Score: {color_text(f'{session.avg_form_score:.1f}%', form_color)}")
        print(f"  Tempo Consistency: {color_text(f'σ = {session.tempo_consistency:.2f}s', Colors.BLUE)}")
        print()

        if args.output:
            print_success(f"Annotated video saved: {args.output}")

        return 0

    except PatientNotFoundError:
        print_error(f"Patient '{args.patient}' not found. Register it with: patients add {args.patient}")
        return 1
    except ImportError as e:
        print_error(f"Could not import analysis module: {e}")
        print_info("Make sure you're running from the project directory")
        return 1
    except Exception as e:
        print_error(f"Analysis failed: {e}")
        return 1


def cmd_webcam(args):
    """Handle the webcam command."""
    print_header("AI PT Assistant - Live Session")

    print_info(f"Exercise: {args.exercise}")
    print_info(f"Target reps: {args.reps}")
    print_info(f"Camera: {args.camera}")
    if args.record:
        print_info(f"Recording to: {args.record}")
    print()

    print(color_text("Controls:", Colors.BOLD))
    print("  q - Quit")
    print("  r - Reset rep counter")
    print("  p - Pause/Resume")
    print("  n - Next exercise")
    print("  s - Save screenshot")
    print()

    input(color_text("Press Enter to start...", Colors.CYAN))

    try:
        from analyze import analyze_webcam

        session = analyze_webcam(
            exercise_name=args.exercise,
            camera_id=args.camera,
            record_output=args.record,
            patient_id=args.patient
        )

        # Print session summary
        print()
        print_header("Session Complete")

        print(f"  Total Reps: {session.total_reps}")
        print(f"  Average Form Score: {session.avg_form_score:.1f}%")
        print(f"  Average ROM: {session.avg_rom}°")

        return 0

    except PatientNotFoundError:
        print_error(f"Patient '{args.patient}' not found. Register it with: patients add {args.patient}")
        return 1
    except ImportError as e:
        print_error(f"Could not import analysis module: {e}")
        return 1
    except Exception as e:
        print_error(f"Webcam session failed: {e}")
        return 1


def cmd_list_exercises(args):
    """Handle the list-exercises command."""
    print_header("Available Exercises")

    try:
        import yaml
        config_path = Path(__file__).parent.parent / "config.yaml"

        if not config_path.exists():
            print_warning("config.yaml not found, using defaults")
            exercises = {
                "knee_extension": {"display_name": "Knee Extension", "keypoints": [11, 13, 15]},
                "shoulder_flexion": {"display_name": "Shoulder Flexion", "keypoints": [11, 5, 7]},
                "squat": {"display_name": "Squat", "keypoints": [11, 13, 15]},
                "hip_abduction": {"display_name": "Hip Abduction", "keypoints": [12, 11, 13]},
            }
        else:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                exercises = config.get('exercises', {})

        print(f"{'Exercise ID':<25} {'Display Name':<25} {'Keypoints':<20}")
        print("-" * 70)

        for ex_id, ex_data in exercises.items():
            name = ex_data.get('display_name', ex_id)
            kpts = ex_data.get('keypoints', [])
            kpts_str = f"[{', '.join(map(str, kpts))}]"
            print(f"{ex_id:<25} {name:<25} {kpts_str:<20}")

        print()
        print_info("Use exercise ID with --exercise flag in analyze/webcam commands")

        # Show keypoint reference if verbose
        if args.verbose:
            print()
            print_header("YOLO Pose Keypoint Reference")
            keypoints = [
                (0, "Nose"), (1, "Left Eye"), (2, "Right Eye"),
                (3, "Left Ear"), (4, "Right Ear"), (5, "Left Shoulder"),
                (6, "Right Shoulder"), (7, "Left Elbow"), (8, "Right Elbow"),
                (9, "Left Wrist"), (10, "Right Wrist"), (11, "Left Hip"),
                (12, "Right Hip"), (13, "Left Knee"), (14, "Right Knee"),
                (15, "Left Ankle"), (16, "Right Ankle")
            ]
            for idx, name in keypoints:
                print(f"  {idx:>2}: {name}")

        return 0

    except Exception as e:
        print_error(f"Could not load exercise list: {e}")
        return 1


def _patient_dict(p) -> dict:
    return {"id": p.id, "label": p.label, "notes": p.notes, "created_at": p.created_at,
            "is_builtin": p.is_builtin, "session_count": p.session_count,
            "last_session_at": p.last_session_at}


def cmd_patients(args):
    """Handle the patients command group (add, list, edit, delete, reassign)."""
    try:
        with SessionStore(default_db_path()).open() as store:
            sub = args.patients_cmd
            if sub == "add":
                p = store.add_patient(args.id, label=args.label, notes=args.notes)
                print_success(f"Registered patient {p.id}")
            elif sub == "list":
                patients = store.list_patients()
                if args.json:
                    print(json.dumps([_patient_dict(p) for p in patients], indent=2))
                else:
                    print(f"{'ID':<20} {'Label':<32} {'Sessions':>8}  Last session")
                    for p in patients:
                        last = (p.last_session_at or "")[:16].replace("T", " ")
                        print(f"{p.id:<20} {(p.label or ''):<32} {p.session_count:>8}  {last}")
            elif sub == "edit":
                p = store.update_patient(args.id, label=args.label, notes=args.notes)
                print_success(f"Updated patient {p.id}")
            elif sub == "delete":
                p = store.get_patient(args.id)
                if p is None:
                    raise PatientNotFoundError(f"Patient '{args.id}' not found")
                if p.is_builtin:
                    raise BuiltinPatientError("The built-in 'unassigned' patient cannot be deleted")
                if not args.yes:
                    answer = input(f"Delete patient {p.id} and {p.session_count} sessions? [y/N] ")
                    if answer.strip().lower() not in ("y", "yes"):
                        print_info("Cancelled; nothing deleted")
                        return 0
                report = store.delete_patient(p.id)
                print_success(f"Deleted patient {report.patient_id}: {report.sessions} sessions, "
                              f"{report.events} events, {report.export_files} export files removed")
            elif sub == "reassign":
                store.reassign_session(args.session_id, args.to)
                print_success(f"Reassigned session {args.session_id} to {args.to}")
            else:
                print_error("Usage: patients {add,list,edit,delete,reassign}")
                return 1
        return 0
    except (PatientValidationError, DuplicatePatientError, BuiltinPatientError,
            PatientNotFoundError, SessionNotFoundError) as e:
        print_error(str(e))
        return 1
    except sqlite3.OperationalError as e:
        print_error(f"Database error: {e}")
        return 2


def cmd_sessions(args):
    """Handle the sessions command group (list, show)."""
    from src.ptlog import views
    try:
        with SessionStore(default_db_path()).open() as store:
            if args.sessions_cmd == "list":
                rows = store.list_sessions(args.patient)
                if args.json:
                    print(json.dumps([{
                        "id": r.id, "patient_id": r.patient_id, "start_time": r.start_time, "end_time": r.end_time,
                        "source": r.source, "status": r.status, "exercises": r.exercises,
                        "total_reps": r.total_reps, "avg_form_score": r.avg_form_score} for r in rows], indent=2))
                else:
                    print(f"{'ID':>5}  {'Date':<16} {'Patient':<14} {'Source':<7} {'Exercises':<34} {'Reps':>4}  {'Avg form':<13} Status")
                    for t in views.session_table_rows(store, args.patient):
                        print(f"{t['id']:>5}  {t['date']:<16} {t['patient_id']:<14} {t['source']:<7} "
                              f"{t['exercises'][:34]:<34} {t['total_reps']:>4}  {t['avg_form_score']:<13} {t['status']}")
            elif args.sessions_cmd == "show":
                session = store.load_session(args.session_id)
                if args.json:
                    from dataclasses import asdict
                    events = [asdict(r) for r in store.event_log(args.session_id)]
                    print(json.dumps({"session": {
                        "id": session.id, "patient_id": session.patient_id, "source": session.source,
                        "source_ref": session.source_ref, "status": session.status, "start_time": session.start_time,
                        "end_time": session.end_time, "total_reps": session.total_reps,
                        "avg_form_score": session.avg_form_score, "avg_rom": session.avg_rom,
                        "duration_seconds": session.duration_seconds}, "events": events}, indent=2))
                else:
                    for line in views.session_header_lines(session)[:-1]:
                        print(line)
                    print()
                    for line in views.event_log_lines(store, args.session_id):
                        print(line)
            else:
                print_error("Usage: sessions {list,show}")
                return 1
        return 0
    except SessionNotFoundError as e:
        print_error(str(e))
        return 1
    except sqlite3.OperationalError as e:
        print_error(f"Database error: {e}")
        return 2


def cmd_export(args):
    """Handle the export command: write a session in one or all legacy formats."""
    from src.ptlog.exports import FORMATS, write_export
    fmts = list(FORMATS) if args.format == "all" else [args.format]
    try:
        with SessionStore(default_db_path()).open() as store:
            for fmt in fmts:
                for path in write_export(store, args.session_id, fmt, args.out):
                    print(path)
        return 0
    except SessionNotFoundError as e:
        print_error(str(e))
        return 1
    except (OSError, sqlite3.OperationalError) as e:
        print_error(f"Could not write export: {e}")
        return 2


def cmd_import_legacy(args):
    """Handle import-legacy: bring pre-existing session files into the canonical record once."""
    from src.ptlog.importer import import_legacy
    try:
        with SessionStore(default_db_path()).open() as store:
            report = import_legacy(store, Path(args.sessions_dir), Path(args.obs_dir), dry_run=args.dry_run)
        for e in report.entries:
            if e.outcome == "imported":
                line = "imported (dry run)" if args.dry_run else f"imported → session {e.session_id}"
            elif e.outcome == "duplicate":
                line = f"duplicate ({e.detail})"
            elif e.outcome == "malformed":
                line = f"malformed: {e.detail}"
            else:
                line = f"skipped ({e.detail})"
            print(f"{e.path.name}: {line}")
        suffix = " (dry run, nothing written)" if args.dry_run else ""
        print(f"Totals: imported {report.imported}, duplicate {report.duplicates}, "
              f"malformed {report.malformed}, skipped {report.skipped}{suffix}")
        return 0
    except (OSError, sqlite3.OperationalError) as e:
        print_error(f"Import failed: {e}")
        return 2


def _goal_text(g) -> str:
    parts = []
    if g.target_rom:
        parts.append(f"ROM {g.target_rom:g}°")
    if g.target_reps:
        parts.append(f"reps {g.target_reps}")
    return " | ".join(parts)


def _print_trend(store, trend, patient_id, views):
    print(f"{'date':<17}{'session':>8}  {'reps/target':<12}{'avg form (0-100)':<18}{'avg ROM (°)':<13}"
          f"{'avg rep (s)':<13}{'tempo sd (s)':<14}{'partial (%)':<13}status")
    for r in views.trend_table_rows(trend):
        print(f"{r['date']:<17}{r['session_id']:>8}  {r['reps']:<12}{r['avg_form']:<18}{r['avg_rom']:<13}"
              f"{r['avg_duration']:<13}{r['tempo_sd']:<14}{r['partial_share']:<13}{r['status']}")
    print()
    print("change first→latest:" if trend.enough_for_trend else "")
    for line in views.trend_summary_lines(trend):
        print(f"  {line}")


def cmd_review(args):
    """Handle the review command group."""
    from dataclasses import asdict
    from src.ptlog import review, views
    try:
        with SessionStore(default_db_path()).open() as store:
            sub = args.review_cmd
            if sub == "trends":
                if store.get_patient(args.patient) is None:
                    raise PatientNotFoundError(f"Patient '{args.patient}' not found")
                t = review.trend(store, args.patient, args.exercise, args.period)
                if not t.points:
                    names = review.exercise_names(store, args.patient)
                    print_error(f"No sessions of '{args.exercise}' for {args.patient}. Recorded exercises: "
                                f"{', '.join(names) if names else 'none'}")
                    return 1
                if args.json:
                    print(json.dumps({"exercise": t.exercise, "period": t.period,
                                      "points": [asdict(p) for p in t.points], "summary": t.summary,
                                      "goal": asdict(t.goal) if t.goal else None,
                                      "rom_progress_pct": t.rom_progress_pct,
                                      "enough_for_trend": t.enough_for_trend}, indent=2))
                else:
                    print_header(f"Trends: {args.patient} · {t.exercise} · {views.PERIOD_LABELS[t.period]}")
                    _print_trend(store, t, args.patient, views)
            elif sub == "session":
                view = review.session_review_view(store, args.session_id)
                if args.json:
                    print(json.dumps({
                        "session": {"id": view["session"].id, "patient_id": view["session"].patient_id,
                                    "status": view["session"].status, "start_time": view["session"].start_time},
                        "measures": {k: asdict(v) for k, v in view["measures"].items()},
                        "summary": view["summary"],
                        "review": asdict(view["review"]) if view["review"] else None}, indent=2, default=str))
                else:
                    for line in views.session_header_lines(view["session"]):
                        print(line)
                    print()
                    for line in views.review_lines(view):
                        print(line)
            elif sub == "mark":
                r = store.set_review(args.session_id, args.next_step, args.notes)
                print_success(f"Reviewed session {r.session_id} (next step: {r.next_step})")
            elif sub == "pending":
                rows = review.pending(store, args.patient)
                if args.json:
                    print(json.dumps([{"id": r.id, "start_time": r.start_time, "exercises": r.exercises,
                                       "total_reps": r.total_reps, "status": r.status} for r in rows], indent=2))
                else:
                    print(f"{'session':>7}  {'date':<17}{'exercises':<34}{'reps':>5}  status")
                    for r in rows:
                        print(f"{r.id:>7}  {views.date_minute(r.start_time):<17}{', '.join(r.exercises)[:34]:<34}"
                              f"{(r.total_reps or 0):>5}  {r.status}")
                    if not rows:
                        print("No sessions pending review.")
            elif sub == "flags":
                if store.get_patient(args.patient) is None:
                    raise PatientNotFoundError(f"Patient '{args.patient}' not found")
                result = review.flags_for(store, args.patient, args.period)
                if args.json:
                    print(json.dumps({"flags": [asdict(f) for f in result.flags],
                                      "not_evaluated": [asdict(n) for n in result.not_evaluated]}, indent=2))
                else:
                    print_header(f"Flags: {args.patient} · {views.PERIOD_LABELS[args.period]}")
                    for line in views.flag_lines(result):
                        print(line)
            elif sub == "settings":
                if store.get_patient(args.patient) is None:
                    raise PatientNotFoundError(f"Patient '{args.patient}' not found")
                if args.gap_days is not None:
                    store.set_gap_days(args.patient, args.gap_days)
                print(f"Gap threshold: {store.get_gap_days(args.patient)} days")
            elif sub == "compare":
                comp = review.compare(store, args.session_a, args.session_b, args.exercise)
                if args.json:
                    print(json.dumps({"exercise": comp.exercise, "a": comp.a.session_id, "b": comp.b.session_id,
                                      "rows": [asdict(r) for r in comp.rows]}, indent=2))
                else:
                    print_header(f"Compare: {comp.exercise} · session {comp.a.session_id} → session {comp.b.session_id}")
                    print(f"{'measure':<32}{'session ' + str(comp.a.session_id):<18}{'session ' + str(comp.b.session_id):<18}"
                          f"{'change':<14}{'% change':<12}better when")
                    for r in views.comparison_rows(comp):
                        print(f"{r['measure']:<32}{r['a']:<18}{r['b']:<18}{r['change']:<14}{r['pct_change']:<12}{r['better']}")
            elif sub == "goals":
                if store.get_patient(args.patient) is None:
                    raise PatientNotFoundError(f"Patient '{args.patient}' not found")
                goals = store.list_goals(args.patient)
                if args.json:
                    print(json.dumps([asdict(g) for g in goals], indent=2))
                elif not goals:
                    print("No goals set.")
                for g in ([] if args.json else goals):
                    print(f"{g.exercise_name}: {_goal_text(g)}")
            elif sub == "goal":
                if args.goal_cmd == "set":
                    g = store.set_goal(args.patient, args.exercise, target_rom=args.rom, target_reps=args.reps)
                    print_success(f"Goal for {g.exercise_name}: {_goal_text(g)}")
                elif args.goal_cmd == "clear":
                    if store.clear_goal(args.patient, args.exercise):
                        print_success(f"Cleared goal for {args.exercise}")
                    else:
                        print_error(f"No goal set for {args.exercise}")
                        return 1
                else:
                    print_error("Usage: review goal {set,clear}")
                    return 1
            elif sub == "export":
                from src.ptlog.exports import write_review_export
                fmts = ["review_report", "review_csv"] if args.format == "all" else [{"report": "review_report", "csv": "review_csv"}[args.format]]
                for fmt in fmts:
                    print(write_review_export(store, args.patient, args.period, fmt, args.out))
            else:
                print_error("Usage: review {trends,session,mark,pending,flags,settings,compare,goals,goal,export}")
                return 1
        return 0
    except (PatientNotFoundError, SessionNotFoundError, PTLogError, ValueError) as e:
        print_error(str(e))
        return 1
    except sqlite3.OperationalError as e:
        print_error(f"Database error: {e}")
        return 2


def cmd_tracker(args):
    """Handle the tracker command group (caseload roster, programs, assignments, adherence, queue)."""
    from dataclasses import asdict
    from src.ptlog import programs, tracker, views
    try:
        with SessionStore(default_db_path()).open() as store:
            sub = args.tracker_cmd
            if sub == "roster":
                rows = tracker.roster(store, sort=args.sort, program=args.program, needs_attention=args.needs_attention)
                if args.json:
                    print(json.dumps([asdict(r) for r in rows], indent=2))
                else:
                    print(f"{'patient':<14}{'label':<22}{'program':<24}{'last (days)':<13}{'7d':>3} {'30d':>4}  "
                          f"{'adherence':<20}{'pending':>7} {'flags':>5}  {'gap':<4} next step")
                    for t in views.roster_table_rows(rows):
                        program = f"{t['program']} ({t['program_status']})" if t['program'] != "none" else "none"
                        print(f"{t['patient_id']:<14}{t['label'][:21]:<22}{program[:23]:<24}{t['days_since_last']:<13}"
                              f"{t['sessions_7d']:>3} {t['sessions_30d']:>4}  {t['adherence']:<20}{t['pending_reviews']:>7} "
                              f"{t['open_flags']:>5}  {t['practice_gap']:<4} {t['last_next_step']}")
                    if not rows:
                        print("No active patients.")
            elif sub == "programs":
                items = [{"id": p.id, "name": p.name, "description": p.description, "exercise_keys": p.exercise_keys,
                          "exercise_names": p.exercise_names} for p in programs.list_programs()]
                items.append({"id": "custom", "name": "Custom", "description": "Your own list of exercise keys (see --exercises)",
                              "exercise_keys": [], "exercise_names": []})
                if args.json:
                    print(json.dumps(items, indent=2))
                else:
                    for it in items:
                        names = ", ".join(it["exercise_names"]) if it["exercise_names"] else it["description"]
                        print(f"{it['id']:<22}{it['name']:<24}{len(it['exercise_keys']):>2} exercises  {names}")
            elif sub == "assign":
                if args.program:
                    prog = programs.get_program(args.program)
                    if prog is None:
                        print_error(f"Unknown program '{args.program}'; run: tracker programs")
                        return 1
                    keys, name, prog_id = prog.exercise_keys, prog.name, prog.id
                else:
                    keys = [k.strip() for k in args.exercises.split(",") if k.strip()]
                    name, prog_id = "Custom", "custom"
                previous = store.active_assignment(args.patient, args.start) if store.get_patient(args.patient) else None
                a = store.assign_program(args.patient, prog_id, name, keys, args.per_week, args.start, args.end)
                span = f"from {a.start_date}" + (f" to {a.end_date}" if a.end_date else "")
                print_success(f"Assigned {a.program_name} to {args.patient}: {a.sessions_per_week} sessions/week {span}")
                if previous is not None and previous.id != a.id:
                    ended = next((h for h in store.assignment_history(args.patient) if h.id == previous.id), None)
                    if ended is not None:
                        print_info(f"Ended previous assignment ({ended.program_name}) on {ended.end_date}")
            elif sub == "assignments":
                if store.get_patient(args.patient) is None:
                    raise PatientNotFoundError(f"Patient '{args.patient}' not found")
                from src.ptlog import adherence as adherence_mod
                from datetime import date as _date
                history = store.assignment_history(args.patient)
                if args.json:
                    print(json.dumps([dict(asdict(a), status=adherence_mod.assignment_status(a, _date.today())) for a in history], indent=2))
                else:
                    if not history:
                        print("No assignments.")
                    for a in history:
                        status = adherence_mod.assignment_status(a, _date.today())
                        print(f"{a.start_date} → {a.end_date or 'open'}  {a.program_name} ({status})  "
                              f"{a.sessions_per_week}/week  [{', '.join(a.exercise_keys)}]")
            elif sub == "adherence":
                adh = tracker.adherence_for(store, args.patient)
                if args.json:
                    print(json.dumps({"status": adh.status, "percentage": adh.percentage, "note": adh.note,
                                      "assignment": asdict(adh.assignment) if adh.assignment else None,
                                      "weeks": [asdict(w) for w in adh.weeks]}, indent=2))
                else:
                    print_header(f"Adherence: {args.patient}")
                    for line in views.adherence_lines(adh):
                        print(line)
            else:
                print_error("Usage: tracker {roster,programs,assign,assignments,adherence}")
                return 1
        return 0
    except (PatientNotFoundError, SessionNotFoundError, PTLogError, ValueError) as e:
        print_error(str(e))
        return 1
    except sqlite3.OperationalError as e:
        print_error(f"Database error: {e}")
        return 2


def cmd_calibrate(args):
    """Handle the calibrate command for camera setup."""
    print_header("Camera Calibration Guide")

    print("""
    For optimal pose detection, follow these guidelines:
    """)

    print(color_text("1. CAMERA POSITION", Colors.BOLD))
    print("""
       - Place camera 6-10 feet away from exercise area
       - Position at hip height for most exercises
       - Ensure full body is visible in frame
       - Angle slightly downward for floor exercises
    """)

    print(color_text("2. LIGHTING", Colors.BOLD))
    print("""
       - Ensure even lighting (avoid harsh shadows)
       - Face a window or light source (don't backlight)
       - Avoid direct sunlight causing overexposure
    """)

    print(color_text("3. BACKGROUND", Colors.BOLD))
    print("""
       - Use a plain, contrasting background if possible
       - Remove clutter from frame
       - Ensure no mirrors cause duplicate detections
    """)

    print(color_text("4. CLOTHING", Colors.BOLD))
    print("""
       - Wear fitted clothing for better joint visibility
       - Avoid baggy clothes that obscure body shape
       - Contrasting colors with background help detection
    """)

    # Offer to start webcam test
    print()
    response = input(color_text("Would you like to test camera setup? (y/n): ", Colors.CYAN))

    if response.lower() == 'y':
        print()
        print_info("Starting camera test...")
        print_info("Press 'q' to quit, 's' to save screenshot")

        try:
            import cv2
            from ultralytics import YOLO

            model = YOLO("models/yolo11m-pose.pt")
            cap = cv2.VideoCapture(args.camera)

            if not cap.isOpened():
                print_error(f"Could not open camera {args.camera}")
                return 1

            print_success("Camera opened successfully")

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # Run pose detection
                results = model(frame, verbose=False)
                annotated = results[0].plot() if results else frame

                # Add guidance overlay
                h, w = annotated.shape[:2]
                cv2.putText(annotated, "Calibration Mode - Press Q to quit",
                           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                # Check if person detected
                if results and len(results[0].keypoints) > 0:
                    cv2.putText(annotated, "Person Detected!",
                               (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                else:
                    cv2.putText(annotated, "No person detected - adjust position",
                               (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                cv2.imshow("Calibration", annotated)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('s'):
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    cv2.imwrite(f"calibration_{timestamp}.jpg", annotated)
                    print_success(f"Screenshot saved: calibration_{timestamp}.jpg")

            cap.release()
            cv2.destroyAllWindows()
            print_success("Calibration test complete")

        except Exception as e:
            print_error(f"Calibration test failed: {e}")
            return 1

    return 0


# =============================================================================
# INTERACTIVE MODE
# =============================================================================

def interactive_menu():
    """Run an interactive menu for selecting exercises and options."""
    print_header("AI PT Assistant - Interactive Mode")

    while True:
        print()
        print(color_text("Main Menu:", Colors.BOLD))
        print("  1. Start webcam session")
        print("  2. Analyze video file")
        print("  3. View session history")
        print("  4. List exercises")
        print("  5. Camera calibration")
        print("  0. Exit")
        print()

        choice = input(color_text("Select option: ", Colors.CYAN))

        if choice == "0":
            print_info("Goodbye!")
            break
        elif choice == "1":
            # Exercise selection submenu
            print()
            print("Select exercise:")
            exercises = ["knee_extension", "shoulder_flexion", "squat", "hip_abduction", "pushup"]
            for i, ex in enumerate(exercises, 1):
                print(f"  {i}. {ex}")

            ex_choice = input(color_text("Select (1-5): ", Colors.CYAN))
            try:
                exercise = exercises[int(ex_choice) - 1]
                args = argparse.Namespace(
                    exercise=exercise, reps=10, camera=0, record=None, patient=None
                )
                cmd_webcam(args)
            except (ValueError, IndexError):
                print_error("Invalid selection")

        elif choice == "2":
            video_path = input(color_text("Enter video path: ", Colors.CYAN))
            if os.path.exists(video_path):
                args = argparse.Namespace(
                    video=video_path, exercise="knee_extension",
                    output=None, headless=False, patient=None
                )
                cmd_analyze(args)
            else:
                print_error(f"File not found: {video_path}")

        elif choice == "3":
            args = argparse.Namespace(sessions_cmd="list", patient=None, json=False)
            cmd_sessions(args)

        elif choice == "4":
            args = argparse.Namespace(verbose=True)
            cmd_list_exercises(args)

        elif choice == "5":
            args = argparse.Namespace(camera=0)
            cmd_calibrate(args)

        else:
            print_warning("Invalid option")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="AI Physical Therapy Assistant - Command Line Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s analyze --video session.mp4 --exercise knee_extension
  %(prog)s webcam --exercise shoulder_flexion --reps 10
  %(prog)s patients add P-017 --label "Post-op knee"
  %(prog)s sessions list --patient P-017
  %(prog)s sessions show 3
  %(prog)s list-exercises --verbose
  %(prog)s review trends P-017 --exercise "Knee Extension" --period 30d
  %(prog)s calibrate
  %(prog)s interactive
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a video file")
    analyze_parser.add_argument("--video", "-v", required=True, help="Path to video file")
    analyze_parser.add_argument("--exercise", "-e", default="knee_extension",
                                help="Exercise to analyze")
    analyze_parser.add_argument("--output", "-o", help="Output video path")
    analyze_parser.add_argument("--patient", "-p", default=None,
                                help="Pseudonymous patient ID for the session record (default: unassigned)")
    analyze_parser.add_argument("--headless", action="store_true",
                                help="Don't display video during processing")

    # Webcam command
    webcam_parser = subparsers.add_parser("webcam", help="Start live webcam session")
    webcam_parser.add_argument("--exercise", "-e", default="knee_extension",
                               help="Exercise to track")
    webcam_parser.add_argument("--reps", "-r", type=int, default=10,
                               help="Target rep count")
    webcam_parser.add_argument("--camera", "-c", type=int, default=0,
                               help="Camera device ID")
    webcam_parser.add_argument("--record", help="Record session to file")
    webcam_parser.add_argument("--patient", "-p", default=None,
                               help="Pseudonymous patient ID for the session record (default: unassigned)")

    # List exercises command
    list_parser = subparsers.add_parser("list-exercises", help="List available exercises")
    list_parser.add_argument("--verbose", "-v", action="store_true",
                             help="Show keypoint reference")

    # Patients command group
    patients_parser = subparsers.add_parser("patients", help="Manage pseudonymous patients")
    patients_sub = patients_parser.add_subparsers(dest="patients_cmd")
    pa = patients_sub.add_parser("add", help="Register a patient")
    pa.add_argument("id", help="Pseudonymous ID: 1-32 letters, digits, or hyphens")
    pa.add_argument("--label", default=None, help="Short label (max 60 chars, no identifying text)")
    pa.add_argument("--notes", default=None, help="Free-text notes")
    pl = patients_sub.add_parser("list", help="List patients")
    pl.add_argument("--json", action="store_true", help="Output JSON")
    pe = patients_sub.add_parser("edit", help="Edit a patient's label or notes")
    pe.add_argument("id")
    pe.add_argument("--label", default=None)
    pe.add_argument("--notes", default=None)
    pd_ = patients_sub.add_parser("delete", help="Delete a patient and all their sessions")
    pd_.add_argument("id")
    pd_.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    pr = patients_sub.add_parser("reassign", help="Move a session to another patient")
    pr.add_argument("session_id", type=int)
    pr.add_argument("--to", required=True, help="Target patient ID")

    # Sessions command group
    sessions_parser = subparsers.add_parser("sessions", help="Browse recorded sessions")
    sessions_sub = sessions_parser.add_subparsers(dest="sessions_cmd")
    sl = sessions_sub.add_parser("list", help="List sessions newest first")
    sl.add_argument("--patient", "-p", default=None, help="Only this patient's sessions")
    sl.add_argument("--json", action="store_true", help="Output JSON")
    ss = sessions_sub.add_parser("show", help="Show a session's full event log")
    ss.add_argument("session_id", type=int)
    ss.add_argument("--json", action="store_true", help="Output JSON")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export a session in a legacy file format")
    export_parser.add_argument("session_id", type=int)
    export_parser.add_argument("--format", "-f", required=True,
                               choices=["pta_log", "observation_json", "csv_report", "text_log", "all"])
    export_parser.add_argument("--out", "-o", default=None, help="Output directory (default: exports/)")

    # Import legacy command
    import_parser = subparsers.add_parser("import-legacy", help="Import pre-existing session files once")
    import_parser.add_argument("--sessions-dir", default="sessions", help="Folder of legacy session JSON files")
    import_parser.add_argument("--obs-dir", default="observation_logs", help="Folder of legacy observation logs")
    import_parser.add_argument("--dry-run", action="store_true", help="Report what would be imported without writing")

    # Review command group
    review_parser = subparsers.add_parser("review", help="Review a patient's sessions over time")
    review_sub = review_parser.add_subparsers(dest="review_cmd")
    rt = review_sub.add_parser("trends", help="Per-session measures for one exercise over a period")
    rt.add_argument("patient")
    rt.add_argument("--exercise", "-e", required=True, help="Exercise name as recorded")
    rt.add_argument("--period", default="all", choices=["14d", "30d", "90d", "all"])
    rt.add_argument("--json", action="store_true")
    rs = review_sub.add_parser("session", help="A session's measures, per-session summary, and review")
    rs.add_argument("session_id", type=int)
    rs.add_argument("--json", action="store_true")
    rm = review_sub.add_parser("mark", help="Record the review of a session")
    rm.add_argument("session_id", type=int)
    rm.add_argument("--next-step", required=True, choices=["continue", "progress", "regress", "hold"])
    rm.add_argument("--notes", default=None, help="Clinical notes (no names, dates of birth, or record numbers)")
    rp = review_sub.add_parser("pending", help="Sessions still waiting for a review")
    rp.add_argument("patient")
    rp.add_argument("--json", action="store_true")

    rf = review_sub.add_parser("flags", help="Patterns that need attention, with evidence")
    rf.add_argument("patient")
    rf.add_argument("--period", default="all", choices=["14d", "30d", "90d", "all"])
    rf.add_argument("--json", action="store_true")
    rg = review_sub.add_parser("settings", help="Show or set the patient's practice-gap threshold")
    rg.add_argument("patient")
    rg.add_argument("--gap-days", type=int, default=None, help="Days without practice that raise a flag (1-90)")

    rc = review_sub.add_parser("compare", help="Compare two sessions of one exercise side by side")
    rc.add_argument("session_a", type=int)
    rc.add_argument("session_b", type=int)
    rc.add_argument("--exercise", "-e", default=None, help="Needed when the sessions share several exercises")
    rc.add_argument("--json", action="store_true")

    rgl = review_sub.add_parser("goals", help="List a patient's goals")
    rgl.add_argument("patient")
    rgl.add_argument("--json", action="store_true")
    rgo = review_sub.add_parser("goal", help="Set or clear a goal for one exercise")
    goal_sub = rgo.add_subparsers(dest="goal_cmd")
    gs = goal_sub.add_parser("set")
    gs.add_argument("patient")
    gs.add_argument("--exercise", "-e", required=True)
    gs.add_argument("--rom", type=float, default=None, help="Target range of motion in degrees (1-180)")
    gs.add_argument("--reps", type=int, default=None, help="Target reps (at least 1)")
    gc = goal_sub.add_parser("clear")
    gc.add_argument("patient")
    gc.add_argument("--exercise", "-e", required=True)
    rx = review_sub.add_parser("export", help="Export a review summary as a text report and/or CSV")
    rx.add_argument("patient")
    rx.add_argument("--period", default="all", choices=["14d", "30d", "90d", "all"])
    rx.add_argument("--format", "-f", required=True, choices=["report", "csv", "all"])
    rx.add_argument("--out", "-o", default=None, help="Output directory (default: exports/)")

    # Tracker command group
    tracker_parser = subparsers.add_parser("tracker", help="Manage the caseload: roster, programs, adherence, queue")
    tracker_sub = tracker_parser.add_subparsers(dest="tracker_cmd")
    tr = tracker_sub.add_parser("roster", help="Every active patient at a glance")
    tr.add_argument("--sort", default="attention", choices=["attention", "id"])
    tr.add_argument("--program", default=None, help="Only patients on this program id")
    tr.add_argument("--needs-attention", action="store_true")
    tr.add_argument("--json", action="store_true")
    tp = tracker_sub.add_parser("programs", help="Pre-built programs from the configuration")
    tp.add_argument("--json", action="store_true")

    ta = tracker_sub.add_parser("assign", help="Assign a program to a patient (ends any current one)")
    ta.add_argument("patient")
    src = ta.add_mutually_exclusive_group(required=True)
    src.add_argument("--program", default=None, help="Program id from: tracker programs")
    src.add_argument("--exercises", default=None, help="Comma-separated exercise keys for a custom program")
    ta.add_argument("--per-week", type=int, default=3, help="Planned sessions per week (1-14)")
    ta.add_argument("--start", default=None, help="Start date YYYY-MM-DD (default today)")
    ta.add_argument("--end", default=None, help="Optional end date YYYY-MM-DD")
    tas = tracker_sub.add_parser("assignments", help="A patient's assignment history")
    tas.add_argument("patient")
    tas.add_argument("--json", action="store_true")
    tad = tracker_sub.add_parser("adherence", help="Week-by-week adherence to the assigned program")
    tad.add_argument("patient")
    tad.add_argument("--json", action="store_true")

    # Calibrate command
    calibrate_parser = subparsers.add_parser("calibrate", help="Camera setup helper")
    calibrate_parser.add_argument("--camera", "-c", type=int, default=0,
                                  help="Camera device ID")

    # Interactive mode
    subparsers.add_parser("interactive", help="Start interactive menu")

    args = parser.parse_args()

    # Route to appropriate command
    if args.command == "analyze":
        return cmd_analyze(args)
    elif args.command == "webcam":
        return cmd_webcam(args)
    elif args.command == "list-exercises":
        return cmd_list_exercises(args)
    elif args.command == "patients":
        return cmd_patients(args)
    elif args.command == "sessions":
        return cmd_sessions(args)
    elif args.command == "export":
        return cmd_export(args)
    elif args.command == "import-legacy":
        return cmd_import_legacy(args)
    elif args.command == "review":
        return cmd_review(args)
    elif args.command == "tracker":
        return cmd_tracker(args)
    elif args.command == "calibrate":
        return cmd_calibrate(args)
    elif args.command == "interactive":
        interactive_menu()
        return 0
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    try:
        import numpy as np
    except ImportError:
        print("NumPy not installed. Run: pip install numpy")
        sys.exit(1)

    sys.exit(main())
