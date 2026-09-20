# AI Physical Therapy Assistant - Project Overview

## Executive Summary

The **AI Physical Therapy Assistant** is a computer vision application that uses YOLO11 pose estimation to monitor and provide feedback on physical therapy exercises. This project demonstrates real-world AI applications in healthcare, combining deep learning with biomechanical analysis to create an intelligent exercise monitoring system.

**Key Technologies:** YOLO11 Pose Estimation, OpenCV, Python, Streamlit

**Primary Use Cases:**
- Home-based PT exercise monitoring
- Telehealth physical therapy sessions
- Clinical PT documentation and progress tracking
- Patient self-service exercise programs

---

## Project Significance

### The Healthcare Challenge

Physical therapy effectiveness depends heavily on:
1. **Correct exercise form** - Poor form can cause injury or slow recovery
2. **Consistent practice** - Patients often struggle with home exercise compliance
3. **Progress tracking** - Therapists need objective measurements over time
4. **Accessibility** - Not all patients can attend frequent in-person sessions

### How AI Solves This

This project leverages **YOLO11 pose estimation** to:
- Detect 17 body keypoints in real-time
- Calculate joint angles mathematically
- Compare movement to clinically-appropriate ranges
- Provide immediate, actionable feedback
- Track progress automatically across sessions

### Real-World Applications

| Setting | Application |
|---------|-------------|
| **Home PT** | Patient performs exercises with webcam guidance |
| **Telehealth** | Therapist monitors patient remotely via video |
| **Clinics** | Automated rep counting and form documentation |
| **Research** | Objective movement analysis for studies |

---

## Project Architecture

```
ai-pt-assistant/
├── analyze.py              # Core analysis engine (main entry point)
├── config.yaml             # Exercise definitions & thresholds
├── requirements.txt        # Python dependencies
│
├── src/
│   ├── __init__.py
│   ├── utils.py            # Angle calculation, keypoint extraction
│   ├── form_assessment.py  # Biomechanical form checking
│   ├── session_summary.py  # Clinical summary of one session
│   ├── live_session.py     # LiveSession: engine + recorder per browser frame (web live page)
│   └── ptlog/              # Canonical session record and review
│       ├── models.py       # Entities with units and definitions
│       ├── store.py        # SQLite store: single writer, reads, migrations, recovery
│       ├── recorder.py     # The only engine-facing adapter
│       ├── measures.py     # Per-session per-exercise measures (derived, never stored)
│       ├── flags.py        # Seven attention rules with thresholds and evidence
│       ├── review.py       # Trends, comparison, reviews, flags, review summary
│       ├── programs.py     # Exercise and program catalog from config.yaml
│       ├── adherence.py    # Assignment weeks, coverage, adherence percentage
│       ├── tracker.py      # Caseload roster, attention sort, cross-patient queue
│       ├── views.py        # Unit-labelled rendering for CLI and web
│       ├── privacy.py      # Pseudonymous-ID and notes rules
│       ├── importer.py     # One-time legacy import
│       └── exports/        # Legacy formats plus review report and CSV
│
├── interfaces/
│   ├── cli.py              # Command-line interface
│   └── app.py              # Streamlit web application
│
├── specs/                  # Spec-driven development artifacts (Spec Kit)
├── tests/
│   ├── test_analysis.py
│   ├── test_form_assessment.py
│   ├── test_ptlog_*.py     # Record, recorder, recovery, exports, import
│   ├── test_app_pages.py   # Headless Streamlit page tests
│   └── fixtures/           # Golden legacy files and synthetic legacy inputs
│
├── data/                   # ptassist.db — the canonical record (git-ignored)
├── exports/                # Session exports (git-ignored)
├── videos/                 # Sample input videos
└── output/                 # Processed videos & screenshots
```

---

## Key Files Breakdown

### `analyze.py` (~1,400 lines)
**The main processing engine**

This is the core of the application, handling:
- Video/webcam input processing
- YOLO11 pose model inference
- Rep counting state machine
- Angle calculation and tracking
- Annotated video output generation

**Key Classes:**
- `ExerciseTracker` - State machine for tracking reps and metrics
- `ExerciseSession` - Data structure for session results
- `RepMetrics` - Per-rep measurements

