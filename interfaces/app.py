"""
Streamlit Web Application for AI Physical Therapy Assistant
============================================================

A user-friendly web interface for the PT Assistant, designed for:
- Classroom demonstrations
- Patient self-service sessions
- Therapist monitoring dashboards

Pages:
    1. Home/Dashboard - Overview and quick actions
    2. Live Session - Real-time webcam analysis
    3. Video Analysis - Upload and analyze recorded videos
    4. Progress Report - Historical data and trends
    5. How It Works - Educational content about the technology

Run with:
    streamlit run app.py

Author: AI PT Assistant
"""

import streamlit as st
import cv2
import numpy as np
import tempfile
import time
import json
from pathlib import Path
from datetime import datetime
import sys
import av
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import streamlit-webrtc for live video
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode

# Import YOLO and our utilities
from ultralytics import YOLO
from src.utils import get_angle_from_keypoints, extract_keypoint, calculate_angle

# Import core analysis engine for real video processing
from analyze import main as analyze_video

# Import observation logger helpers
from src.ptlog.store import SessionStore, default_db_path
from src.ptlog import views as ptviews
from src.ptlog.exports import FORMATS, to_observation_dict
from src.ptlog.models import PTLogError
from src.session_tracker import SessionTracker


def _open_store():
    return SessionStore(default_db_path()).open()


def list_observation_logs(patient_id=None):
    """Sessions newest first from the canonical record (drop-in for the retired file lister)."""
    with _open_store() as store:
        return ptviews.session_refs(store, patient_id)


def load_observation_log(ref):
    """Observation-log dict for a session id or SessionRef (drop-in for the retired file loader)."""
    with _open_store() as store:
        return to_observation_dict(store.load_session(int(str(ref))))

# Import Smart PT Summary generator
from src.session_summary import generate_session_summary

# Exercise name → config key mapping
EXERCISE_KEY_MAP = {
    "Knee Extension": "knee_extension",
    "Shoulder Flexion": "shoulder_flexion",
    "Squat": "squat",
    "Hip Abduction": "hip_abduction",
    "Push-up": "pushup",
    "Elbow Flexion": "elbow_flexion",
}

