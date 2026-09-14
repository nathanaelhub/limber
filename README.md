# AI Physical Therapy Assistant

An intelligent exercise monitoring system using YOLO11 pose estimation to provide real-time feedback on physical therapy exercises.

## Features

- **Real-time pose detection** using YOLO11 pose estimation
- **Rep counting** with state machine logic
- **Form assessment** with biomechanical checks
- **Progress tracking** across multiple sessions
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
# Analyze a video file
python analyze.py video --input your_video.mp4 --exercise knee_extension

# Start webcam session (default camera 0)
python analyze.py webcam --exercise shoulder_flexion

# Use a specific camera
python analyze.py webcam --exercise squat --camera 2

# Launch web interface
streamlit run interfaces/app.py
```

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
├── analyze.py              # Core analysis engine
├── config.yaml             # Exercise configurations
├── requirements.txt        # Dependencies
├── src/
│   ├── utils.py            # Helper functions
│   ├── form_assessment.py  # Form checking
│   └── session_tracker.py  # Progress tracking
├── interfaces/
│   ├── cli.py              # Command-line interface
│   └── app.py              # Streamlit web app
└── tests/                  # Test suite
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