**Key Functions:**
- `main()` - Process video files
- `analyze_webcam()` - Real-time webcam analysis
- `analyze_single_frame()` - Single image testing
- `generate_session_report()` - Export to JSON/CSV

### `src/form_assessment.py` (~650 lines)
**Intelligent form checking**

Biomechanically-informed analysis of exercise form:
- Joint alignment verification
- Compensation pattern detection
- Left/right symmetry analysis
- Fatigue tracking over reps

**Key Classes:**
- `FormAnalyzer` - Main form assessment engine
- `FormFeedback` - Structured feedback messages
- `OverallFormAssessment` - Complete frame analysis

### `src/live_session.py` (~200 lines)
**Live web sessions**

`LiveSession` runs the engine's per-frame steps for frames that arrive through a callback (the
browser stream) and records through `SessionRecorder`, with `switch()`, `reset()`, `end()`, and
`save_screenshot()`. It mirrors the command-line webcam loop without editing it; an opt-in
parity test on a sample clip guards the two against drift.

### `src/ptlog/` (~1,800 lines)
**The canonical session record**

One local SQLite file holds patients, sessions, exercise sets, reps, partial reps, form
events, and control events. `SessionStore` is the only writer; `SessionRecorder` is the only
code that reads the engine's outputs; `exports/` reproduces the four legacy file formats
from the record; `importer.py` brings pre-existing files in once. Every metric carries a
unit and a plain-language definition.

### `src/ptlog/tracker.py`, `adherence.py`, `programs.py` (~600 lines)
**Multi-patient tracker**

The caseload roster with adherence, pending reviews, and open flags per patient; program
assignment from the configuration's programs with supersession and history; week-by-week
adherence; the cross-patient queue; discharge; and the roster export.

### `src/ptlog/review.py`, `measures.py`, `flags.py` (~900 lines)
**Review over time**

Per-session measures derived from the record, trend series over a period, seven explicit
attention rules that show their evidence, side-by-side comparison, one review per session with
notes and a next step, goals, and the review summary that feeds the text and CSV exports.

### `config.yaml` (~400 lines)
**Exercise configuration**

Defines all exercises with:
- Target keypoint indices
- Angle thresholds (up/down positions)
- Form tolerance ranges
- Clinical notes for each exercise

### `interfaces/cli.py` (~500 lines)
**Command-line interface**

User-friendly terminal interface with:
- Colored output
- Progress bars
- Interactive menus
- Multiple subcommands

### `interfaces/app.py` (~600 lines)
**Streamlit web application**

Browser-based interface featuring:
- Dashboard with quick stats
- Live webcam session page
- Video upload and analysis
- Progress reports with charts
- Educational "How It Works" section

---

## How to Understand the Code

### Recommended Reading Order

**For beginners (understanding the concepts):**
1. `config.yaml` - See how exercises are defined
2. `src/utils.py` - Learn angle calculation math
3. `analyze.py` - Follow the main processing flow
4. `interfaces/app.py` - See the user-facing application

**For developers (extending the code):**
1. `analyze.py:ExerciseTracker` - Understand the state machine
2. `src/form_assessment.py:FormAnalyzer` - See form checking logic
3. `config.yaml` - Add new exercises
4. `src/ptlog/store.py` - Understand the canonical session record

### Key Concepts

#### 1. Pose Estimation
YOLO11 detects 17 body keypoints per person in each frame:
```
0: Nose      5-6: Shoulders    11-12: Hips
1-2: Eyes    7-8: Elbows       13-14: Knees
3-4: Ears    9-10: Wrists      15-16: Ankles
```

#### 2. Angle Calculation
Joint angles are calculated using vector mathematics:
```python
def calculate_angle(point1, vertex, point2):
    vector1 = point1 - vertex
    vector2 = point2 - vertex
    cos_angle = dot(vector1, vector2) / (|vector1| * |vector2|)
    return degrees(arccos(cos_angle))
```

#### 3. Rep Counting State Machine
```
       angle >= up_threshold
  DOWN ────────────────────> UP
    ^                         │
    │   angle <= down_threshold
    └─────────────────────────┘
         (rep counted here)
```