# Page configuration
st.set_page_config(
    page_title="AI PT Assistant",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E88E5;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: bold;
        color: #1E88E5;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #666;
    }
    .form-good { color: #28a745; }
    .form-warning { color: #ffc107; }
    .form-poor { color: #dc3545; }
    .stProgress > div > div > div > div {
        background-color: #1E88E5;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# SESSION STATE INITIALIZATION
# =============================================================================

def init_session_state():
    """Initialize Streamlit session state variables."""
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 'home'
    if 'session_data' not in st.session_state:
        st.session_state.session_data = []
    if 'rep_count' not in st.session_state:
        st.session_state.rep_count = 0
    if 'form_score' not in st.session_state:
        st.session_state.form_score = 0
    if 'is_recording' not in st.session_state:
        st.session_state.is_recording = False
    if 'current_angle' not in st.session_state:
        st.session_state.current_angle = 0
    if 'exercise_state' not in st.session_state:
        st.session_state.exercise_state = 'neutral'


# =============================================================================
# VIDEO PROCESSOR FOR LIVE POSE ESTIMATION
# =============================================================================

# Exercise configurations
EXERCISE_CONFIGS = {
    "Knee Extension": {"keypoints": [11, 13, 15], "up_angle": 170, "down_angle": 90},
    "Shoulder Flexion": {"keypoints": [11, 5, 7], "up_angle": 170, "down_angle": 20},
    "Squat": {"keypoints": [11, 13, 15], "up_angle": 170, "down_angle": 90},
    "Hip Abduction": {"keypoints": [12, 11, 13], "up_angle": 45, "down_angle": 10},
    "Push-up": {"keypoints": [5, 7, 9], "up_angle": 170, "down_angle": 90},
}

@st.cache_resource
def load_pose_model():
    """Load YOLO pose model (cached)."""
    return YOLO("models/yolo11m-pose.pt")


class PoseVideoProcessor(VideoProcessorBase):
    """Video processor for real-time pose estimation."""

    def __init__(self):
        self.model = load_pose_model()
        self.exercise = "Knee Extension"
        self.keypoints_indices = [11, 13, 15]
        self.up_angle = 170
        self.down_angle = 90
        self.tolerance = 15

        # State tracking
        self.rep_count = 0
        self.current_state = "neutral"
        self.current_angle = 0
        self.form_score = 0
        self.angles_history = []

    def set_exercise(self, exercise_name):
        """Set the exercise configuration."""
        if exercise_name in EXERCISE_CONFIGS:
            config = EXERCISE_CONFIGS[exercise_name]
            self.exercise = exercise_name
            self.keypoints_indices = config["keypoints"]
            self.up_angle = config["up_angle"]
            self.down_angle = config["down_angle"]
            self.rep_count = 0
            self.current_state = "neutral"

    def recv(self, frame):
        """Process each video frame."""
        img = frame.to_ndarray(format="bgr24")

        # Run pose estimation
        results = self.model(img, verbose=False)

        # Get annotated frame with skeleton
        annotated = results[0].plot() if results else img.copy()

        # Extract keypoints and calculate angle
        if results and len(results) > 0 and results[0].keypoints is not None:
            if len(results[0].keypoints) > 0:
                keypoints = results[0].keypoints.data[0].cpu().numpy()

                # Calculate angle
                angle = get_angle_from_keypoints(keypoints, self.keypoints_indices)

                if angle is not None:
                    self.current_angle = angle
                    self.angles_history.append(angle)
                    if len(self.angles_history) > 30:
                        self.angles_history.pop(0)

                    # State machine for rep counting
                    prev_state = self.current_state
                    ascending = self.up_angle > self.down_angle

                    if ascending:
                        if angle >= self.up_angle - self.tolerance:
                            self.current_state = "up"
                        elif angle <= self.down_angle + self.tolerance:
                            if prev_state == "up":
                                self.rep_count += 1
                            self.current_state = "down"
                    else:
                        if angle <= self.up_angle + self.tolerance:
                            if prev_state == "down":
                                self.rep_count += 1
                            self.current_state = "up"
                        elif angle >= self.down_angle - self.tolerance:
                            self.current_state = "down"

                    # Calculate form score (simplified)
                    if len(self.angles_history) > 5:
                        smoothness = 100 - min(np.std(np.diff(self.angles_history[-10:])) * 2, 50)
                        self.form_score = max(0, min(100, smoothness))

                    # Draw angle visualization
                    p1 = extract_keypoint(keypoints, self.keypoints_indices[0])
                    vertex = extract_keypoint(keypoints, self.keypoints_indices[1])
                    p2 = extract_keypoint(keypoints, self.keypoints_indices[2])

                    if all(p is not None for p in [p1, vertex, p2]):
                        v = tuple(vertex.astype(int))
                        cv2.putText(annotated, f"{angle:.1f}", (v[0]+15, v[1]-15),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        # Draw metrics panel on LEFT side (to avoid cutoff on right)
        h, w = annotated.shape[:2]
        panel_w = 220
        panel_h = 160

        # Semi-transparent background panel on left
        overlay = annotated.copy()
        cv2.rectangle(overlay, (0, 0), (panel_w, panel_h), (40, 40, 40), -1)
        cv2.addWeighted(overlay, 0.7, annotated, 0.3, 0, annotated)

        # Exercise name
        cv2.putText(annotated, self.exercise, (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        # Rep count (large)
        cv2.putText(annotated, f"Reps: {self.rep_count}", (10, 65),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        # Angle
        cv2.putText(annotated, f"Angle: {self.current_angle:.1f}", (10, 100),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        # Phase
        cv2.putText(annotated, f"Phase: {self.current_state.upper()}", (10, 130),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        # Form score
        cv2.putText(annotated, f"Form: {self.form_score:.0f}%", (10, 155),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        return av.VideoFrame.from_ndarray(annotated, format="bgr24")


# =============================================================================
# SIDEBAR NAVIGATION
# =============================================================================

def render_sidebar():
    """Render the sidebar navigation."""
    with st.sidebar:
        st.markdown("""
            <div style="text-align: center; padding: 10px 0;">
                <div style="font-size: 3rem;">🏥</div>
                <div style="font-size: 1.4rem; font-weight: bold;">PT Assistant</div>
            </div>
        """, unsafe_allow_html=True)
        st.markdown("---")

        # Navigation
        st.markdown("### Navigation")
        pages = {
            'home': '🏠 Dashboard',
            'live': '📹 Live Session',
            'video': '🎬 Video Analysis',
            'patients': '👥 Patients',
            'sessions': '📋 Sessions',
            'pt_summary': '🩺 PT Summary',
            'obs_logs': '🔬 Observation Logs',
            'progress': '📊 Progress Report',
            'learn': '📚 How It Works'
        }

        for page_id, page_name in pages.items():
            if st.button(page_name, key=f"nav_{page_id}", use_container_width=True):
                st.session_state.current_page = page_id
                st.rerun()

        st.markdown("---")

        # Patient (pseudonymous IDs from the canonical record)
        st.markdown("### Patient")
        with _open_store() as store:
            patients = store.list_patients()
        ids = [p.id for p in patients]
        labels = {p.id: (f"{p.id} · {p.label}" if p.label else p.id) for p in patients}
        current = st.session_state.get("patient_id") or "unassigned"
        st.session_state.patient_id = st.selectbox(
            "Patient", ids, index=ids.index(current) if current in ids else 0,
            format_func=lambda i: labels.get(i, i), key="patient_select")

        st.markdown("### Settings")
        st.toggle("Show Technical Details", key="show_technical")

        st.markdown("---")
        st.caption("AI PT Assistant v1.0")
        st.caption("Powered by YOLO11 Pose Estimation")


# =============================================================================
# PAGE: HOME DASHBOARD
# =============================================================================

def page_home():
    """Render the home dashboard page."""
    st.markdown('<p class="main-header">AI Physical Therapy Assistant</p>',
                unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Intelligent exercise monitoring powered by computer vision</p>',
                unsafe_allow_html=True)

    # Quick stats — pull real data from observation logs
    col1, col2, col3, col4 = st.columns(4)

    obs_log_files = list_observation_logs()
    total_sessions = len(obs_log_files)
    total_reps_all = 0
    form_scores_all = []
    rom_all = []
    for lf in obs_log_files:
        try:
            ld = load_observation_log(str(lf))
            s = ld.get("summary", {})
            total_reps_all += s.get("total_reps", 0)
            if s.get("avg_form_score"):
                form_scores_all.append(s["avg_form_score"])
            if s.get("avg_rom"):
                rom_all.append(s["avg_rom"])
        except Exception:
            pass
    overall_form = f"{sum(form_scores_all)/len(form_scores_all):.0f}%" if form_scores_all else "N/A"
    overall_rom = f"{sum(rom_all)/len(rom_all):.1f}°" if rom_all else "N/A"

    with col1:
        st.metric("Observation Sessions", total_sessions)
    with col2:
        st.metric("Total Reps Logged", total_reps_all)
    with col3:
        st.metric("Avg Form Score", overall_form)
    with col4:
        st.metric("Avg ROM", overall_rom)

    st.markdown("---")

    # Quick actions
    st.markdown("### Quick Actions")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 📹 Start Live Session")
        st.write("Real-time exercise monitoring with your webcam")
        if st.button("Start Session", type="primary", key="start_live"):
            st.session_state.current_page = 'live'
            st.rerun()

    with col2:
        st.markdown("#### 🎬 Analyze Video")
        st.write("Upload and analyze a recorded exercise video")
        if st.button("Upload Video", key="upload_video"):
            st.session_state.current_page = 'video'
            st.rerun()

    with col3:
        st.markdown("#### 🔬 Observation Logs")
        st.write("Review per-rep event logs from past sessions")
        if st.button("View Logs", key="view_obs_logs"):
            st.session_state.current_page = 'obs_logs'
            st.rerun()

    st.markdown("---")

    # Recent activity
    st.markdown("### Recent Sessions")

    # Sample recent sessions (would be loaded from session_tracker in production)
    recent_sessions = [
        {"date": "2024-01-15", "exercise": "Knee Extension", "reps": 10, "form": 85},
        {"date": "2024-01-14", "exercise": "Shoulder Flexion", "reps": 12, "form": 78},
        {"date": "2024-01-13", "exercise": "Squats", "reps": 8, "form": 82},
    ]

    for session in recent_sessions:
        col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
        with col1:
            st.write(f"📅 {session['date']}")
        with col2:
            st.write(f"🏋️ {session['exercise']}")
        with col3:
            st.write(f"🔄 {session['reps']} reps")
        with col4:
            form_class = "form-good" if session['form'] >= 80 else ("form-warning" if session['form'] >= 60 else "form-poor")
            st.markdown(f'<span class="{form_class}">✓ {session["form"]}%</span>',
                       unsafe_allow_html=True)


# =============================================================================
# PAGE: LIVE SESSION
# =============================================================================

def page_live_session():
    """Render the live session page with real webcam support."""
    st.markdown("## 📹 Live PT Session")

    # Hide webrtc default icons and fullscreen toolbar
    st.markdown("""
        <style>
        /* Hide the fullscreen toolbar button */
        .stElementToolbar,
        [data-testid="stElementToolbar"] {
            display: none !important;
        }
        /* Make video container cleaner */
        .stApp video {
            border-radius: 8px;
            border: 2px solid #333;
        }
        </style>
    """, unsafe_allow_html=True)

    # Exercise and camera selection
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        exercise = st.selectbox(
            "Select Exercise",
            list(EXERCISE_CONFIGS.keys()),
            key="exercise_select"
        )

    with col2:
        target_reps = st.number_input("Target Reps", min_value=1, max_value=50, value=10)

    with col3:
        camera_option = st.selectbox(
            "Camera",
            ["Default", "Front Camera", "Back Camera"],
            key="camera_select",
            help="Select which camera to use"
        )

    st.markdown("---")

    # CLI quality note
    st.warning("**💡 For best video quality**, use the command line: `python analyze.py webcam --exercise \"" + exercise + "\"`")

    st.info("**Instructions:** Allow camera access when prompted. The pose estimation will start automatically. Press 'STOP' to end the session.")

    # HD video constraints with camera selection
    video_config = {
        "width": {"min": 1280, "ideal": 1920},
        "height": {"min": 720, "ideal": 1080},
        "frameRate": {"ideal": 30}
    }

    # Add facing mode based on camera selection
    if camera_option == "Front Camera":
        video_config["facingMode"] = "user"
    elif camera_option == "Back Camera":
        video_config["facingMode"] = "environment"

    video_constraints = {
        "video": video_config,
        "audio": False
    }

    # RTC configuration
    rtc_config = {
        "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}],
    }

    # Create the webrtc streamer with pose estimation
    ctx = webrtc_streamer(
        key=f"pose-estimation-{camera_option}",  # Key changes with camera to force refresh
        mode=WebRtcMode.SENDRECV,
        video_processor_factory=PoseVideoProcessor,
        media_stream_constraints=video_constraints,
        async_processing=True,
        rtc_configuration=rtc_config,
        video_html_attrs={
            "style": {"width": "100%", "max-width": "1280px"},
            "autoPlay": True,
            "muted": True
        }
    )

    # Update exercise config when selection changes
    if ctx.video_processor:
        ctx.video_processor.set_exercise(exercise)

    st.markdown("---")

    # Info panel
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### Exercise Info")
        if exercise in EXERCISE_CONFIGS:
            config = EXERCISE_CONFIGS[exercise]
            st.write(f"**Keypoints:** {config['keypoints']}")
            st.write(f"**Up Angle:** {config['up_angle']}°")
            st.write(f"**Down Angle:** {config['down_angle']}°")

    with col2:
        st.markdown("### Target")
        st.metric("Target Reps", target_reps)

    with col3:
        st.markdown("### Tips")
        tips = {
            "Knee Extension": "Keep your back against the seat",
            "Shoulder Flexion": "Don't arch your back",
            "Squat": "Keep knees over toes",
            "Hip Abduction": "Keep trunk stable",
            "Push-up": "Maintain straight body line"
        }
        st.info(tips.get(exercise, "Maintain good form"))

    # Controls
    st.markdown("---")
    st.markdown("### Session Notes")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("📸 Save Screenshot"):
            st.toast("Screenshot saved!")

    with col2:
        if st.button("💾 Save Session"):
            st.toast("Session saved!")


# =============================================================================
# PAGE: VIDEO ANALYSIS
# =============================================================================

def page_video_analysis():
    """Render the video analysis page."""
    st.markdown("## 🎬 Video Analysis")

    # File upload
    uploaded_file = st.file_uploader(
        "Upload a video file",
        type=['mp4', 'avi', 'mov', 'mkv'],
        help="Upload a video of your exercise session for analysis"
    )

    if uploaded_file is not None:
        # Save uploaded file temporarily
        tfile = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
        tfile.write(uploaded_file.read())
        video_path = tfile.name

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### Original Video")
            st.video(video_path)

        with col2:
            st.markdown("### Analysis Settings")

            exercise = st.selectbox(
                "Exercise Type",
                list(EXERCISE_KEY_MAP.keys())
            )

            gen_annotated = st.checkbox("Generate annotated video", value=True, key="gen_annotated")
            gen_report = st.checkbox("Export detailed report", value=True, key="gen_report")

            if st.button("🔍 Analyze Video", type="primary"):
                exercise_key = EXERCISE_KEY_MAP.get(exercise, "knee_extension")
                base_dir = Path(__file__).parent.parent
                config_path = str(base_dir / "config.yaml")
                model_path = str(base_dir / "models" / "yolo11m-pose.pt")

                annotated_path = None
                if gen_annotated:
                    annotated_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                    annotated_path = annotated_tmp.name
                    annotated_tmp.close()

                with st.spinner("Running YOLO pose analysis — this may take a minute..."):
                    try:
                        session = analyze_video(
                            video_path=video_path,
                            exercise_name=exercise_key,
                            output_path=annotated_path,
                            config_path=config_path,
                            model_path=model_path,
                            show_video=False,
                            patient_id=st.session_state.get("patient_id")
                        )
                        st.success("✅ Video analysis complete!")
                    except Exception as e:
                        st.error(f"Analysis failed: {e}")
                        session = None

                if session is not None:
                    st.markdown("---")
                    st.markdown("### Analysis Results")

                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Total Reps", f"{session.total_reps}/{session.target_reps}")
                    with col2:
                        st.metric("Avg Form Score", f"{session.avg_form_score:.1f}%")
                    with col3:
                        st.metric("Avg ROM", f"{session.avg_rom:.1f}°")
                    with col4:
                        st.metric("Max ROM", f"{session.max_rom:.1f}°")

                    # Annotated video playback
                    if annotated_path and Path(annotated_path).exists():
                        st.markdown("#### Annotated Video")
                        st.video(annotated_path)

                    # Rep-by-rep breakdown
                    if session.rep_metrics:
                        import pandas as pd
                        from dataclasses import asdict
                        st.markdown("#### Rep-by-Rep Breakdown")
                        df = pd.DataFrame([asdict(r) for r in session.rep_metrics])
                        display_cols = ["rep_number", "min_angle", "max_angle", "rom", "duration_seconds", "form_score"]
                        st.dataframe(df[display_cols].rename(columns={
                            "rep_number": "Rep", "min_angle": "Min °", "max_angle": "Max °",
                            "rom": "ROM °", "duration_seconds": "Duration (s)", "form_score": "Form %"
                        }), use_container_width=True)

                    # Download options
                    st.markdown("#### Download Results")
                    dl_col1, dl_col2 = st.columns(2)

                    if gen_report:
                        report_data = {
                            "exercise": session.exercise_name,
                            "total_reps": session.total_reps,
                            "target_reps": session.target_reps,
                            "avg_rom": session.avg_rom,
                            "max_rom": session.max_rom,
                            "avg_form_score": session.avg_form_score,
                            "tempo_consistency": session.tempo_consistency,
                        }
                        if session.rep_metrics:
                            from dataclasses import asdict
                            report_data["reps"] = [asdict(r) for r in session.rep_metrics]
                        with dl_col1:
                            st.download_button(
                                "📄 Download Report (JSON)",
                                json.dumps(report_data, indent=2),
                                file_name="analysis_report.json",
                                mime="application/json"
                            )

                    if annotated_path and Path(annotated_path).exists():
                        with open(annotated_path, "rb") as vf:
                            video_bytes = vf.read()
                        with dl_col2:
                            st.download_button(
                                "🎬 Download Annotated Video",
                                video_bytes,
                                file_name="annotated_exercise.mp4",
                                mime="video/mp4"
                            )

    else:
        st.info("👆 Upload a video file to begin analysis")

        # Show example
        st.markdown("### Example Analysis")
        st.image("https://via.placeholder.com/800x400?text=Example+Analysis+Screenshot",
                use_container_width=True)


# =============================================================================
# PAGE: PT SUMMARY (clinical smart summary of a session log)
# =============================================================================

def page_pt_summary():
    """Render the Smart PT Summary clinical dashboard."""

    # ── CSS ──────────────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    .pts-header-card {
        background: linear-gradient(135deg, #0d2137 0%, #102a47 100%);
        border: 1px solid #1e4a7a;
        border-radius: 14px;
        padding: 1.4rem 1.6rem;
        margin-bottom: 1.2rem;
    }
    .pts-metric-row {
        display: flex;
        gap: 1rem;
        flex-wrap: wrap;
        margin-top: 0.8rem;
    }
    .pts-metric-box {
        background: rgba(255,255,255,0.06);
        border-radius: 10px;
        padding: 0.6rem 1rem;
        min-width: 120px;
        text-align: center;
    }
    .pts-metric-label {
        font-size: 0.7rem;
        color: #8aa4c0;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .pts-metric-value {
        font-size: 1.4rem;
        font-weight: 700;
        color: #e8f4ff;
    }
    .pts-section-title {
        font-size: 0.85rem;
        font-weight: 600;
        color: #8aa4c0;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin: 1.2rem 0 0.5rem 0;
    }
    .rep-table th {
        background: #1a2a3a !important;
        color: #8aa4c0 !important;
        font-size: 0.75rem !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("## 🩺 PT Summary")
    st.caption("Clinical smart summary — select a session log and generate an instant report.")

    # ── Session selector ──────────────────────────────────────────────────────
    log_files = list_observation_logs()

    if not log_files:
        st.warning("No observation logs found. Run a video or live session analysis first.")
        return

    # Build display labels: "session_2026-03-23_234320 (2026-03-23)"
    def _label(f):
        try:
            d = load_observation_log(str(f))
            src = d.get("source", "")
            ex = d.get("initial_exercise", "")
            start = d.get("start_time", "")[:16].replace("T", " ")
            return f"{f.stem}  |  {src}  |  {ex}  |  {start}"
        except Exception:
            return f.name

    labels = [_label(f) for f in log_files]
    file_map = {label: f for label, f in zip(labels, log_files)}

    selected_label = st.selectbox(
        "Select session log",
        options=labels,
        index=0,
        key="pts_file_select",
    )
    selected_file = file_map[selected_label]

    generate_btn = st.button("🔍 Generate PT Summary", type="primary", use_container_width=True)

    if not generate_btn and "pts_summary_data" not in st.session_state:
        st.info("Select a session log above and click **Generate PT Summary** to begin.")
        return

    # ── Load & analyse ────────────────────────────────────────────────────────
    if generate_btn:
        with st.spinner("Analysing session…"):
            try:
                data = load_observation_log(str(selected_file))
                summary = generate_session_summary(data)
                st.session_state["pts_summary_data"] = summary
                st.session_state["pts_log_data"] = data
                st.session_state["pts_selected_file"] = selected_file.name
            except Exception as exc:
                st.error(f"Failed to load or analyse log: {exc}")
                return
    else:
        summary = st.session_state.get("pts_summary_data")
        data = st.session_state.get("pts_log_data")
        if not summary or not data:
            st.info("Select a session log above and click **Generate PT Summary** to begin.")
            return

    metrics = summary["metrics"]
    flags = summary["key_flags"]

    # ── Header card ───────────────────────────────────────────────────────────
    start_raw = metrics.get("start_time", "")
    start_display = start_raw[:16].replace("T", "  ") if start_raw else "—"
    source = metrics.get("source", "—").capitalize()
    dur_sec = metrics.get("session_duration_seconds", 0)
    dur_min, dur_s = divmod(int(dur_sec), 60)
    dur_label = f"{dur_min}:{dur_s:02d}" if dur_min else f"{dur_s}s"
    exercises = metrics.get("exercises_performed", [])
    ex_label = " → ".join(exercises) if exercises else "—"

    st.markdown(f"""
    <div class="pts-header-card">
        <div style="font-size:1.1rem; font-weight:700; color:#e8f4ff; margin-bottom:0.2rem;">
            📋 Session Report — {st.session_state.get('pts_selected_file', '')}
        </div>
        <div style="font-size:0.82rem; color:#8aa4c0;">
            {start_display} &nbsp;·&nbsp; {source} &nbsp;·&nbsp; {ex_label}
        </div>
        <div class="pts-metric-row">
            <div class="pts-metric-box">
                <div class="pts-metric-label">Total Reps</div>
                <div class="pts-metric-value">{metrics.get('total_reps', 0)}</div>
            </div>
            <div class="pts-metric-box">
                <div class="pts-metric-label">Duration</div>
                <div class="pts-metric-value">{dur_label}</div>
            </div>
            <div class="pts-metric-box">
                <div class="pts-metric-label">Avg Form</div>
                <div class="pts-metric-value">{metrics.get('avg_form_score', 0):.0f}%</div>
            </div>
            <div class="pts-metric-box">
                <div class="pts-metric-label">Avg ROM</div>
                <div class="pts-metric-value">{metrics.get('avg_rom', 0):.1f}°</div>
            </div>
            <div class="pts-metric-box">
                <div class="pts-metric-label">Rest Periods</div>
                <div class="pts-metric-value">{metrics.get('rest_period_count', 0)}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Reps per exercise breakdown ───────────────────────────────────────────
    rpe = metrics.get("reps_per_exercise", {})
    if rpe:
        cols = st.columns(len(rpe))
        for col, (ex, cnt) in zip(cols, rpe.items()):
            col.metric(ex, f"{cnt} reps")

    st.markdown("---")

    # ── Key Observations ──────────────────────────────────────────────────────
    st.markdown('<div class="pts-section-title">🔎 Key Observations</div>', unsafe_allow_html=True)

    if not flags:
        st.success("No significant observations — session within normal parameters.")
    else:
        for flag in flags:
            sev = flag.get("severity", "info")
            msg = flag.get("message", "")
            cat = flag.get("category", "")
            # Skip rest_period flags here — they are minor and clutter the view
            if cat == "rest_period":
                continue
            if sev == "warning":
                st.warning(msg)
            elif sev == "success":
                st.success(msg)
            elif sev == "error":
                st.error(msg)
            else:
                st.info(msg)

    st.markdown("---")

    # ── Timeline chart: form score over reps ─────────────────────────────────
    events = data.get("events", [])
    rep_events = [e for e in events if e.get("type") == "rep"]

    if rep_events:
        import pandas as pd

        chart_rows = []
        for i, rep in enumerate(rep_events):
            chart_rows.append({
                "Rep #": i + 1,
                "Exercise": rep.get("exercise", "?"),
                "Form Score (%)": rep.get("form_score", 0),
                "ROM (°)": rep.get("rom", 0),
                "Duration (s)": rep.get("duration_seconds", 0),
                "rep_number": rep.get("rep_number", i + 1),
                "timestamp": rep.get("timestamp", ""),
            })
        df_chart = pd.DataFrame(chart_rows)

        st.markdown('<div class="pts-section-title">📈 Form Score Timeline</div>', unsafe_allow_html=True)

        try:
            import plotly.graph_objects as go

            fig = go.Figure()

            # One trace per exercise with distinct colours
            colours = ["#4fc3f7", "#81c784", "#ffb74d", "#e57373", "#ce93d8"]
            ex_list = df_chart["Exercise"].unique().tolist()
            colour_map = {ex: colours[i % len(colours)] for i, ex in enumerate(ex_list)}

            for ex in ex_list:
                ex_df = df_chart[df_chart["Exercise"] == ex]
                fig.add_trace(go.Scatter(
                    x=ex_df["Rep #"],
                    y=ex_df["Form Score (%)"],
                    mode="lines+markers",
                    name=ex,
                    line=dict(color=colour_map[ex], width=2.5),
                    marker=dict(size=8, color=colour_map[ex]),
                    hovertemplate=(
                        "<b>%{text}</b><br>"
                        "Rep %{x}<br>"
                        "Form: %{y:.0f}%<extra></extra>"
                    ),
                    text=[ex] * len(ex_df),
                ))

            # Vertical lines at exercise switches
            ex_changes = [e for e in events if e.get("type") == "exercise_change"]
            for chg in ex_changes:
                # Find the rep index just before this change
                chg_ts = chg.get("timestamp", "")
                switch_rep_idx = None
                for j, row in enumerate(chart_rows):
                    if row["timestamp"] <= chg_ts:
                        switch_rep_idx = row["Rep #"]
                if switch_rep_idx is not None:
                    fig.add_vline(
                        x=switch_rep_idx + 0.5,
                        line_dash="dash",
                        line_color="#ffb74d",
                        annotation_text=f"→ {chg.get('to_exercise','?')}",
                        annotation_font_color="#ffb74d",
                        annotation_position="top right",
                    )

            # Threshold line at 80%
            fig.add_hline(
                y=80,
                line_dash="dot",
                line_color="#e57373",
                annotation_text="80% threshold",
                annotation_font_color="#e57373",
                annotation_position="bottom right",
            )

            fig.update_layout(
                plot_bgcolor="#0d1117",
                paper_bgcolor="#0d1117",
                font_color="#c9d1d9",
                xaxis=dict(
                    title="Rep Number",
                    gridcolor="#21262d",
                    tickmode="linear",
                    tick0=1,
                    dtick=1,
                ),
                yaxis=dict(
                    title="Form Score (%)",
                    gridcolor="#21262d",
                    range=[50, 105],
                ),
                legend=dict(
                    bgcolor="rgba(0,0,0,0)",
                    bordercolor="#21262d",
                ),
                margin=dict(l=40, r=20, t=20, b=40),
                height=320,
            )

            st.plotly_chart(fig, use_container_width=True)

        except ImportError:
            # Fallback to Streamlit's built-in line chart if plotly not available
            st.line_chart(df_chart.set_index("Rep #")[["Form Score (%)"]])

        # ── ROM chart ─────────────────────────────────────────────────────────
        st.markdown('<div class="pts-section-title">📐 ROM by Rep</div>', unsafe_allow_html=True)
        try:
            fig2 = go.Figure()
            for ex in ex_list:
                ex_df = df_chart[df_chart["Exercise"] == ex]
                fig2.add_trace(go.Bar(
                    x=ex_df["Rep #"],
                    y=ex_df["ROM (°)"],
                    name=ex,
                    marker_color=colour_map[ex],
                    opacity=0.85,
                ))
            avg_rom = metrics.get("avg_rom", 0)
            fig2.add_hline(
                y=avg_rom,
                line_dash="dot",
                line_color="#ffffff",
                annotation_text=f"avg {avg_rom:.1f}°",
                annotation_font_color="#ffffff",
                annotation_position="top right",
            )
            fig2.update_layout(
                plot_bgcolor="#0d1117",
                paper_bgcolor="#0d1117",
                font_color="#c9d1d9",
                barmode="overlay",
                xaxis=dict(title="Rep Number", gridcolor="#21262d", tickmode="linear", tick0=1, dtick=1),
                yaxis=dict(title="ROM (°)", gridcolor="#21262d"),
                legend=dict(bgcolor="rgba(0,0,0,0)"),
                margin=dict(l=40, r=20, t=10, b=40),
                height=260,
            )
            st.plotly_chart(fig2, use_container_width=True)
        except Exception:
            st.bar_chart(df_chart.set_index("Rep #")[["ROM (°)"]])

        # ── Rep-by-rep table ──────────────────────────────────────────────────
        st.markdown('<div class="pts-section-title">📋 Rep-by-Rep Breakdown</div>', unsafe_allow_html=True)

        display_df = df_chart[["Rep #", "Exercise", "Form Score (%)", "ROM (°)", "Duration (s)"]].copy()

        def _color_form(val):
            if val >= 90:
                return "background-color: #1b3a1b; color: #81c784"
            elif val >= 80:
                return "background-color: #1b2d1b; color: #a5d6a7"
            elif val >= 70:
                return "background-color: #3a2e10; color: #ffcc80"
            else:
                return "background-color: #3a1010; color: #ef9a9a"

        styled = display_df.style.map(_color_form, subset=["Form Score (%)"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Summary text (collapsible) ────────────────────────────────────────────
    with st.expander("📝 Full Summary Text", expanded=False):
        st.text(summary.get("summary_text", ""))


# =============================================================================
# PAGE: OBSERVATION LOGS (structured per-rep event logs)
# =============================================================================

def page_observation_logs():
    """Render the Observation Logs page — structured per-rep event viewer."""

    # ---- CSS for cards ----
    st.markdown("""
    <style>
    .obs-card {
        background: linear-gradient(135deg, #1a1f36 0%, #1e2540 100%);
        border: 1px solid #2d3561;
        border-radius: 12px;
        padding: 1.1rem 1.3rem;
        margin-bottom: 0.6rem;
    }
    .obs-card-title {
        font-size: 0.75rem;
        color: #8892b0;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.2rem;
    }
    .obs-card-value {
        font-size: 1.7rem;
        font-weight: 700;
        color: #64ffda;
    }
    .obs-card-sub {
        font-size: 0.8rem;
        color: #a8b2d8;
        margin-top: 0.1rem;
    }
    .event-row-rep { border-left: 4px solid #64ffda; padding-left: 0.7rem; margin: 0.3rem 0; }
    .event-row-switch { border-left: 4px solid #ffb347; padding-left: 0.7rem; margin: 0.3rem 0; }
    .event-row-reset { border-left: 4px solid #ff6b6b; padding-left: 0.7rem; margin: 0.3rem 0; }
    .event-row-start { border-left: 4px solid #79c0ff; padding-left: 0.7rem; margin: 0.3rem 0; }
    .event-row-end { border-left: 4px solid #c9d1d9; padding-left: 0.7rem; margin: 0.3rem 0; }
    .badge-video { background:#1f6feb; color:#e6edf3; border-radius:4px; padding:2px 8px; font-size:0.72rem; font-weight:600; }
    .badge-webcam { background:#388bfd20; color:#79c0ff; border: 1px solid #388bfd; border-radius:4px; padding:2px 8px; font-size:0.72rem; font-weight:600; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("## 🔬 Observation Logs")
    st.markdown("*Structured per-rep event logs generated automatically during analysis*")

    # Discover log files
    log_files = list_observation_logs()

    if not log_files:
        st.info(
            "No sessions recorded yet. Run a video or webcam session to create one.\n\n"
            "**Command line:** `python analyze.py video --input videos/Squats.demo.video.mp4 --exercise squat --patient unassigned`"
        )
        return

    # ---- File selector (sidebar column) ----
    col_sidebar, col_main = st.columns([1, 3])

    with col_sidebar:
        st.markdown("### Sessions")

        file_labels = []
        for f in log_files:
            try:
                d = load_observation_log(str(f))
                ex = d.get("initial_exercise", "Unknown")
                ts = d.get("start_time", "")[:16].replace("T", " ")
                src = d.get("source", "video")
                reps = d.get("summary", {}).get("total_reps", "?")
                label = f"{ts}\n{ex} · {reps} reps · {src}"
            except Exception:
                label = f.stem
            file_labels.append(label)

        selected_idx = st.radio(
            "Select session",
            range(len(log_files)),
            format_func=lambda i: file_labels[i],
            label_visibility="collapsed",
        )

        selected_file = log_files[selected_idx]

    with col_main:
        try:
            data = load_observation_log(str(selected_file))
        except Exception as e:
            st.error(f"Could not load log file: {e}")
            return

        summary = data.get("summary", {})
        events = data.get("events", [])
        source = data.get("source", "video")
        start_ts = data.get("start_time", "")[:19].replace("T", " ")
        duration_s = data.get("duration_seconds") or 0
        duration_str = f"{int(duration_s // 60)}m {int(duration_s % 60)}s" if duration_s else "N/A"

        badge_html = (
            '<span class="badge-video">📹 Video</span>'
            if source == "video"
            else '<span class="badge-webcam">🎥 Webcam</span>'
        )

        st.markdown(
            f"**{data.get('initial_exercise','Unknown')}** &nbsp;{badge_html}&nbsp;"
            f"<span style='color:#8892b0;font-size:0.85rem'>{start_ts} &middot; {duration_str}</span>",
            unsafe_allow_html=True,
        )

        # ---- Summary metrics row ----
        total_reps = summary.get("total_reps", 0)
        target_reps = data.get("target_reps", 10)
        avg_form = summary.get("avg_form_score", 0)
        avg_rom = summary.get("avg_rom", 0)
        completion = round(total_reps / target_reps * 100) if target_reps else 0
        form_color = "#64ffda" if avg_form >= 80 else ("#ffb347" if avg_form >= 60 else "#ff6b6b")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Reps Completed", f"{total_reps} / {target_reps}", f"{completion}%")
        c2.metric("Avg Form Score", f"{avg_form:.1f}%")
        c3.metric("Avg ROM", f"{avg_rom:.1f}°")
        c4.metric("Total Events", len(events))

        st.markdown("---")

        # ---- Build rep DataFrame ----
        rep_events = [e for e in events if e.get("type") == "rep"]

        if rep_events:
            tab1, tab2, tab3 = st.tabs(["📊 Charts", "📋 Rep Table", "🗂 Event Timeline"])

            with tab1:
                df_reps = pd.DataFrame(rep_events)

                chart_col1, chart_col2 = st.columns(2)

                with chart_col1:
                    st.markdown("#### Form Score per Rep")
                    chart_df = df_reps.set_index("rep_number")[["form_score"]]
                    st.bar_chart(chart_df, color="#64ffda", height=220)

                with chart_col2:
                    st.markdown("#### Range of Motion per Rep")
                    chart_df2 = df_reps.set_index("rep_number")[["rom"]]
                    st.bar_chart(chart_df2, color="#79c0ff", height=220)

                st.markdown("#### Rep Duration (seconds)")
                dur_df = df_reps.set_index("rep_number")[["duration_seconds"]]
                st.line_chart(dur_df, color="#ffb347", height=180)

                # Angle range visualization
                st.markdown("#### Joint Angle Range per Rep")
                angle_df = df_reps[["rep_number", "min_angle", "max_angle"]].set_index("rep_number")
                st.area_chart(angle_df, height=180)

            with tab2:
                st.markdown("#### Rep-by-Rep Breakdown")
                display_cols = {
                    "rep_number": "Rep",
                    "exercise": "Exercise",
                    "min_angle": "Min °",
                    "max_angle": "Max °",
                    "rom": "ROM °",
                    "duration_seconds": "Duration (s)",
                    "form_score": "Form %",
                }
                available = [c for c in display_cols if c in df_reps.columns]
                renamed = df_reps[available].rename(columns=display_cols)

                # Color-code form score
                def color_form(val):
                    if isinstance(val, (int, float)):
                        if val >= 80:
                            return "color: #64ffda"
                        elif val >= 60:
                            return "color: #ffb347"
                        else:
                            return "color: #ff6b6b"
                    return ""

                styled = renamed.style.map(color_form, subset=["Form %"])
                st.dataframe(styled, use_container_width=True, hide_index=True)

                # Download
                csv_data = df_reps.to_csv(index=False)
                st.download_button(
                    "📥 Download Rep Data (CSV)",
                    csv_data,
                    file_name=f"{selected_file.stem}_reps.csv",
                    mime="text/csv",
                )

            with tab3:
                st.markdown("#### Full Event Timeline")

                event_type_map = {
                    "session_start": ("🟦", "SESSION START", "event-row-start"),
                    "rep":           ("🟢", "REP COMPLETE", "event-row-rep"),
                    "exercise_change": ("🟡", "EXERCISE SWITCH", "event-row-switch"),
                    "reset":         ("🔴", "RESET", "event-row-reset"),
                    "session_end":   ("⬜", "SESSION END", "event-row-end"),
                }

                for evt in events:
                    etype = evt.get("type", "")
                    icon, label, css_class = event_type_map.get(etype, ("⚪", etype.upper(), "event-row-start"))
                    ts = evt.get("timestamp", "")[:19].replace("T", " ")

                    if etype == "rep":
                        detail = (
                            f"**Rep {evt.get('rep_number')}** — {evt.get('exercise')} | "
                            f"ROM {evt.get('rom')}° | Form {evt.get('form_score')}% | "
                            f"{evt.get('duration_seconds')}s"
                        )
                    elif etype == "exercise_change":
                        detail = (
                            f"**{evt.get('from_exercise')}** → **{evt.get('to_exercise')}**"
                        )
                    elif etype == "reset":
                        detail = (
                            f"Reset during **{evt.get('exercise')}** at rep {evt.get('rep_count_at_reset')}"
                        )
                    elif etype == "session_start":
                        detail = (
                            f"Started **{evt.get('exercise')}** · Target {evt.get('target_reps')} reps"
                        )
                    elif etype == "session_end":
                        detail = (
                            f"Total {evt.get('total_reps')} reps · "
                            f"Avg Form {evt.get('avg_form_score')}% · "
                            f"Avg ROM {evt.get('avg_rom')}° · "
                            f"Duration {evt.get('duration_seconds')}s"
                        )
                    else:
                        detail = str(evt)

                    st.markdown(
                        f'<div class="{css_class}">'
                        f"<span style='color:#8892b0;font-size:0.78rem'>{ts}</span> &nbsp; "
                        f"{icon} **{label}** — {detail}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

        else:
            st.info("No rep events recorded in this session.")

        # ---- Warnings ----
        warnings = summary.get("warnings", [])
        if warnings:
            st.markdown("---")
            st.markdown("#### ⚠️ Session Warnings")
            for w in warnings:
                st.warning(w)

        # ---- Exercise breakdown (multi-exercise sessions) ----
        ex_performed = summary.get("exercises_performed", [])
        if len(ex_performed) > 1:
            st.markdown("---")
            st.markdown("#### Exercise Breakdown")
            ex_df = pd.DataFrame(ex_performed)
            ex_df.columns = ["Exercise", "Reps", "Avg Form %", "Avg ROM °"]
            st.dataframe(ex_df, use_container_width=True, hide_index=True)

        # ---- Download full log ----
        st.markdown("---")
        raw_json = json.dumps(data, indent=2)
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "📄 Download Full Log (JSON)",
                raw_json,
                file_name=f"{selected_file.stem}.json",
                mime="application/json",
            )
        with dl2:
            st.caption(f"🗄️ canonical record · session {selected_file.id} · patient {selected_file.patient_id}")


# =============================================================================
# PAGE: PATIENTS (pseudonymous registry)
# =============================================================================

def page_patients():
    """Register, edit, and delete pseudonymous patients (all logic lives in src/ptlog)."""
    st.markdown("## 👥 Patients")
    st.caption("Patients are identified only by a pseudonymous ID. Do not enter names, dates of birth, "
               "or medical record numbers anywhere on this page.")

    with _open_store() as store:
        patients = store.list_patients()

    rows = [{"ID": p.id, "Label": p.label or "", "Sessions": p.session_count,
             "Last session": ptviews.date_minute(p.last_session_at), "Notes": p.notes or ""} for p in patients]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("### Register a patient")
    with st.form("add_patient_form", clear_on_submit=True):
        new_id = st.text_input("Pseudonymous ID", placeholder="P-017", help="1-32 letters, digits, or hyphens")
        new_label = st.text_input("Label (optional)", placeholder="Post-op knee", help="Max 60 characters")
        new_notes = st.text_area("Notes (optional)")
        if st.form_submit_button("Register"):
            try:
                with _open_store() as store:
                    store.add_patient(new_id, label=new_label or None, notes=new_notes or None)
                st.success(f"Registered patient {new_id}")
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))

    editable = [p for p in patients if not p.is_builtin]
    st.markdown("### Edit or delete")
    if not editable:
        st.info("No patients registered yet.")
        return
    pid = st.selectbox("Patient", [p.id for p in editable], key="patients_edit_select")
    current = next(p for p in editable if p.id == pid)
    with st.form("edit_patient_form"):
        label = st.text_input("Label", value=current.label or "")
        notes = st.text_area("Notes", value=current.notes or "")
        if st.form_submit_button("Save changes"):
            try:
                with _open_store() as store:
                    store.update_patient(pid, label=label, notes=notes)
                st.success(f"Updated patient {pid}")
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))
    confirm = st.checkbox(f"I understand this permanently deletes {pid} and its {current.session_count} sessions",
                          key="patients_delete_confirm")
    if st.button("Delete patient", disabled=not confirm, key="patients_delete_button"):
        try:
            with _open_store() as store:
                report = store.delete_patient(pid)
            st.success(f"Deleted {report.patient_id}: {report.sessions} sessions, {report.events} events, "
                       f"{report.export_files} export files removed")
            st.rerun()
        except PTLogError as exc:
            st.error(str(exc))


# =============================================================================
# PAGE: SESSIONS (history and full event log from the canonical record)
# =============================================================================

_EXPORT_MIME = {"pta_log": ("txt", "text/plain"), "observation_json": ("json", "application/json"),
                "csv_report": ("csv", "text/csv"), "text_log": ("log", "text/plain")}
_EXPORT_LABEL = {"pta_log": "PTA-Log text", "observation_json": "Observation JSON",
                 "csv_report": "CSV report", "text_log": "Session text log"}


def page_sessions():
    """Session history newest first, a session's full event log, and the four exports."""
    st.markdown("## 📋 Sessions")
    scope = st.radio("Show", ["Selected patient", "All patients"], horizontal=True, key="sessions_scope")
    patient_filter = st.session_state.get("patient_id") if scope == "Selected patient" else None

    with _open_store() as store:
        rows = ptviews.session_table_rows(store, patient_filter)
    if not rows:
        st.info("No sessions recorded yet for this selection. Run a video or webcam session to create one.")
        return

    table = pd.DataFrame(rows).rename(columns={
        "id": "ID", "date": "Date", "patient_id": "Patient", "source": "Source", "exercises": "Exercises",
        "total_reps": ptviews.metric_label("total_reps"), "avg_form_score": ptviews.metric_label("avg_form_score"),
        "status": "Status"})
    st.dataframe(table, use_container_width=True, hide_index=True)

    ids = [r["id"] for r in rows]
    by_id = {r["id"]: r for r in rows}
    sid = st.selectbox("Open session", ids, key="sessions_open",
                       format_func=lambda i: f"#{i} · {by_id[i]['date']} · {by_id[i]['exercises']} · {by_id[i]['total_reps']} reps")

    with _open_store() as store:
        session = store.load_session(sid)
        header = ptviews.session_header_lines(session)
        lines = ptviews.event_log_lines(store, sid)
        rendered = {fmt: FORMATS[fmt][1](store, session) for fmt in FORMATS}

    st.markdown("  \n".join(header))
    if session.status == "interrupted":
        st.warning("This session was interrupted. The summary is computed from the events recorded before the interruption.")
    with st.expander("Metric definitions"):
        for field in ("rom", "form_score", "duration_seconds", "avg_form_score", "avg_rom"):
            st.markdown(f"**{ptviews.metric_label(field)}** — {ptviews.metric_definition(field)}")
    st.code("\n".join(lines), language=None)

    st.markdown("### Export")
    base = f"{session.patient_id}_{datetime.fromisoformat(session.start_time):%Y%m%d_%H%M%S}"
    cols = st.columns(4)
    for col, fmt in zip(cols, FORMATS):
        ext, mime = _EXPORT_MIME[fmt]
        content = rendered[fmt]
        if isinstance(content, list):
            content = "\n".join(content)
        with col:
            st.download_button(_EXPORT_LABEL[fmt], content, file_name=f"{base}.{ext}", mime=mime, key=f"dl_{fmt}_{sid}")


# =============================================================================
# PAGE: PROGRESS REPORT (trend math from src/session_tracker fed by the record)
# =============================================================================

def page_progress_report():
    """Progress over time for the selected patient, from the canonical record."""
    st.markdown("## 📊 Progress Report")
    pid = st.session_state.get("patient_id") or "unassigned"
    with _open_store() as store:
        history = ptviews.load_session_data_for_trends(store, pid)
    if not history:
        st.info(f"No sessions recorded for patient {pid} yet.")
        return

    exercises = sorted({e.exercise_name for s in history for e in s.exercises})
    col1, col2 = st.columns([2, 1])
    with col1:
        days = st.select_slider("Time period (days)", options=[7, 14, 30, 90, 180, 365], value=30, key="progress_days")
    with col2:
        exercise = st.selectbox("Exercise", exercises, key="progress_exercise")

    tracker = SessionTracker.from_history(history, pid)
    progress = tracker.calculate_progress(exercise, days_back=days)

    total_reps = sum(e.reps_completed for s in history for e in s.exercises)
    form_scores = [s.overall_form_score for s in history if s.exercises]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sessions", len(history))
    c2.metric(ptviews.metric_label("total_reps"), total_reps)
    c3.metric(ptviews.metric_label("avg_form_score"), f"{sum(form_scores) / len(form_scores):.1f}" if form_scores else "n/a")
    c4.metric("ROM trend", progress.rom_trend if progress else "n/a",
              f"{progress.rom_change_percent:+.1f}%" if progress else None)
    st.markdown("---")

    if progress is None:
        st.info("At least two sessions with this exercise inside the period are needed to compute a trend.")
    else:
        chart = pd.DataFrame({"Date": progress.dates, ptviews.metric_label("rom"): progress.rom_values,
                              ptviews.metric_label("form_score"): progress.form_scores}).set_index("Date")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"### {ptviews.metric_label('rom')}")
            st.line_chart(chart[[ptviews.metric_label("rom")]])
            st.caption(ptviews.metric_definition("rom"))
        with col2:
            st.markdown(f"### {ptviews.metric_label('form_score')}")
            st.line_chart(chart[[ptviews.metric_label("form_score")]])
            st.caption(ptviews.metric_definition("form_score"))

    st.markdown("### Areas for attention")
    try:
        concerns = tracker.get_exercises_needing_attention()
    except Exception:
        concerns = []
    if concerns:
        for c in concerns:
            st.warning(f"**{c.get('exercise', '')}** — {', '.join(c.get('concerns', []))}" if isinstance(c, dict) else str(c))
    else:
        st.success("No exercises are flagged for attention in the recorded sessions.")

    st.markdown("---")
    csv_rows = ["date,exercise,reps,form_score,rom_range"] + [
        f"{s.date},{e.exercise_name},{e.reps_completed},{e.avg_form_score:.1f},{e.rom_range:.1f}"
        for s in history for e in s.exercises]
    st.download_button("📊 Export session data (CSV)", "\n".join(csv_rows) + "\n",
                       file_name=f"{pid}_progress.csv", mime="text/csv")


# =============================================================================
# PAGE: HOW IT WORKS (Educational)
# =============================================================================

def page_how_it_works():
    """Render the educational page explaining the technology."""
    st.markdown("## 📚 How It Works")
    st.markdown("*Understanding the AI behind your PT Assistant*")

    # Navigation tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "🎯 Overview",
        "🦴 Pose Estimation",
        "📐 Angle Calculation",
        "🧠 Form Assessment"
    ])

    with tab1:
        st.markdown("""
        ### What is AI Pose Estimation?

        This application uses **YOLO11 Pose Estimation** to detect and track your body
        movements in real-time. Here's the high-level process:

        1. **📹 Video Input** - Camera captures your exercise
        2. **🔍 Detection** - AI identifies your body in each frame
        3. **🦴 Keypoint Extraction** - 17 body landmarks are located
        4. **📐 Angle Calculation** - Joint angles computed from keypoints
        5. **✅ Form Assessment** - Angles compared to target ranges
        6. **💬 Feedback** - Real-time guidance provided

        """)

        st.image("https://via.placeholder.com/800x300?text=Pipeline+Diagram",
                caption="AI Processing Pipeline", use_container_width=True)

        st.markdown("""
        ### Why AI for Physical Therapy?

        - **Consistency**: AI provides objective, repeatable measurements
        - **Accessibility**: PT guidance available at home
        - **Real-time**: Immediate feedback during exercise
        - **Tracking**: Automatic progress documentation
        """)

    with tab2:
        st.markdown("""
        ### YOLO Pose Keypoints

        The AI detects **17 body keypoints** that define your pose:
        """)

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("""
            | Index | Keypoint |
            |-------|----------|
            | 0 | Nose |
            | 1 | Left Eye |
            | 2 | Right Eye |
            | 3 | Left Ear |
            | 4 | Right Ear |
            | 5 | Left Shoulder |
            | 6 | Right Shoulder |
            | 7 | Left Elbow |
            | 8 | Right Elbow |
            """)

        with col2:
            st.markdown("""
            | Index | Keypoint |
            |-------|----------|
            | 9 | Left Wrist |
            | 10 | Right Wrist |
            | 11 | Left Hip |
            | 12 | Right Hip |
            | 13 | Left Knee |
            | 14 | Right Knee |
            | 15 | Left Ankle |
            | 16 | Right Ankle |
            """)

        st.image("https://via.placeholder.com/600x400?text=Keypoint+Diagram",
                caption="Body keypoint locations", use_container_width=True)

        st.markdown("""
        ### Confidence Scores

        Each keypoint has a **confidence score** (0-1) indicating how certain
        the AI is about its position. We typically require >0.3 confidence
        to use a keypoint for calculations.
        """)

    with tab3:
        st.markdown("""
        ### How Joint Angles Are Calculated

        We use **vector mathematics** to calculate the angle at any joint:
        """)

        st.latex(r'''
        \cos(\theta) = \frac{\vec{A} \cdot \vec{B}}{|\vec{A}| \times |\vec{B}|}
        ''')

        st.markdown("""
        Where:
        - **θ** is the angle at the joint
        - **A** is the vector from joint to first connected point
        - **B** is the vector from joint to second connected point

        ### Example: Knee Angle

        For knee extension, we calculate the angle using three points:
        - **Hip** (keypoint 11)
        - **Knee** (keypoint 13) - this is the vertex
        - **Ankle** (keypoint 15)
        """)

        st.code("""
def calculate_angle(hip, knee, ankle):
    # Create vectors from knee to hip and knee to ankle
    vector_a = hip - knee
    vector_b = ankle - knee

    # Calculate angle using dot product formula
    cos_angle = np.dot(vector_a, vector_b) / (
        np.linalg.norm(vector_a) * np.linalg.norm(vector_b)
    )

    # Convert to degrees
    angle = np.degrees(np.arccos(cos_angle))
    return angle
        """, language="python")

        st.markdown("""
        ### Angle Interpretation

        | Knee Angle | Meaning |
        |------------|---------|
        | ~180° | Fully extended (straight leg) |
        | ~90° | Right angle (seated position) |
        | <90° | Deep flexion |
        """)

    with tab4:
        st.markdown("""
        ### Form Assessment Logic

        The system evaluates form using multiple criteria:

        #### 1. Range of Motion (ROM)
        Compares achieved angles to target angles for each exercise.

        #### 2. Movement Quality
        - **Smoothness**: Measures variation in angle changes
        - **Symmetry**: Compares left vs right side
        - **Control**: Detects jerky or momentum-based movements

        #### 3. Compensation Detection
        Identifies when patients use incorrect muscles:
        - Hip hiking during leg exercises
        - Trunk lean during arm movements
        - Shoulder shrugging

        #### 4. Fatigue Tracking
        Monitors form degradation over repetitions to suggest rest.
        """)

        st.markdown("""
        ### Form Score Calculation
        """)

        st.code("""
def calculate_form_score(rep_data):
    score = 0

    # ROM Achievement (40 points)
    rom_ratio = actual_rom / target_rom
    score += rom_ratio * 40

    # Smoothness (30 points)
    smoothness = 1.0 / (1.0 + angle_variance)
    score += smoothness * 30

    # Symmetry (30 points)
    symmetry = 1.0 - abs(left_time - right_time) / total_time
    score += symmetry * 30

    return min(score, 100)
        """, language="python")

        # Interactive demo
        st.markdown("---")
        st.markdown("### Try It: Form Score Calculator")

        col1, col2, col3 = st.columns(3)
        with col1:
            rom_achieved = st.slider("ROM Achieved (%)", 0, 100, 80)
        with col2:
            smoothness = st.slider("Movement Smoothness", 0, 100, 70)
        with col3:
            symmetry = st.slider("Left/Right Symmetry", 0, 100, 90)

        form_score = (rom_achieved * 0.4) + (smoothness * 0.3) + (symmetry * 0.3)
        st.metric("Calculated Form Score", f"{form_score:.1f}%")

    # Toggle technical overlay option
    if st.session_state.get('show_technical', False):
        st.markdown("---")
        st.markdown("### 🔧 Technical Details")
        st.json({
            "model": "models/yolo11m-pose.pt",
            "framework": "Ultralytics",
            "keypoints": 17,
            "inference_speed": "~30ms per frame",
            "input_resolution": "640x640"
        })


# =============================================================================
# MAIN APP
# =============================================================================

def main():
    """Main application entry point."""
    init_session_state()
    render_sidebar()

    # Route to current page
    page = st.session_state.current_page

    if page == 'home':
        page_home()
    elif page == 'live':
        page_live_session()
    elif page == 'video':
        page_video_analysis()
    elif page == 'patients':
        page_patients()
    elif page == 'sessions':
        page_sessions()
    elif page == 'pt_summary':
        page_pt_summary()
    elif page == 'obs_logs':
        page_observation_logs()
    elif page == 'progress':
        page_progress_report()
    elif page == 'learn':
        page_how_it_works()
    else:
        page_home()


if __name__ == "__main__":
    main()
