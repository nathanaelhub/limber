#!/usr/bin/env python3
"""
Command Line Interface for AI Physical Therapy Assistant
=========================================================

This module provides a clean, user-friendly CLI for all PT Assistant functions.

Commands:
    analyze     Process a video file for exercise analysis
    webcam      Start real-time webcam analysis
    report      View or export a session report
    list        List available exercises
    history     View patient session history
    progress    Show progress charts for an exercise
    calibrate   Help set up optimal camera positioning

Usage Examples:
    python cli.py analyze --video session.mp4 --exercise knee_extension
    python cli.py webcam --exercise shoulder_flexion --reps 10
    python cli.py report --session-id 20240115_001
    python cli.py list-exercises
    python cli.py progress --exercise "Knee Extension" --days 30

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

from src.ptlog.models import PatientNotFoundError  # noqa: E402

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


def cmd_report(args):
    """Handle the report command."""
    print_header("AI PT Assistant - Session Report")

    try:
        from src.session_tracker import SessionTracker

        tracker = SessionTracker(data_dir=args.data_dir, patient_id=args.patient or "default")

        if args.session_id:
            # Load specific session
            session = tracker.get_session_by_id(args.session_id)
            if session is None:
                print_error(f"Session not found: {args.session_id}")
                return 1

            print(tracker.generate_session_summary_card(session))

        elif args.list:
            # List all sessions
            sessions = tracker.session_history
            if not sessions:
                print_warning("No sessions found")
                return 0

            print(f"{'Session ID':<35} {'Date':<12} {'Form Score':<12} {'Exercises'}")
            print("-" * 70)
            for s in sessions:
                ex_count = len(s.exercises)
                print(f"{s.session_id:<35} {s.date:<12} {s.overall_form_score:>8.1f}% {ex_count:>8}")

        elif args.latest:
            # Show latest session
            if tracker.session_history:
                latest = tracker.session_history[-1]
                print(tracker.generate_session_summary_card(latest))
            else:
                print_warning("No sessions found")

        else:
            print_info("Use --session-id, --list, or --latest to view reports")

        return 0

    except Exception as e:
        print_error(f"Could not load session data: {e}")
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


def cmd_progress(args):
    """Handle the progress command."""
    print_header(f"Progress Report: {args.exercise}")

    try:
        from src.session_tracker import SessionTracker

        tracker = SessionTracker(data_dir=args.data_dir, patient_id=args.patient or "default")

        progress = tracker.calculate_progress(args.exercise, days_back=args.days)

        if progress is None:
            print_warning(f"Insufficient data for {args.exercise}")
            print_info("Need at least 2 sessions to calculate progress")
            return 0

        print(f"  Sessions Analyzed: {progress.sessions_count}")
        print(f"  Time Period: Last {args.days} days")
        print()

        # ROM Progress
        rom_color = Colors.GREEN if progress.rom_trend == "improving" else (
            Colors.RED if progress.rom_trend == "declining" else Colors.YELLOW
        )
        print(f"  Range of Motion: {color_text(progress.rom_trend.upper(), rom_color)}")
        print(f"    Change: {progress.rom_change_percent:+.1f}%")
        if progress.rom_values:
            print(f"    Current: {progress.rom_values[-1]:.1f}°")
        print()

        # Form Progress
        form_color = Colors.GREEN if progress.form_score_trend == "improving" else (
            Colors.RED if progress.form_score_trend == "declining" else Colors.YELLOW
        )
        print(f"  Form Score: {color_text(progress.form_score_trend.upper(), form_color)}")
        print(f"    Change: {progress.form_score_change:+.1f}%")
        if progress.form_scores:
            print(f"    Current: {progress.form_scores[-1]:.1f}%")

        # Generate chart if requested
        if args.chart:
            print()
            print_info("Generating progress chart...")
            chart_path = f"progress_{args.exercise.lower().replace(' ', '_')}.png"
            tracker.plot_progress(args.exercise, save_path=chart_path)
            if os.path.exists(chart_path):
                print_success(f"Chart saved: {chart_path}")

        return 0

    except Exception as e:
        print_error(f"Could not generate progress report: {e}")
        return 1


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


def cmd_history(args):
    """Handle the history command."""
    print_header("Patient Session History")

    try:
        from src.session_tracker import SessionTracker

        tracker = SessionTracker(data_dir=args.data_dir, patient_id=args.patient or "default")

        if not tracker.session_history:
            print_warning("No session history found")
            return 0

        print(f"Patient ID: {tracker.patient_id}")
        print(f"Total Sessions: {len(tracker.session_history)}")
        print()

        # Summary statistics
        total_reps = 0
        total_exercises = 0
        all_form_scores = []

        for session in tracker.session_history:
            for ex in session.exercises:
                total_reps += ex.reps_completed
                total_exercises += 1
                all_form_scores.append(ex.avg_form_score)

        if all_form_scores:
            print(f"Total Reps (all time): {total_reps}")
            print(f"Average Form Score: {np.mean(all_form_scores):.1f}%")
            print()

        # Show exercises needing attention
        concerns = tracker.get_exercises_needing_attention()
        if concerns:
            print(color_text("Exercises Needing Attention:", Colors.YELLOW))
            for concern in concerns[:3]:
                print(f"  • {concern['exercise']}")
                for reason in concern['reasons']:
                    print(f"      - {reason}")
            print()

        # Export option
        if args.export:
            filepath = tracker.export_patient_history(format=args.export)
            print_success(f"History exported: {filepath}")

        return 0

    except Exception as e:
        print_error(f"Could not load history: {e}")
        import traceback
        traceback.print_exc()
        return 1


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
                    exercise=exercise, reps=10, camera=0, record=None
                )
                cmd_webcam(args)
            except (ValueError, IndexError):
                print_error("Invalid selection")

        elif choice == "2":
            video_path = input(color_text("Enter video path: ", Colors.CYAN))
            if os.path.exists(video_path):
                args = argparse.Namespace(
                    video=video_path, exercise="knee_extension",
                    output=None, report=["json"], headless=False
                )
                cmd_analyze(args)
            else:
                print_error(f"File not found: {video_path}")

        elif choice == "3":
            args = argparse.Namespace(
                data_dir="./sessions", patient=None, session_id=None,
                list=True, latest=False, export=None
            )
            cmd_history(args)

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
  %(prog)s report --latest
  %(prog)s list-exercises --verbose
  %(prog)s progress --exercise "Knee Extension" --days 30 --chart
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

    # Report command
    report_parser = subparsers.add_parser("report", help="View session reports")
    report_parser.add_argument("--session-id", "-s", help="Specific session ID")
    report_parser.add_argument("--list", "-l", action="store_true",
                               help="List all sessions")
    report_parser.add_argument("--latest", action="store_true",
                               help="Show most recent session")
    report_parser.add_argument("--patient", "-p", help="Patient ID")
    report_parser.add_argument("--data-dir", "-d", default="./sessions",
                               help="Session data directory")

    # List exercises command
    list_parser = subparsers.add_parser("list-exercises", help="List available exercises")
    list_parser.add_argument("--verbose", "-v", action="store_true",
                             help="Show keypoint reference")

    # Progress command
    progress_parser = subparsers.add_parser("progress", help="Show progress report")
    progress_parser.add_argument("--exercise", "-e", required=True,
                                 help="Exercise name")
    progress_parser.add_argument("--days", "-d", type=int, default=30,
                                 help="Days of history to analyze")
    progress_parser.add_argument("--chart", "-c", action="store_true",
                                 help="Generate progress chart")
    progress_parser.add_argument("--patient", "-p", help="Patient ID")
    progress_parser.add_argument("--data-dir", default="./sessions",
                                 help="Session data directory")

    # History command
    history_parser = subparsers.add_parser("history", help="View patient history")
    history_parser.add_argument("--patient", "-p", help="Patient ID")
    history_parser.add_argument("--data-dir", "-d", default="./sessions",
                                help="Session data directory")
    history_parser.add_argument("--export", "-e", choices=["json", "csv"],
                                help="Export format")

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
    elif args.command == "report":
        return cmd_report(args)
    elif args.command == "list-exercises":
        return cmd_list_exercises(args)
    elif args.command == "progress":
        return cmd_progress(args)
    elif args.command == "history":
        return cmd_history(args)
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