#### 4. Form Assessment
Form score = 40% ROM achievement + 30% smoothness + 30% symmetry

---

## Quick Start Guide

### Installation

```bash
# Clone or download the project
cd ai-pt-assistant

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

```bash
# Analyze a video file
python analyze.py video --input exercise.mp4 --exercise knee_extension

# Start webcam session
python analyze.py webcam --exercise shoulder_flexion

# Run web interface
streamlit run interfaces/app.py

# Use CLI interface
python interfaces/cli.py interactive
```

### Configuration

Edit `config.yaml` to:
- Adjust angle thresholds for exercises
- Add new exercise definitions
- Change target rep counts
- Modify form tolerance ranges

---

## Learning Path

### Beginner Level
1. **Run the demo** - Try the webcam mode with default settings
2. **Explore the web app** - Use Streamlit interface to understand features
3. **Read the "How It Works" page** - Built-in educational content
4. **Examine config.yaml** - See how exercises are configured

### Intermediate Level
1. **Trace the code flow** - Follow a frame from input to output
2. **Add a new exercise** - Create entry in config.yaml
3. **Customize form checks** - Modify form_assessment.py
4. **Export sessions** - `python interfaces/cli.py export <id> --format all`

### Advanced Level
1. **Train custom model** - Use data.yaml for equipment detection
2. **Optimize inference** - Explore model quantization
3. **Build integrations** - Connect to EHR systems
4. **Deploy to production** - Containerize with Docker

---

## Technical Specifications

### System Requirements
- Python 3.8+
- Webcam (for live sessions)
- 4GB+ RAM recommended
- GPU optional (CUDA support available)

### Performance Metrics
- Inference speed: ~30ms/frame (CPU), ~10ms/frame (GPU)
- Supported video formats: MP4, AVI, MOV, MKV
- Resolution: 640x480 to 1920x1080

### Model Details
- Base model: YOLO11m-pose
- Input resolution: 640x640
- Output: 17 keypoints with confidence scores
- Framework: Ultralytics

---

## Important AI Studio Project Features

This project demonstrates best practices for AI applications:

### 1. Clean Code Organization
- Modular architecture with clear separation of concerns
- Consistent naming conventions
- Comprehensive docstrings and comments

### 2. Configuration-Driven Behavior
- All exercise parameters in YAML config
- Easy to add/modify without code changes
- Environment-specific settings supported

### 3. Multiple Interfaces
- Command-line for power users
- Web interface for general users
- Programmatic API for integration

### 4. Educational Documentation
- Inline comments explaining CV concepts
- "How It Works" section in web app
- Learning path from beginner to advanced

### 5. Reproducible Setup
- Complete requirements.txt
- Clear installation instructions
- Sample data and test cases

### 6. Production Considerations
- HIPAA awareness notes (encryption needed)
- Error handling throughout
- Logging and debugging support

---

## Extension Ideas

### Short-term Enhancements
- [ ] Voice feedback using text-to-speech
- [ ] Multiple person tracking
- [ ] Exercise recommendation engine
- [ ] Mobile app wrapper

### Medium-term Features
- [ ] Custom model training for PT equipment
- [ ] Integration with wearable devices
- [ ] Video call integration for telehealth
- [ ] Gamification elements

### Long-term Vision
- [ ] EHR/EMR system integration
- [ ] Insurance documentation automation
- [ ] Multi-language support
- [ ] Clinical trial data collection

---

## References

### YOLO Pose Estimation
- [Ultralytics YOLO Documentation](https://docs.ultralytics.com/)
- [YOLO Pose Keypoint Format](https://docs.ultralytics.com/tasks/pose/)

### Physical Therapy Resources
- APTA Clinical Practice Guidelines
- Biomechanics of Exercise literature

### Computer Vision
- OpenCV Documentation
- NumPy for scientific computing

---

## Contact & Support

For questions about this project:
- Review the code comments and docstrings
- Check the "How It Works" section in the web app
- Examine the test files for usage examples

---

*This project was created for educational purposes to demonstrate AI applications in healthcare settings.*
