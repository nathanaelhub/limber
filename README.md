# AI Physical Therapy Assistant

An intelligent exercise monitoring system using YOLO11 pose estimation to provide real-time feedback on physical therapy exercises.

## Features

- **Real-time pose detection** using YOLO11 pose estimation
- **Rep counting** with state machine logic
- **Form assessment** with biomechanical checks
- **One canonical session record** (local SQLite) with pseudonymous patients, crash-safe logging, and exports in the legacy PTA-Log, JSON, CSV, and text formats
- **Review over time**: trends per exercise, attention flags with evidence, side-by-side comparison, session reviews with notes and next steps, goals, and review summary exports
- **Multiple interfaces**: CLI, Web (Streamlit), and programmatic API

## Installation

```bash
# Clone the repository
git clone https://github.com/nathanaelhub/pt-assist.git
cd pt-assist

# Create and activate a virtual environment (Python 3.11-3.13; 3.14 lacks torch wheels)
python3.13 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Download YOLO11 pose model (required, ~40MB)
mkdir -p models
wget -O models/yolo11m-pose.pt https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m-pose.pt
# Or download manually from: https://docs.ultralytics.com/models/yolo11/
```

## Camera Setup

Camera indices (0, 1, 2, etc.) are assigned by your operating system and vary per machine.

**Find your cameras:**
```bash
# List available cameras (macOS)
system_profiler SPCameraDataType

# Or use the built-in scanner
python -c "
import cv2
for i in range(5):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        w, h = int(cap.get(3)), int(cap.get(4))
        print(f'Camera {i}: {w}x{h}')
        cap.release()
"
```

**Common camera indices:**
- `0` - Usually the built-in webcam (FaceTime, etc.)
- `1`, `2` - External cameras (USB webcams, DJI Osmo, etc.)

## Quick Start

```bash
# Register a patient (pseudonymous ID only: letters, digits, hyphens)
python interfaces/cli.py patients add P-017 --label "Post-op knee"

# Analyze a video file for that patient
python analyze.py video --input your_video.mp4 --exercise knee_extension --patient P-017

# Start webcam session (default camera 0); without --patient it is recorded under "unassigned"
python analyze.py webcam --exercise shoulder_flexion --patient P-017

# Use a specific camera
python analyze.py webcam --exercise squat --camera 2

# Browse and export what was recorded
python interfaces/cli.py sessions list --patient P-017
python interfaces/cli.py sessions show 3
python interfaces/cli.py export 3 --format all

# Bring pre-existing files in sessions/ and observation_logs/ into the record (once)
python interfaces/cli.py import-legacy --dry-run

# Review a patient's course of care: trends, flags, comparison, session reviews, goals, exports
python interfaces/cli.py review trends P-017 --exercise "Knee Extension" --period 30d
python interfaces/cli.py review flags P-017
python interfaces/cli.py review mark 3 --next-step progress --notes "post-op week 3"
python interfaces/cli.py review export P-017 --format all

# Launch web interface
streamlit run interfaces/app.py
```

**Where data lives:** every session is written to one local SQLite file, `data/ptassist.db`
(set `PTASSIST_DB=/path/to/file.db` to use another location). Exports default to `exports/`.
Both folders are ignored by git. Patients are identified only by a pseudonymous ID; names,
dates of birth, and record numbers are rejected.

**Webcam Controls:**
- `q` - Quit
- `r` - Reset rep count
- `p` - Pause/Resume
- `n` - Next exercise
- `s` - Save frame

## Supported Exercises

| Exercise | Command | Description |
|----------|---------|-------------|
| Knee Extension | `knee_extension` / `knee_extension_right` | Seated leg extension |
| Shoulder Flexion | `shoulder_flexion` / `shoulder_flexion_right` | Standing arm raise |
| Squat | `squat` / `partial_squat` | Bodyweight squat |
| Hip Abduction | `hip_abduction` / `hip_abduction_right` | Side leg raise |
| Hip Flexion | `seated_hip_flexion` / `seated_hip_flexion_right` | Seated knee lift |
| Push-up | `pushup` / `pushup_right` | Upper body exercise |
| Elbow Flexion | `elbow_flexion` / `elbow_flexion_right` | Bicep curl |
| Trunk Flexion | `trunk_flexion` | Seated forward bend |

**Pre-built Programs:** `knee_rehab`, `shoulder_mobility`, `hip_strengthening`, `general_conditioning`

## Project Structure

```
ai-pt-assistant/
├── analyze.py              # Core analysis engine (pose, rep counting, runner loops)
├── config.yaml             # Exercise configurations
├── requirements.txt        # Dependencies
├── src/
│   ├── utils.py            # Helper functions
│   ├── form_assessment.py  # Form checking
│   ├── session_summary.py  # Clinical summary of one session
│   └── ptlog/              # Canonical record: store, recorder, measures, flags, review, views, exports, importer
├── interfaces/
│   ├── cli.py              # Command-line interface (patients, sessions, review, export, import-legacy)
│   └── app.py              # Streamlit web app
├── specs/                  # Spec Kit feature specs, plans, and tasks
├── data/                   # ptassist.db (created on first run, git-ignored)
├── exports/                # Session exports (git-ignored)
└── tests/                  # Test suite (pytest)
```

## Documentation

- [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) - Detailed project documentation
- [docs/presentation/slides.md](docs/presentation/slides.md) - Classroom presentation
- [config.yaml](config.yaml) - Exercise configurations with clinical notes

## Requirements

- Python 3.8+
- Webcam (for live sessions)
- See `requirements.txt` for Python packages

## License

Educational project - see LICENSE for details.
