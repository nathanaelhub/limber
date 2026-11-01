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
from datetime import date, datetime
import os
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
from analyze import load_config as load_exercise_config
from src.live_session import LiveSession, save_screenshot

# Import observation logger helpers
from src.ptlog.store import SessionStore, default_db_path
from src.ptlog import views as ptviews
from src.ptlog.exports import FORMATS, to_observation_dict
from src.ptlog.models import PTLogError
from src.ptlog import review as ptreview
from src.ptlog import tracker as pttracker
from src.ptlog import programs as ptprograms
from src.ptlog import thresholds as ptthresholds
from src.portal import access as ptaccess
from src.portal import accounts as ptaccounts
from src.portal import admin as ptadmin
from src.portal import messages as ptmessages
from src.portal import plans as ptplans
from src.portal import attachments as ptattach
from src.ptlog.models import PERIODS, NEXT_STEPS


def _open_store():
    """The record, limited to the signed-in therapist's caseload (feature 016). With no staff password set
    (a private machine) there is no account and nothing is limited, as before."""
    store = SessionStore(default_db_path()).open()
    account_id = st.session_state.get("account_id")
    if account_id is not None:
        ptaccounts.restrict(store, store.account_get(account_id))
    return store


def _account():
    """The signed-in person, or None on an installation without staff sign-in."""
    account_id = st.session_state.get("account_id")
    if account_id is None:
        return None
    with SessionStore(default_db_path()).open() as store:
        return store.account_get(account_id)


PORTAL_URL = os.environ.get("PTASSIST_PORTAL_URL", "http://127.0.0.1:8600").rstrip("/")


def list_observation_logs(patient_id=None):
    """Sessions newest first from the canonical record (drop-in for the retired file lister)."""
    with _open_store() as store:
        return ptviews.session_refs(store, patient_id)


def load_observation_log(ref):
    """Observation-log dict for a session id or SessionRef (drop-in for the retired file loader)."""
    with _open_store() as store:
        return to_observation_dict(store.load_session(int(str(ref))))

# Import Smart PT Summary generator

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
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LIMBER_MARK_SVG = (ASSETS_DIR / "limber-mark.svg").read_text(encoding="utf-8")

st.set_page_config(
    page_title="Limber · Therapist",
    page_icon=str(ASSETS_DIR / "limber-icon-64.png"),
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    /* Limber brand: teal #0E6B64, coral #F2684A, ink #16302C, warm off-white #FAF8F4 */
    html, body, [class*="css"], .stApp {
        font-family: "Sora", "Outfit", "Poppins", "Avenir Next", "Segoe UI", system-ui, sans-serif;
    }
    h1, h2, h3 { letter-spacing: -0.02em; color: #16302C; }
    p.main-header, .main-header {
        font-size: 2.6rem !important;
        line-height: 1.1;
        font-weight: 800 !important;
        letter-spacing: -0.03em;
        color: #16302C;
        margin-bottom: 0.5rem;
    }
    p.sub-header, .sub-header {
        font-size: 1.15rem !important;
        color: #728280;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #FFFFFF;
        border: 1px solid #EDEAE2;
        padding: 1rem;
        border-radius: 18px;
        text-align: center;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: 800;
        color: #0E6B64;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #728280;
    }
    .form-good { color: #0E6B64; }
    .form-warning { color: #C98A1B; }
    .form-poor { color: #F2684A; }
    .stProgress > div > div > div > div {
        background-color: #0E6B64;
    }
    [data-testid="stSidebar"] { background-color: #FFFFFF; border-right: 1px solid #EDEAE2; }
    .stButton > button { border-radius: 14px; border-color: #EDEAE2; }
    .stButton > button:hover { border-color: #0E6B64; color: #0E6B64; }
    .limber-lockup { display: flex; align-items: center; justify-content: center; gap: 0.6rem; padding: 6px 0 2px; }
    .limber-lockup svg { width: 46px; height: 46px; }
    .limber-lockup span { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.04em; color: #16302C; }
    .limber-tag { text-align: center; color: #728280; font-size: 0.85rem; margin-bottom: 4px; }
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

@st.cache_resource
def load_pose_model():
    """Load YOLO pose model (cached)."""
    return YOLO("models/yolo11m-pose.pt")


@st.cache_data
def _live_exercises():
    """Display name -> configuration key, in configuration order (the engine's own exercise list)."""
    return {cfg.name: key for key, cfg in load_exercise_config().items()}


class LiveVideoProcessor(VideoProcessorBase):
    """Feeds browser frames to a LiveSession: the real engine, recorded in the canonical record.

    The page sets the stream's patient, exercise, target, and camera label through `configure()`;
    the session is created on the first frame after that. Nothing here counts reps or scores form.
    """

    def __init__(self, infer=None):
        self._infer_override = infer
        self.model = None if infer is not None else load_pose_model()
        self.patient_id = None
        self.exercise_key = None
        self.target_reps = None
        self.camera_label = "Default"
        self.db_path = None
        self.live = None
        self.store = None
        self.session_id = None
        self.error = None
        self.last_frame = None
        self.pending_switch = None
        self.pending_reset = False

    def request_switch(self, exercise_key):
        """Applied inside the next frame callback, so the engine is only touched from the stream's thread."""
        self.pending_switch = exercise_key

    def request_reset(self):
        self.pending_reset = True

    def _apply_requests(self):
        if self.pending_reset:
            self.pending_reset = False
            self.live.reset()
        key, self.pending_switch = self.pending_switch, None
        if key and key != self.live.exercise_key:
            try:
                self.live.switch(key)
                self.exercise_key = key
            except ValueError as err:
                self.error = str(err)

    def configure(self, patient_id, exercise_key, target_reps, camera_label, db_path=None):
        """Set what the next session records. The patient and camera are fixed once the session exists."""
        if self.live is None:
            self.patient_id = patient_id
            self.exercise_key = exercise_key
            self.camera_label = camera_label
            self.db_path = db_path
        self.target_reps = int(target_reps)
        if self.live is not None:
            self.live.set_target_reps(self.target_reps)

    def _infer(self, img):
        if self._infer_override is not None:
            return self._infer_override(img)
        results = self.model(img, imgsz=320, verbose=False)
        keypoints = None
        if results and len(results) > 0 and results[0].keypoints is not None and len(results[0].keypoints) > 0:
            keypoints = results[0].keypoints.data[0].cpu().numpy()
        return keypoints, (results[0].plot() if results else None)

    def _ensure_live(self):
        if self.live is not None or self.error is not None or not self.exercise_key:
            return
        try:
            self.store = SessionStore(self.db_path or default_db_path(), check_same_thread=False).open()
            live = LiveSession(self.store, self.patient_id, self.exercise_key, self.target_reps,
                               self.camera_label, self._infer)
            self.session_id = live.start()
            self.live = live
        except Exception as err:  # noqa: BLE001 — the stream keeps running; the page shows the message
            self.error = str(err)

    def process_image(self, img):
        self._ensure_live()
        if self.live is None:
            return img
        self._apply_requests()
        out = self.live.process(img)
        self.last_frame = out
        if self.live.error and not self.error:
            self.error = self.live.error
        return out

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        return av.VideoFrame.from_ndarray(self.process_image(img), format="bgr24")

    def on_ended(self):
        """The stream stopped: end the session normally."""
        live, store = self.live, self.store
        if live is not None:
            try:
                live.end()
            except Exception as err:  # noqa: BLE001
                self.error = str(err)
        if store is not None:
            store.close()
            self.store = None


# =============================================================================
# SIDEBAR NAVIGATION
# =============================================================================

def render_sidebar():
    """Render the sidebar navigation."""
    with st.sidebar:
        st.markdown(f'''<div class="limber-lockup">{LIMBER_MARK_SVG}<span>Limber</span></div>
            <div class="limber-tag">Physical therapy, between visits · therapist</div>''', unsafe_allow_html=True)
        st.markdown("---")

        # Navigation
        st.markdown("### Navigation")
        pages = {
            'home': '🏠 Dashboard',
            'live': '📹 Live Session',
            'video': '🎬 Video Analysis',
            'patients': '👥 Patients',
            'sessions': '📋 Sessions',
            'obs_logs': '🔬 Observation Logs',
            'review': '🩺 Review',
            'tracker': '🗂️ Tracker',
            'inbox': '✉️ Inbox',
            'learn': '📚 How It Works'
        }
        me = _account()
        if me is not None and not me.is_therapist:       # an admin who is not a therapist sees no clinical pages
            pages = {}
        if me is not None and me.is_admin:
            pages['people'] = '🧑‍🤝‍🧑 People'
        if me is not None:
            pages['settings'] = '⚙️ My settings'
        if st.session_state.get("current_page") not in pages:
            st.session_state.current_page = next(iter(pages), 'home')
        with _open_store() as store:
            waiting = ptmessages.total_unread(store)
        if waiting:                                   # who is waiting for a reply, visible from every page
            pages['inbox'] = f"✉️ Inbox ({waiting})"

        for page_id, page_name in pages.items():
            if st.button(page_name, key=f"nav_{page_id}", use_container_width=True):
                st.session_state.current_page = page_id
                st.rerun()

        st.markdown("---")

        # Patient (pseudonymous IDs from the canonical record, only the signed-in therapist's own)
        if me is None or me.is_therapist:
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
        if st.session_state.get("admin_token"):
            if me is not None:
                st.caption(f"Signed in as {me.display_name} ({me.username})")
            if st.button("Sign out", key="therapist_signout", use_container_width=True):
                with _open_store() as store:
                    ptadmin.sign_out(store, st.session_state.pop("admin_token", None), "therapist-app")
                st.session_state.pop("account_id", None)
                st.rerun()
        st.caption("Limber v1.0 · therapist app")
        st.caption("Powered by YOLO11 Pose Estimation")


# =============================================================================
# PAGE: HOME DASHBOARD
# =============================================================================

def page_home():
    """Render the home dashboard page."""
    st.markdown('<p class="main-header">Limber</p>',
                unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Physical therapy, between visits · exercise monitoring powered by computer vision</p>',
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

    # Recent sessions from the canonical record
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

LIVE_LOST_AFTER_SECONDS = 10   # a running session with no stream and no activity for this long was lost


def _live_summary_block():
    """After a stream: the stored summary of the session it recorded, with a way to open it."""
    sid = st.session_state.get("live_session_id")
    if sid is None:
        return
    with _open_store() as store:
        try:
            session = store.load_session(int(sid))
        except PTLogError:
            st.session_state.pop("live_session_id", None)
            return
    if session.status == "running":
        # No stream is playing, yet the session never ended: the tab or connection was lost.
        # Wait out the moment in which a normal stop is still being written.
        with _open_store() as store:
            last = store.last_activity_time(session.id) or session.start_time
            if (datetime.now() - datetime.fromisoformat(last)).total_seconds() > LIVE_LOST_AFTER_SECONDS:
                store.interrupt_session(session.id, "stream_lost")
                session = store.load_session(session.id)
    if session.status == "running":
        st.info(f"Session {session.id} is finishing…")
        return
    if session.status == "interrupted":
        st.warning(ptviews.live_summary_line(session))
    else:
        st.success(ptviews.live_summary_line(session))
    if st.button("📋 Open in Sessions", key="live_open_session"):
        st.session_state.sessions_scope = "All patients"
        st.session_state.sessions_open = session.id
        st.session_state.current_page = "sessions"
        st.rerun()


def page_live_session():
    """Live session: the browser stream runs the real engine and is recorded as it happens."""
    st.markdown("## 📹 Live PT Session")

    # Hide webrtc default icons and fullscreen toolbar
    st.markdown("""
        <style>
        .stElementToolbar,
        [data-testid="stElementToolbar"] {
            display: none !important;
        }
        .stApp video {
            border-radius: 8px;
            border: 2px solid #16302C;
        }
        </style>
    """, unsafe_allow_html=True)

    exercises = _live_exercises()
    configs = load_exercise_config()
    patient_id = st.session_state.get("patient_id") or "unassigned"

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        exercise = st.selectbox("Select Exercise", list(exercises.keys()), key="exercise_select")
    exercise_key = exercises[exercise]
    config = configs[exercise_key]
    with col2:
        target_reps = st.number_input("Target Reps", min_value=1, max_value=100,
                                      value=int(config.target_reps), key=f"target_reps_{exercise_key}")
    with col3:
        camera_option = st.selectbox("Camera", ["Default", "Front Camera", "Back Camera"],
                                     key="camera_select", help="Select which camera to use")

    st.markdown("---")
    st.info(f"**Instructions:** allow camera access, then press START. The session is recorded for "
            f"**{patient_id}** as it happens; press STOP to end it. Sessions are saved automatically.")

    video_config = {
        "width": {"min": 1280, "ideal": 1920},
        "height": {"min": 720, "ideal": 1080},
        "frameRate": {"ideal": 30},
    }
    if camera_option == "Front Camera":
        video_config["facingMode"] = "user"
    elif camera_option == "Back Camera":
        video_config["facingMode"] = "environment"

    ctx = webrtc_streamer(
        key=f"pose-estimation-{camera_option}",  # Key changes with camera to force refresh
        mode=WebRtcMode.SENDRECV,
        video_processor_factory=LiveVideoProcessor,
        media_stream_constraints={"video": video_config, "audio": False},
        async_processing=True,
        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
        video_html_attrs={"style": {"width": "100%", "max-width": "1280px"}, "autoPlay": True, "muted": True},
    )

    processor = ctx.video_processor
    playing = bool(ctx.state.playing)
    if processor is not None:
        processor.configure(patient_id, exercise_key, target_reps, camera_option)
        if processor.session_id is not None:
            st.session_state.live_session_id = processor.session_id
        if processor.error:
            st.error(f"Recording problem: {processor.error}")

    if playing and processor is not None:
        if processor.session_id is not None:
            st.caption(f"Recording session {processor.session_id} for {processor.patient_id or 'unassigned'}")
        else:
            st.caption("Starting… the session begins with the first processed frame.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button(f"🔀 Switch exercise to {exercise}", key="live_switch",
                         disabled=(processor.exercise_key == exercise_key)):
                processor.request_switch(exercise_key)
        with c2:
            if st.button("🔄 Reset reps", key="live_reset"):
                processor.request_reset()
    else:
        _live_summary_block()

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Exercise Info")
        st.write(f"**Keypoints:** {config.keypoints}")
        st.write(f"**Up Angle:** {config.up_angle}°")
        st.write(f"**Down Angle:** {config.down_angle}°")
    with col2:
        st.markdown("### Target")
        st.metric("Target Reps", target_reps)

    st.markdown("---")
    if st.button("📸 Save Screenshot", key="live_screenshot"):
        frame = getattr(processor, "last_frame", None) if playing else None
        if frame is None:
            st.info("No frame to save. Start the stream first.")
        else:
            try:
                shot = save_screenshot(frame, getattr(processor, "patient_id", None) or patient_id)
                st.success(f"Screenshot saved: {shot}")
            except (ValueError, PTLogError) as err:
                st.error(str(err))


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
                    ptaccounts.add_patient(store, _account(), new_id, label=new_label or None, notes=new_notes or None)
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

    _patient_plans_section(pid)
    _patient_appointments_section(pid)
    _patient_program_section(pid)
    _patient_home_access_section(pid, current)
    _patient_logs_section(pid, current)
    _patient_questionnaire_section(pid, current)
    _patient_discharge_section(pid)

_PLAN_STATUS = {"active": "Active", "completed": "Completed", "archived": "Archived (read-only)"}


def _plan_action(fn, *args, done=None, **kwargs):
    try:
        with _open_store() as store:
            fn(store, *args, **kwargs)
        if done:
            st.session_state["plans_notice"] = done
        st.rerun()
    except PTLogError as exc:
        st.error(str(exc))


def _patient_plans_section(pid):
    """Plans of care for one patient (feature 017): open, edit, complete, archive."""
    st.markdown("### Plans of care")
    st.caption("Everything new (program, logs, messages, visits) belongs to a plan. An archived plan is kept "
               "read-only. The diagnosis is seen by the patient only if you turn that on.")
    notice = st.session_state.pop("plans_notice", None)
    if notice:
        st.success(notice)
    with _open_store() as store:
        plan_list = store.plans(pid)
    if plan_list:
        st.dataframe(pd.DataFrame([{
            "Plan": p.title, "Status": _PLAN_STATUS[p.status], "Started": p.start_date, "Ended": p.end_date or "",
            "Diagnosis shown to patient": "yes" if p.diagnosis_visible else "no"} for p in plan_list]),
            use_container_width=True, hide_index=True)

    with st.expander("Open a new plan", expanded=len(plan_list) == 0):
        st.text_input("Title", key=f"plan_new_title_{pid}", placeholder="Right knee, post-op", max_chars=ptplans.TITLE_MAX)
        st.text_area("Diagnosis", key=f"plan_new_diagnosis_{pid}", max_chars=ptplans.DIAGNOSIS_MAX,
                     help="Your own words. Never put names or dates of birth here.")
        st.toggle("Show the diagnosis to the patient", key=f"plan_new_show_dx_{pid}", value=False)
        if st.button("Open plan", key="plan_open"):
            _plan_action(ptplans.open_plan, pid, st.session_state.get(f"plan_new_title_{pid}"),
                         st.session_state.get(f"plan_new_diagnosis_{pid}", ""),
                         st.session_state.get(f"plan_new_show_dx_{pid}", False),
                         done=f"Opened “{(st.session_state.get('plan_new_title_' + pid) or '').strip()}”.")

    if not plan_list:
        return
    by_id = {p.id: p for p in plan_list}
    if st.session_state.get(f"plan_edit_select_{pid}") not in by_id:
        st.session_state[f"plan_edit_select_{pid}"] = plan_list[-1].id
    chosen = st.selectbox("Plan to change", list(by_id), key=f"plan_edit_select_{pid}",
                          format_func=lambda i: f"{by_id[i].title} · {_PLAN_STATUS[by_id[i].status]}")
    plan = by_id[chosen]
    locked = plan.read_only
    title = st.text_input("Title", value=plan.title, key=f"plan_title_{plan.id}", disabled=locked,
                          max_chars=ptplans.TITLE_MAX)
    diagnosis = st.text_area("Diagnosis", value=plan.diagnosis, key=f"plan_dx_{plan.id}", disabled=locked,
                             max_chars=ptplans.DIAGNOSIS_MAX)
    show = st.toggle("Show the diagnosis to the patient", value=plan.diagnosis_visible,
                     key=f"plan_show_dx_{plan.id}", disabled=locked)
    if locked:
        st.info("This plan is archived. Everything in it can be read; nothing can be added or changed.")
        return
    c1, c2, c3 = st.columns(3)
    if c1.button("Save changes", key=f"plan_save_{plan.id}"):
        _plan_action(ptplans.edit_plan, plan.id, title=title, diagnosis=diagnosis, diagnosis_visible=show,
                     done="Plan saved.")
    if plan.status == "active":
        if c2.button("Mark completed", key=f"plan_complete_{plan.id}"):
            _plan_action(ptplans.complete, plan.id, done=f"“{plan.title}” is completed.")
    else:
        if c2.button("Reopen", key=f"plan_reopen_{plan.id}"):
            _plan_action(ptplans.reopen, plan.id, done=f"“{plan.title}” is active again.")
        if c3.button("Archive (read-only)", key=f"plan_archive_{plan.id}",
                     help="Keeps everything readable and stops any new messages, logs, or visits in this plan."):
            _plan_action(ptplans.archive, plan.id, done=f"“{plan.title}” is archived.")


def _patient_appointments_section(pid):
    """Visits for one patient (feature 017): add, change the time, answer a reschedule request, cancel.
    Times are the clinic's (a setting); the patient sees the same wall-clock time on any device."""
    from datetime import timedelta
    st.markdown("### Visits")
    with _open_store() as store:
        zone = str(ptplans.clinic_zone(store))
        rows = [(a, ptplans.appointment_json(store, a)) for a in store.appointments(pid)]
        live_plans = [p for p in store.plans(pid) if not p.read_only]
    st.caption(f"Times are clinic time ({zone}).")
    for a, v in rows:
        label = f"{v['date']} {v['time']} · {v['minutes']} min" + (f" · {v['note']}" if v["note"] else "")
        state = {"cancelled": "Cancelled", "past": "Past", "upcoming": "Upcoming"}[v["state"]]
        with st.container(border=True):
            st.markdown(("~~" + label + "~~" if v["state"] == "cancelled" else label) + f"  \n{state}"
                        + (" · **reschedule requested**" if v["reschedule_requested"] else ""))
            if v["reschedule_requested"]:
                st.warning(f"{pid} asked to reschedule" + (f": “{v['request_note']}”" if v["request_note"] else "."))
            elif v["response_note"]:
                st.caption(f"Your reply: {v['response_note']}")
            if v["state"] != "upcoming":
                continue
            m1, m2, m3 = st.columns([1.2, 1, 1])
            new_day = m1.date_input("New date", value=date.fromisoformat(v["date"]), key=f"appt_move_date_{a.id}")
            new_time = m2.text_input("New time (HH:MM)", value=v["time"], key=f"appt_move_time_{a.id}")
            if m3.button("Change time", key=f"appt_move_{a.id}"):
                _plan_action(ptplans.move, a.id, f"{new_day.isoformat()}T{new_time.strip()}", done="Visit moved.")
            if v["reschedule_requested"]:
                r1, r2 = st.columns([3, 1])
                r1.text_input("Reply without moving it", key=f"appt_reply_{a.id}", max_chars=ptplans.REQUEST_MAX)
                if r2.button("Decline request", key=f"appt_decline_{a.id}"):
                    _plan_action(ptplans.decline_request, a.id, st.session_state.get(f"appt_reply_{a.id}", ""),
                                 done="Request declined; the patient sees your reply.")
            if st.button("Cancel visit", key=f"appt_cancel_{a.id}"):
                _plan_action(ptplans.cancel, a.id, done="Visit cancelled. It stays on both calendars, struck through.")
    if not rows:
        st.caption("No visits yet.")
    if not live_plans:
        st.caption("Open a plan of care to add visits.")
        return
    with st.expander("Add a visit", expanded=not rows):
        c1, c2, c3 = st.columns(3)
        day = c1.date_input("Date", value=date.today() + timedelta(days=7), key=f"appt_new_date_{pid}")
        at = c2.text_input("Time (HH:MM)", value="09:00", key=f"appt_new_time_{pid}")
        minutes = c3.number_input("Length (minutes)", min_value=5, max_value=480, value=45, step=5, key=f"appt_new_minutes_{pid}")
        note = st.text_input("Short note", key=f"appt_new_note_{pid}", max_chars=ptplans.NOTE_MAX, placeholder="Re-check range of motion")
        by_id = {p.id: p for p in live_plans}
        plan_id = st.selectbox("Plan of care", list(by_id), format_func=lambda i: by_id[i].title, key=f"appt_new_plan_{pid}")
        if st.button("Add visit", key="appt_add"):
            _plan_action(ptplans.schedule, pid, f"{day.isoformat()}T{at.strip()}", int(minutes), note, plan_id=plan_id,
                         done="Visit added.")



def _patient_questionnaire_section(pid, patient):
    """Which questionnaires this patient answers, and how often (feature 013)."""
    from src.ptlog import instruments as registry
    from src.ptlog import questionnaires as qrules
    st.markdown("### Questionnaires")
    if patient.is_builtin:
        st.caption("The built-in patient has no phone access.")
        return
    installed = registry.load()
    for problem in installed.problems:
        st.warning(f"The questionnaire file {problem.file} could not be used: {problem.message}")
    with _open_store() as store:
        live = store.assignments(pid)
        last = {a.instrument_key: store.last_questionnaire_at(pid, a.instrument_key) for a in live}
    if live:
        rows = []
        for a in live:
            instrument = installed.by_key.get(a.instrument_key)
            answered = last.get(a.instrument_key)
            due = qrules.next_due(a.interval, date.fromisoformat(a.start_date),
                                  date.fromisoformat(answered[:10]) if answered else None)
            rows.append({"Questionnaire": instrument.name if instrument else f"{a.instrument_key} (file not installed)",
                         "How often": qrules.interval_words(a.interval),
                         "Last answered": (answered or "")[:10] or "not yet",
                         "Next due": due.isoformat() if due else "nothing more due"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        for a in live:
            instrument = installed.by_key.get(a.instrument_key)
            if instrument and instrument.notice:
                st.caption(f"{instrument.name}: {instrument.notice}")
            if st.button(f"End '{instrument.name if instrument else a.instrument_key}'",
                         key=f"end_assignment_{a.instrument_key}_{pid}"):
                with _open_store() as store:
                    store.end_assignment(a.id)
                st.rerun()
    elif not installed.by_key:
        st.caption("No questionnaires are installed. Add one as a YAML file in the `instruments/` folder; "
                   "no code change is needed.")
        return
    else:
        st.caption("None assigned. The patient is offered a questionnaire on Today once you assign one.")
    choices = {i.name: i for i in installed.listed() if i.key not in {a.instrument_key for a in live}}
    if not choices:
        return
    c1, c2, c3 = st.columns([2.2, 1.4, 1])
    with c1:
        chosen = st.selectbox("Questionnaire to assign", list(choices), key=f"assign_instrument_{pid}")
    with c2:
        words = st.selectbox("How often", [w for _, w in qrules.INTERVALS], index=2, key=f"assign_interval_{pid}")
    with c3:
        st.caption("")
        if st.button("Assign", key=f"assign_instrument_save_{pid}"):
            interval = next(k for k, w in qrules.INTERVALS if w == words)
            try:
                with _open_store() as store:
                    store.assign_instrument(pid, choices[chosen].key, interval)
                st.success(f"Assigned {chosen}, {words}.")
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))
    instrument = choices[chosen]
    st.caption(f"{instrument.name}: {instrument.meaning} Score in {instrument.unit}; "
               f"{'a higher score is better' if instrument.direction == 'higher_is_better' else 'a higher score is worse'}. "
               f"{len(instrument.items)} questions. {instrument.notice}")


def _patient_logs_section(pid, patient):
    """What the patient may log from their phone (feature 012): exercise done without the camera,
    and the medication list they choose from."""
    from src.portal import diary as diary_rules
    st.markdown("### What the patient can log")
    if patient.is_builtin:
        st.caption("The built-in patient has no phone access.")
        return
    with _open_store() as store:
        enabled = store.diary_enabled(pid)
        medications = store.medication_list(pid)
    # The keys carry the patient id: a widget key alone keeps its value across a rerun, so a shared key
    # would show (and then save) the patient chosen before this one.
    wanted = st.toggle("Let this patient log exercise done without the camera", value=enabled,
                       key=f"patient_diary_enabled_{pid}")
    if wanted != enabled:
        with _open_store() as store:
            store.set_diary_enabled(pid, wanted)
        st.rerun()
    st.caption(f"Logged sessions count towards practice, adherence, and the streak, and are marked "
               f"{diary_rules.LABEL.lower()}. They carry no measured range of motion or form, so they never "
               f"appear in trends, flags, goal progress, or a comparison.")
    st.markdown("**Medication list**")
    st.caption("One medicine per line, as the patient should see it (for example \"ibuprofen 400 mg\"). "
               "The patient ticks from this list and can never type a medicine name. Leave it empty to "
               "offer no medication log. Up to 20 items of 60 characters.")
    text = st.text_area("Medicines", value="\n".join(medications), key=f"patient_medications_{pid}",
                        label_visibility="collapsed", placeholder="ibuprofen 400 mg")
    if st.button("Save medication list", key=f"patient_medications_save_{pid}"):
        warned = [n.strip() for n in text.splitlines() if n.strip() and ptmessages.check_text(n.strip())]
        with _open_store() as store:
            saved = store.set_medication_list(pid, text.splitlines())
        if warned:
            st.warning("These look like they contain identifying details: " + ", ".join(warned))
        st.success(f"Saved {len(saved)} medicine(s)." if saved else "The medication log is now off for this patient.")
        st.rerun()


def _patient_home_access_section(pid, patient):
    """Home access through the Limber patient view (feature 007): issue or revoke the access code."""
    st.markdown("### Home access")
    if patient.is_builtin:
        st.caption("Home access cannot be given to the built-in patient.")
        return
    with _open_store() as store:
        status = store.portal_status(pid)
    state = f"active until {status.expires_at[:10]}" if status.state == "active" else status.state
    used = f" · last used {status.last_used_at[:16].replace('T', ' ')}" if status.last_used_at else ""
    st.caption(f"Access code: {state}{used}. For demo and study use only.")
    fresh = st.session_state.pop("home_access_code", None)
    if fresh and fresh[0] == pid:
        st.warning("This code is shown only once. Give it to the patient now. For demo and study use only.")
        st.code(fresh[1], language=None)
    c1, c2 = st.columns(2)
    with c1:
        label = "Issue a new code" if status.state != "none" else "Issue access code"
        if st.button(label, key="home_access_issue", help="A new code replaces the old one and signs the patient out."):
            try:
                with _open_store() as store:
                    key = ptaccess.load_key(ptaccess.default_key_path(default_db_path()))
                    code, _ = ptaccess.issue_code(store, key, pid)
                st.session_state["home_access_code"] = (pid, code)
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))
    with c2:
        if st.button("Revoke", key="home_access_revoke", disabled=status.state != "active"):
            with _open_store() as store:
                ptaccess.revoke_code(store, pid)
            st.rerun()
    with _open_store() as store:
        history = store.portal_audit_list(pid, limit=20)
    if history:
        with st.expander("Access history"):
            st.dataframe(pd.DataFrame([{"When": h.at[:16].replace("T", " "), "Event": h.event, "Detail": h.detail or ""}
                                       for h in history]), use_container_width=True, hide_index=True)


def _patient_discharge_section(pid):
    """Discharge or reactivate the selected patient (feature 003)."""
    from datetime import date
    st.markdown("### Caseload status")
    with _open_store() as store:
        discharge = store.get_discharge(pid)
    if discharge is not None:
        st.info(f"{pid} was discharged on {discharge.discharged_on}" + (f": {discharge.reason}" if discharge.reason else ""))
        if st.button("Reactivate", key="patients_reactivate"):
            with _open_store() as store:
                store.reactivate(pid)
            st.success(f"Reactivated {pid}")
            st.rerun()
        return
    c1, c2 = st.columns([1, 2])
    with c1:
        on = st.date_input("Discharge date", value=date.today(), key="patients_discharge_date")
    with c2:
        reason = st.text_input("Reason (optional; no names, dates of birth, or record numbers)", key="patients_discharge_reason")
    if st.button("Discharge patient", key="patients_discharge_button"):
        try:
            with _open_store() as store:
                d = store.discharge(pid, on, reason or None)
            st.success(f"Discharged {d.patient_id} on {d.discharged_on}")
            st.rerun()
        except PTLogError as exc:
            st.error(str(exc))


def _patient_program_section(pid):
    """Program assignment form and history for one patient (feature 003)."""
    from datetime import date
    from src.ptlog import adherence as ptadherence
    st.markdown("### Program")
    catalog = ptprograms.list_programs()
    names = [p.name for p in catalog] + ["Custom"]
    choice = st.selectbox("Program", names, key="patients_program_choice")
    custom_keys = []
    if choice == "Custom":
        all_keys = list(ptprograms.load_catalog().exercises)
        custom_keys = st.multiselect("Exercises", all_keys, format_func=ptprograms.exercise_name, key="patients_program_keys")
    c1, c2, c3 = st.columns(3)
    with c1:
        per_week = st.number_input("Sessions per week (count)", min_value=1, max_value=14, value=3, key="patients_program_per_week")
    with c2:
        start = st.date_input("Start date", value=date.today(), key="patients_program_start")
    with c3:
        set_end = st.checkbox("Set an end date", key="patients_program_set_end")
        end = st.date_input("End date", value=date.today(), key="patients_program_end") if set_end else None
    if st.button("Assign program", key="patients_program_assign"):
        try:
            with _open_store() as store:
                if choice == "Custom":
                    a = store.assign_program(pid, "custom", "Custom", custom_keys, int(per_week), start, end)
                else:
                    prog = next(p for p in catalog if p.name == choice)
                    a = store.assign_program(pid, prog.id, prog.name, prog.exercise_keys, int(per_week), start, end)
            st.success(f"Assigned {a.program_name} to {pid}: {a.sessions_per_week} sessions/week from {a.start_date}")
            st.rerun()
        except PTLogError as exc:
            st.error(str(exc))
    with _open_store() as store:
        history = store.assignment_history(pid)
    if history:
        st.dataframe(pd.DataFrame([{
            "Program": h.program_name, "From": h.start_date, "To": h.end_date or "open",
            "Status": ptadherence.assignment_status(h, date.today()),
            "Sessions per week (count)": h.sessions_per_week,
            "Exercises": ", ".join(ptprograms.exercise_name(k) for k in h.exercise_keys),
        } for h in history]), use_container_width=True, hide_index=True)
    else:
        st.caption("No program assigned yet.")


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
        "id": "ID", "date": "Date", "patient_id": "Patient", "source": "Source", "origin": "Recorded", "exercises": "Exercises",
        "total_reps": ptviews.metric_label("total_reps"), "avg_form_score": ptviews.metric_label("avg_form_score"),
        "status": "Status"})
    st.dataframe(table, use_container_width=True, hide_index=True)

    ids = [r["id"] for r in rows]
    by_id = {r["id"]: r for r in rows}
    if st.session_state.get("sessions_open") not in ids:
        st.session_state.pop("sessions_open", None)      # e.g. a link to a session outside this list
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
# PAGE: REVIEW (trends, flags, comparison, session reviews, goals, exports)
# =============================================================================

REVIEW_SECTIONS = ["Trends", "Flags", "Compare", "Session review", "From the patient", "Goals & settings", "Export"]


def page_review():
    """Review a patient's course of care; each section renders only when chosen."""
    st.markdown("## 🩺 Review")
    pid = st.session_state.get("patient_id") or "unassigned"
    section = st.radio("Section", REVIEW_SECTIONS, horizontal=True, key="review_tab", label_visibility="collapsed")
    if section == "Trends":
        _review_trends(pid)
    elif section == "Session review":
        _review_session(pid)
    elif section == "Flags":
        _review_flags(pid)
    elif section == "Compare":
        _review_compare(pid)
    elif section == "Goals & settings":
        _review_goals_settings(pid)
    elif section == "From the patient":
        _review_from_the_patient(pid)
    elif section == "Export":
        _review_export(pid)


def _period_selector(key):
    return st.selectbox("Period", list(PERIODS), index=len(PERIODS) - 1, key=key,
                        format_func=lambda p: ptviews.PERIOD_LABELS[p])


def _review_trends(pid):
    with _open_store() as store:
        names = ptreview.exercise_names(store, pid)
    if not names:
        st.info(f"No sessions recorded for patient {pid} yet.")
        return
    col1, col2 = st.columns([2, 1])
    with col1:
        exercise = st.selectbox("Exercise", names, key="review_trend_exercise")
    with col2:
        period = _period_selector("review_trend_period")
    with _open_store() as store:
        t = ptreview.trend(store, pid, exercise, period)
        logged = ptreview.self_reported_count(store, pid, exercise, period) if not t.points else 0
    if not t.points:
        st.info(f"No measured sessions of {exercise} in this period."
                + (f" The patient logged {logged} session(s) of it without the camera, which carry no "
                   "range of motion or form; they are under \"From the patient\"." if logged else ""))
        return
    rows = ptviews.trend_table_rows(t)
    table = pd.DataFrame(rows).rename(columns={
        "date": "Date", "session_id": "Session", "reps": ptviews.metric_label("reps_completed"),
        "avg_form": ptviews.metric_label("avg_form"), "avg_rom": ptviews.metric_label("avg_rom"),
        "avg_duration": ptviews.metric_label("avg_duration"), "tempo_sd": ptviews.metric_label("tempo_sd"),
        "partial_share": ptviews.metric_label("partial_share"), "status": "Status", "origin": "Recorded"})
    st.dataframe(table, use_container_width=True, hide_index=True)
    chart = pd.DataFrame({
        "Date": [ptviews.date_minute(p.start_time) for p in t.points],
        ptviews.metric_label("avg_rom"): [p.avg_rom for p in t.points],
        ptviews.metric_label("avg_form"): [p.avg_form for p in t.points],
    }).set_index("Date")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"### {ptviews.metric_label('avg_rom')}")
        st.line_chart(chart[[ptviews.metric_label("avg_rom")]])
        st.caption(ptviews.metric_definition("avg_rom"))
    with c2:
        st.markdown(f"### {ptviews.metric_label('avg_form')}")
        st.line_chart(chart[[ptviews.metric_label("avg_form")]])
        st.caption(ptviews.metric_definition("avg_form"))
    st.markdown("### First → latest")
    for line in ptviews.trend_summary_lines(t):
        st.write(line)


def _review_session(pid):
    with _open_store() as store:
        rows = ptviews.session_table_rows(store, pid)
    if not rows:
        st.info(f"No sessions recorded for patient {pid} yet.")
        return
    by_id = {r["id"]: r for r in rows}
    sid = st.selectbox("Session", [r["id"] for r in rows], key="review_session_id",
                       format_func=lambda i: f"#{i} · {by_id[i]['date']} · {by_id[i]['exercises']} · "
                                             f"{by_id[i]['total_reps']} reps · {by_id[i]['status']}")
    with _open_store() as store:
        view = ptreview.session_review_view(store, sid)
    st.markdown("  \n".join(ptviews.session_header_lines(view["session"])))
    st.markdown("### Measures")
    measure_rows = [{"Exercise": name, ptviews.metric_label("reps_completed"): ptviews.fmt_measure("reps_completed", m.reps_completed, m.target_reps),
                     ptviews.metric_label("avg_form"): ptviews.fmt_measure("avg_form", m.avg_form),
                     ptviews.metric_label("avg_rom"): ptviews.fmt_measure("avg_rom", m.avg_rom),
                     ptviews.metric_label("avg_duration"): ptviews.fmt_measure("avg_duration", m.avg_duration),
                     ptviews.metric_label("tempo_sd"): ptviews.fmt_measure("tempo_sd", m.tempo_sd),
                     ptviews.metric_label("partial_share"): ptviews.fmt_measure("partial_share", m.partial_share)}
                    for name, m in view["measures"].items()]
    st.dataframe(pd.DataFrame(measure_rows), use_container_width=True, hide_index=True)
    st.markdown("### Per-session summary")
    flags = view["summary"].get("key_flags") or []
    if not flags:
        st.success("No flags within this session.")
    for f in flags:
        text = f"[{f.get('severity', 'info')}] {f.get('message', '')}"
        (st.warning if str(f.get("severity", "")).lower() in ("warning", "high", "critical", "stop") else st.info)(text)
    if view["summary"].get("summary_text"):
        st.text(view["summary"]["summary_text"])
    review = view["review"]
    st.markdown("**" + ptviews.review_status_line(review).replace("REVIEW:", "REVIEW:**"))
    with st.form("review_form"):
        next_step = st.selectbox("Next step", list(NEXT_STEPS),
                                 index=list(NEXT_STEPS).index(review.next_step) if review else 0, key="review_next_step")
        notes = st.text_area("Clinical notes (no names, dates of birth, or record numbers)",
                             value=(review.notes or "") if review else "", key="review_notes")
        if st.form_submit_button("Mark reviewed" if review is None else "Update review"):
            try:
                with _open_store() as store:
                    store.set_review(sid, next_step, notes)
                st.success(f"Reviewed session {sid} (next step: {next_step})")
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))


def _review_flags(pid):
    period = _period_selector("review_flags_period")
    with _open_store() as store:
        result = ptreview.flags_for(store, pid, period)
    if not result.flags:
        st.success("Nothing needs attention.")
    for f in result.flags:
        st.warning(f"**{f.rule}** — {f.message}")
    if result.not_evaluated:
        st.markdown("Not evaluated yet:")
        for n in result.not_evaluated:
            where = f" for {n.exercise}" if n.exercise else ""
            st.info(f"{n.rule}{where}: needs {n.needed} sessions, has {n.have}")


def _review_compare(pid):
    with _open_store() as store:
        rows = ptviews.session_table_rows(store, pid)
    if len(rows) < 2:
        st.info("Two recorded sessions are needed for a comparison.")
        return
    by_id = {r["id"]: r for r in rows}
    ids = [r["id"] for r in rows]
    label = lambda i: f"#{i} · {by_id[i]['date']} · {by_id[i]['exercises']} · {by_id[i]['total_reps']} reps"
    c1, c2 = st.columns(2)
    with c1:
        a = st.selectbox("Session A (earlier)", ids, index=min(1, len(ids) - 1), key="review_compare_a", format_func=label)
    with c2:
        b = st.selectbox("Session B (later)", ids, index=0, key="review_compare_b", format_func=label)
    shared = [x for x in by_id[a]["exercises"].split(", ") if x in by_id[b]["exercises"].split(", ")]
    exercise = None
    if len(shared) > 1:
        exercise = st.selectbox("Exercise", shared, key="review_compare_exercise")
    try:
        with _open_store() as store:
            comp = ptreview.compare(store, a, b, exercise)
    except PTLogError as exc:
        st.error(str(exc))
        return
    st.markdown(f"**{comp.exercise}** — session {a} → session {b}")
    table = pd.DataFrame(ptviews.comparison_rows(comp)).rename(columns={
        "measure": "Measure", "a": f"Session {a}", "b": f"Session {b}", "change": "Change",
        "pct_change": "% change", "better": "Better when"})
    st.dataframe(table, use_container_width=True, hide_index=True)


def _threshold_table(rows):
    st.dataframe(pd.DataFrame([{
        "Threshold": r["name"], "Value": f"{r['value']} {r['unit']}", "Origin": r["origin"],
        "Default": f"{r['default']} {r['unit']}", "Meaning": r["meaning"]} for r in rows]),
        use_container_width=True, hide_index=True)


def _history_table(changes, label):
    with st.expander(label, expanded=bool(changes)):
        if not changes:
            st.caption("No threshold changes recorded.")
            return
        st.dataframe(pd.DataFrame(ptviews.history_rows(changes)).rename(columns={
            "when": "When", "applies_to": "Applies to", "threshold": "Threshold", "change": "Change"}),
            use_container_width=True, hide_index=True)


def _thresholds_editor(pid):
    """Attention thresholds for the whole patient or for one of the patient's exercises."""
    st.markdown("### Attention thresholds")
    flash = st.session_state.pop("thresholds_flash", None)
    if flash:
        st.success(flash)
    with _open_store() as store:
        names = sorted(set(ptreview.exercise_names(store, pid)) | set(store.get_exercise_thresholds(pid)))
    scope = st.selectbox("Applies to", ["Whole patient"] + names, key="thresholds_scope",
                         help="Practice gap and adherence describe the whole patient; the other six can differ per exercise.")
    exercise = None if scope == "Whole patient" else scope
    with _open_store() as store:
        effective = store.effective_thresholds(pid, exercise)
        if exercise:
            inherited = store.effective_thresholds(pid)
            overrides = store.get_exercise_thresholds(pid).get(exercise, {})
        else:
            inherited = ptthresholds.resolve(None, store.get_installation_thresholds())
            overrides = store.get_patient_thresholds(pid)
    rows = ptviews.threshold_rows(effective, inherited, ptthresholds.EXERCISE_KEYS if exercise else None)
    _threshold_table(rows)
    st.caption("Origin: exercise = set for this exercise; patient = set for this patient; installation = this "
               "installation's value; default = built-in. Flags, the roster, and exports use these values.")
    prefix = f"threshold_{exercise}_" if exercise else "threshold_"
    cols = st.columns(4)
    entered = {}
    for i, r in enumerate(rows):
        with cols[i % 4]:
            entered[r["key"]] = st.number_input(
                f"{r['name']} ({r['unit']})", min_value=r["minimum"], max_value=r["maximum"],
                value=int(r["value"]), step=1, key=f"{prefix}{r['key']}", help=r["meaning"])
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save thresholds", key="thresholds_save"):
            # store a value only when it differs from what would be inherited, or already is an override
            changed = {k: int(v) for k, v in entered.items() if int(v) != inherited.value(k) or k in overrides}
            try:
                with _open_store() as store:
                    if exercise:
                        store.set_exercise_thresholds(pid, exercise, changed)
                    else:
                        store.set_patient_thresholds(pid, changed)
                st.session_state["thresholds_flash"] = (
                    "Thresholds saved." if changed else "No changes: every value equals the default.")
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))
    with c2:
        label = f"Reset {exercise} to the patient's values" if exercise else "Reset all to defaults"
        if st.button(label, key="thresholds_reset_all"):
            with _open_store() as store:
                if exercise:
                    store.reset_exercise_thresholds(pid, exercise)
                else:
                    store.reset_patient_thresholds(pid)
            for key in [k for k in st.session_state.keys() if str(k).startswith("threshold_")]:
                st.session_state.pop(key, None)
            st.rerun()
    with _open_store() as store:
        changes = store.threshold_history(pid, limit=50)
    _history_table(changes, "Change history")


def _review_goals_settings(pid):
    _thresholds_editor(pid)
    st.markdown("### Goals")
    with _open_store() as store:
        names = ptreview.exercise_names(store, pid)
        goals = store.list_goals(pid)
    if goals:
        st.dataframe(pd.DataFrame([{"Exercise": g.exercise_name,
                                    "Target ROM (degrees)": g.target_rom if g.target_rom else "",
                                    "Target reps (count)": g.target_reps if g.target_reps else "",
                                    "Set": ptviews.date_minute(g.set_at)} for g in goals]),
                     use_container_width=True, hide_index=True)
    else:
        st.caption("No goals set.")
    if not names:
        st.info("Record a session before setting goals.")
        return
    exercise = st.selectbox("Exercise", names, key="review_goal_exercise")
    current = next((g for g in goals if g.exercise_name == exercise), None)
    c1, c2 = st.columns(2)
    with c1:
        rom = st.number_input("Target ROM (degrees, 1-180; 0 = none)", min_value=0, max_value=180,
                              value=int(current.target_rom) if current and current.target_rom else 0, key="review_goal_rom")
    with c2:
        reps = st.number_input("Target reps (count; 0 = none)", min_value=0, max_value=200,
                               value=int(current.target_reps) if current and current.target_reps else 0, key="review_goal_reps")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Set goal", key="review_goal_set"):
            try:
                with _open_store() as store:
                    g = store.set_goal(pid, exercise, target_rom=rom or None, target_reps=reps or None)
                st.success(f"Goal for {g.exercise_name} saved")
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))
    with b2:
        if st.button("Clear goal", key="review_goal_clear"):
            with _open_store() as store:
                cleared = store.clear_goal(pid, exercise)
            st.success(f"Cleared goal for {exercise}") if cleared else st.info(f"No goal set for {exercise}")
            if cleared:
                st.rerun()


def _review_clips(pid):
    """Clips the patient sent from their phone (feature 011): play, mark reviewed, delete."""
    from src.portal import uploads
    st.markdown("### Videos from the patient")
    with _open_store() as store:
        rows = uploads.list_media(store, pid)
        media_dir = store.media_dir
    live = [m for m in rows if m.deleted_at is None]
    if not rows:
        st.caption("No videos yet. Patients send them from Today in Limber.")
        return
    for m in live:
        state = "reviewed " + m.reviewed_at[:10] if m.reviewed_at else "waiting for review"
        st.markdown(f"**{m.created_at[:16].replace('T', ' ')}** · {round(m.duration)} s · {state}"
                    + (" · caption sent after a privacy warning" if m.warned else ""))
        if m.caption:
            st.text(m.caption)
        path = uploads.media_path(media_dir, m)
        if path.is_file():
            st.video(path.read_bytes(), format={"mp4": "video/mp4", "webm": "video/webm"}.get(m.ext, "video/mp4"))
            st.caption("If the video does not play in this browser (WebM clips in Safari), open it in Chrome.")
        else:
            st.warning("The file for this clip is missing.")
        c1, c2 = st.columns(2)
        if m.reviewed_at is None and c1.button("Mark reviewed", key=f"media_review_{m.id}"):
            with _open_store() as store:
                uploads.mark_reviewed(store, m.id)
            st.rerun()
        if c2.button("Delete", key=f"media_delete_{m.id}", help="Removes the file; a marker stays."):
            with _open_store() as store:
                uploads.delete_media(store, store.media_dir, None, m.id, by="therapist")
            st.rerun()
    removed = [m for m in rows if m.deleted_at is not None]
    if removed:
        st.caption(f"{len(removed)} removed clip(s): " + ", ".join(f"{m.created_at[:10]} ({m.deleted_by})" for m in removed))


def _review_diary(pid):
    """Exercise the patient logged without the camera (feature 012 FR-009)."""
    from src.portal import diary as diary_rules
    from src.ptlog.origin import DIARY, capture_origin
    st.markdown(f"### Logged without the camera · {diary_rules.LABEL}")
    with _open_store() as store:
        sessions = [s for s in store.sessions_in_period(pid, None) if capture_origin(s) == DIARY]
        enabled = store.diary_enabled(pid)
    if not enabled:
        st.caption("Logging is turned off for this patient. What they logged before stays below.")
    if not sessions:
        st.info("Nothing logged yet. Patients log from Today in Limber when they exercise without their phone set up.")
        return
    st.caption(f"{len(sessions)} logged session(s). These count as practice and towards adherence and the streak; "
               f"they carry no measured range of motion or form, so they are in no trend, flag, or comparison.")
    rows = []
    for s in sorted(sessions, key=lambda x: x.start_time, reverse=True)[:100]:
        first = s.sets[0] if s.sets else None
        note = diary_rules.note_of(s)
        rows.append({
            "When": s.start_time[:16].replace("T", " "),
            "Exercise": first.exercise_name if first else "",
            "Reported": f"{first.reported_sets or 1} × {first.reported_reps or 0} reps" if first else "",
            "Total reps": s.total_reps,
            "Effort": f"{first.effort} {dict(diary_rules.EFFORT).get(first.effort, '')}".strip() if first and first.effort else "",
            "Note": note["note"] + (" · sent after a privacy warning" if note["warned"] else ""),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("Reported: sets × reps the patient said they did. Effort: how hard it felt, 1 very easy to 5 very hard.")


def _review_logs(pid):
    """Medication taken and sleep, beside pain (feature 012 US2)."""
    from src.ptlog import entries as entry_rules
    with _open_store() as store:
        meds = store.entries(pid, "medication", newest_first=True, limit=200)
        sleep = store.entries(pid, "sleep", newest_first=True, limit=200)
        offered = store.medication_list(pid)
    st.markdown("### Medication taken")
    if not offered:
        st.caption("No medication list is set for this patient, so they are not offered the medication log. "
                   "Set one on the Patients page.")
    if not meds:
        st.info("Nothing logged yet.")
    else:
        defs = entry_rules.definitions("medication")
        st.dataframe(pd.DataFrame([{
            "When": e.recorded_at[:16].replace("T", " ") + (" (time adjusted)" if e.time_adjusted else ""),
            "Medicine": e.payload.get("item", ""),
            "Note": ("(note removed)" if e.note_removed else (e.payload.get("note") or ""))
                    + (" · sent after a privacy warning" if e.warned else ""),
        } for e in meds]), use_container_width=True, hide_index=True)
        st.caption(f"Medicine ({defs['item']['unit']}): {defs['item']['meaning']}")

    st.markdown("### Sleep")
    if not sleep:
        st.info("Nothing logged yet.")
        return
    nights = entry_rules.nightly(sleep)
    defs = entry_rules.definitions("sleep")
    st.dataframe(pd.DataFrame([{
        "Night": n["night"], "Hours": n["hours"], "Quality": n["quality"],
        "Note": n["note"], "Corrected": "yes" if n["corrected"] else "",
    } for n in nights]), use_container_width=True, hide_index=True)
    st.caption(f"Hours ({defs['hours']['unit']}): {defs['hours']['meaning']} "
               f"Quality ({defs['quality']['unit']}): {defs['quality']['meaning']} "
               "One row per night: if the patient logged a night twice, the later entry is shown and marked corrected.")
    if len(nights) > 1:
        chart = pd.DataFrame({"night": [n["night"] for n in reversed(nights)],
                              "hours": [n["hours"] for n in reversed(nights)]}).set_index("night")
        st.line_chart(chart, y="hours", height=180)


def _review_questionnaires(pid):
    """Scores over time from the questionnaires this patient answered (feature 013).

    What is shown is what was stored when the patient answered: the snapshot that produced each total.
    Nothing is rescored here, so an edited definition can never move a number the therapist has seen."""
    from src.ptlog import instruments as registry
    from src.ptlog import questionnaires as qrules
    st.markdown("### Questionnaires")
    with _open_store() as store:
        rows = store.entries(pid, "questionnaire", newest_first=True, limit=200)
    if not rows:
        st.info("None answered yet. Assign one on the Patients page and it appears on the patient's Today.")
        return
    installed = registry.load().by_key
    by_instrument = {}
    for e in rows:
        by_instrument.setdefault(e.payload.get("instrument", "?"), []).append(e)
    for key, answers in by_instrument.items():
        snap = answers[0].payload.get("snapshot") or {}
        name = snap.get("name") or answers[0].payload.get("name") or key
        unit = snap.get("unit", "")
        direction = "a higher score is better" if snap.get("direction") == "higher_is_better" else "a higher score is worse"
        st.markdown(f"**{name}** — {len(answers)} answered")
        st.caption(f"{snap.get('meaning', '')} Score in {unit}; {direction}.")
        if snap.get("notice"):
            st.caption(f"⚠️ {snap['notice']}")
        if qrules.differs_from_installed(snap, installed.get(key)):
            now_installed = installed.get(key)
            said = (f"is now version {now_installed.version}" if now_installed
                    else "is no longer installed")
            st.caption(f"Answered under version {snap.get('version')}; the definition {said}. The scores "
                       "below are the ones worked out at the time, from the answers given. Nothing has "
                       "been rescored, so a change to the file can never move a score you have seen.")
        subscale_names = {s["key"]: s["name"] for s in snap.get("subscales", [])}
        table = []
        for e in answers:
            payload = e.payload
            row = {"When": e.recorded_at[:16].replace("T", " ") + (" (time adjusted)" if e.time_adjusted else ""),
                   "Total": payload.get("total"), "Missing": payload.get("missing", 0)}
            for skey, sname in subscale_names.items():
                row[sname] = (payload.get("subscales") or {}).get(skey)
            table.append(row)
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
        totals = [e.payload.get("total") for e in reversed(answers) if e.payload.get("total") is not None]
        if len(totals) >= 2:
            change = round(totals[-1] - totals[0], 1)
            better = (change > 0) == (snap.get("direction") == "higher_is_better")
            st.caption(f"First to latest: {totals[0]} → {totals[-1]} ({change:+g} {unit}), "
                       f"{'the direction you want' if change and better else 'not the direction you want' if change else 'no change'}.")
            chart = pd.DataFrame({"when": [e.recorded_at[:10] for e in reversed(answers)], "total": totals}).set_index("when")
            st.line_chart(chart, y="total", height=180)
        which = st.selectbox(f"Answers to look at ({name})", [e.recorded_at[:16].replace("T", " ") for e in answers],
                             key=f"questionnaire_pick_{key}_{pid}")
        chosen = next(e for e in answers if e.recorded_at[:16].replace("T", " ") == which)
        st.dataframe(pd.DataFrame(qrules.answer_rows(chosen.payload.get("snapshot") or {})),
                     use_container_width=True, hide_index=True)
        st.caption("Value: what the answer scored, after any reversal. A reversed question is one where a "
                   "high answer means a low score, so that the total reads the same way round throughout.")


def _review_from_the_patient(pid):
    """What the patient reported from their phone (features 010, 011, 012, 013)."""
    from src.ptlog import entries as entry_rules
    _review_clips(pid)
    st.markdown("---")
    _review_questionnaires(pid)
    st.markdown("---")
    _review_diary(pid)
    st.markdown("---")
    _review_logs(pid)
    st.markdown("---")
    st.markdown("### Pain and symptom check-ins")
    with _open_store() as store:
        rows = store.entries(pid, "checkin", newest_first=True, limit=200)
        pain_flags = [f for f in ptreview.flags_for(store, pid, "all").flags if f.rule in ("pain_rising", "pain_high")]
    for f in pain_flags:
        st.warning(f"[{f.rule}] {f.message}")
    if not rows:
        st.info("No check-ins yet. Patients make them from Today or around a guided session in Limber.")
        return
    series = entry_rules.pain_series(rows)
    chart = pd.DataFrame({"when": [t[:16].replace("T", " ") for t, _, _ in series], "pain": [s for _, s, _ in series]}).set_index("when")
    st.line_chart(chart, y="pain", height=180)
    defs = entry_rules.definitions("checkin")
    st.caption(f"Pain ({defs['pain']['unit']}): {defs['pain']['meaning']}")
    table = pd.DataFrame([{
        "When": e.recorded_at[:16].replace("T", " ") + (" (time adjusted)" if e.time_adjusted else ""),
        "Around": {"before": f"before session {e.session_id}", "after": f"after session {e.session_id}"}.get(e.phase, "on its own"),
        "Pain": int(e.score) if e.score is not None else None, "Where": e.payload.get("area", ""),
        "Stiffness": e.payload.get("stiffness", ""), "Swelling": e.payload.get("swelling", ""),
        "Note": ("(note removed)" if e.note_removed else (e.payload.get("note") or "")) + (" · sent after a privacy warning" if e.warned else ""),
    } for e in rows])
    st.dataframe(table, use_container_width=True, hide_index=True)
    with st.expander("Definitions"):
        for key, d in defs.items():
            st.caption(f"**{d['name']}** ({d['unit']}): {d['meaning']}")
    with_notes = [e for e in rows if e.payload.get("note") and not e.note_removed]
    if with_notes:
        st.markdown("**Remove a note** (for one that contains identifying details; a marker stays)")
        for e in with_notes[:20]:
            c1, c2 = st.columns([5, 1.3])
            c1.text(f"{e.recorded_at[:16].replace('T', ' ')}: {e.payload['note']}")
            if c2.button("Remove", key=f"entry_remove_note_{e.id}"):
                with _open_store() as store:
                    store.entry_remove_note(e.id)
                st.rerun()


def _review_export(pid):
    from src.ptlog.exports import to_review_csv, to_review_report
    from src.ptlog.exports.review_csv import to_questionnaire_csv
    period = _period_selector("review_export_period")
    with _open_store() as store:
        summary = ptreview.review_summary(store, pid, period)
    stamp = datetime.fromisoformat(summary.generated_at).strftime("%Y%m%d_%H%M%S")
    if summary.questionnaires:
        st.download_button("Questionnaire scores (CSV)", to_questionnaire_csv(summary),
                           file_name=f"{pid}_questionnaires_{period}_{stamp}.csv", mime="text/csv",
                           key="review_dl_questionnaires",
                           help="One row per completed questionnaire: date, total, unit, subscale scores, "
                                "and how many questions were left unanswered. The item answers are in the report.")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Review report (text)", to_review_report(summary),
                           file_name=f"{pid}_review_{period}_{stamp}.txt", mime="text/plain", key="review_dl_txt")
    with c2:
        st.download_button("Review data (CSV)", to_review_csv(summary),
                           file_name=f"{pid}_review_{period}_{stamp}.csv", mime="text/csv", key="review_dl_csv")
    st.code(to_review_report(summary), language=None)


# =============================================================================
# PAGE: TRACKER (caseload roster, queue, adherence, discharged, export)
# =============================================================================

TRACKER_SECTIONS = ["Roster", "Queue", "Adherence", "Discharged", "Export", "Settings"]


def _inbox_voice_note(pid, media_id):
    """One spoken note in the thread: the recording, what was written out if anything, and the two
    things the therapist can do with it (feature 014)."""
    from src.media import transcribe
    from src.portal import uploads as ptuploads
    from src.portal import voice as ptvoice
    with _open_store() as store:
        media = store.media_get(media_id)
        job = store.transcription_for(media_id) if media else None
        media_dir = store.media_dir
    if media is None:
        st.markdown("*This voice note is no longer in the record.*")
        return
    st.markdown(f"**Voice note** · {media.duration:.0f} s"
                + (" · heard" if media.reviewed_at else " · not heard yet"))
    if media.deleted_at is not None:
        st.markdown("*The recording was removed.*")
        return
    path = ptuploads.media_path(media_dir, media)
    if path.is_file():
        st.audio(str(path))
    else:
        st.caption("The file is missing from the volume; the record still has its details.")

    if not transcribe.available():
        st.caption("Written out automatically: not available on this installation. "
                   "The recording is the record; a transcript is only an aid to reading it.")
    elif job is None or job.state in ("queued", "running"):
        st.caption("Written out automatically: still being done. The recording plays now; refresh for the text.")
    elif job.state == "failed":
        st.caption(f"Written out automatically: it did not work ({job.reason}). The recording is unaffected.")
    elif job.removed:
        st.caption("Written out automatically: the text was removed.")
    else:
        st.caption("Written out automatically by this installation. It may contain mistakes, so listen "
                   "before relying on it."
                   + (" This text looks like it contains identifying details." if job.warned else ""))
        st.text(job.text or "Nothing recognisable was said.")

    c1, c2, c3 = st.columns([1.2, 1, 2])
    with c1:
        if media.reviewed_at is None and st.button("Mark heard", key=f"voice_heard_{media.id}"):
            with _open_store() as store:
                ptuploads.mark_reviewed(store, media.id)
            st.rerun()
    with c2:
        if st.button("Delete", key=f"voice_delete_{media.id}",
                     help="Removes the recording and anything written out from it. A marker stays in the conversation."):
            with _open_store() as store:
                ptvoice.delete(store, store.media_dir, pid, media.id, by="therapist")
            st.rerun()
    with c3:
        if job is not None and job.state == "done" and not job.removed and job.text:
            if st.button("Remove the text", key=f"voice_text_remove_{media.id}",
                         help="For a transcript that contains identifying details. The recording stays."):
                with _open_store() as store:
                    store.transcription_remove_text(job.id)
                st.rerun()


def _inbox_send(pid, confirm, plan_id=None):
    """Button callback: send the reply (and any files) into the open plan, then empty the box and the
    file picker so nothing can be sent twice."""
    reply = st.session_state.get("inbox_reply", "")
    picker = f"inbox_files_{st.session_state.get('inbox_files_n', 0)}"
    chosen = st.session_state.get(picker) or []
    if confirm and st.session_state.get("inbox_warned") != (pid, reply):
        return                                         # the text changed after the warning: check it again
    try:
        with _open_store() as store:
            files = [(f.type or "", f.getvalue()) for f in chosen]
            ptmessages.send(store, pid, "therapist", reply, confirm=confirm, plan_id=plan_id,
                            files=files, media_dir=store.media_dir)
        st.session_state["inbox_reply"] = ""
        st.session_state["inbox_files_n"] = st.session_state.get("inbox_files_n", 0) + 1
        st.session_state.pop("inbox_warned", None)
    except ptmessages.NeedsConfirmation:
        st.session_state["inbox_warned"] = (pid, reply)
    except PTLogError as exc:
        st.session_state["inbox_error"] = str(exc)


def _inbox_attachments(m, media_dir):
    """Photos as thumbnails and a PDF as a download (feature 017). The files were cleaned on the host."""
    live = [a for a in m.attachments if a.deleted_at is None]
    photos = [a for a in live if a.kind == "photo"]
    if photos:
        st.caption(f"{len(photos)} photo" + ("" if len(photos) == 1 else "s"))
        cols = st.columns(min(len(photos), 4))
        for col, a in zip(cols, photos):
            path = ptattach.path(media_dir, a)
            if path.is_file():
                col.image(path.read_bytes(), width=150)
    for a in live:
        if a.kind != "photo":
            path = ptattach.path(media_dir, a)
            if path.is_file():
                st.download_button(f"Download PDF ({max(1, a.bytes // 1024)} KB)", data=path.read_bytes(),
                                   file_name=f"document-{a.id[:8]}.pdf", mime=a.mime, key=f"inbox_pdf_{a.id}")
    if len(live) < len(m.attachments):
        st.caption("An attachment was removed.")


def _reschedule_flags(store):
    """Every reschedule request the therapist can see, for the inbox and the patient page."""
    rows = []
    for a in ptplans.reschedule_requests(store):
        view = ptplans.appointment_json(store, a)
        rows.append((a, view))
    return rows


def _plan_summary(store, pid):
    """One line per patient for the inbox table: each plan with the patient's unread messages in it."""
    unread = store.messages_unread_by_plan("patient", pid)
    parts = []
    for p in store.plans(pid):
        if p.read_only and not unread.get(p.id):
            continue
        parts.append(p.title + (f" ({unread[p.id]})" if unread.get(p.id) else ""))
    return " · ".join(parts)


def page_inbox():
    """The therapist's inbox: one conversation per patient (feature 008). Text is shown as plain text."""
    st.markdown("## ✉️ Inbox")
    with _open_store() as store:
        rows = ptmessages.inbox(store, include_empty=True)
        flagged = _reschedule_flags(store)
        plan_lines = {r.patient_id: _plan_summary(store, r.patient_id) for r in rows}
    for a, view in flagged:
        st.warning(f"{a.patient_id} asked to reschedule the visit on {view['date']} at {view['time']}"
                   + (f": “{a.request_note}”" if a.request_note else ".") + " Answer it on the Patients page.")
    if not rows:
        st.info("No patients yet.")
        return
    active = [r for r in rows if r.last_at]
    if active:
        st.dataframe(pd.DataFrame([{
            "Patient": r.patient_id, "Unread": r.unread, "Plans": plan_lines.get(r.patient_id, ""),
            "Latest message": ("You: " if r.last_sender == "therapist" else "") + r.first_line,
            "When": (r.last_at or "")[:16].replace("T", " "), "Messaging": "on" if r.enabled else "off"} for r in active]),
            use_container_width=True, hide_index=True)
    else:
        st.info("No conversations yet. Turn messaging on for a patient below to start one.")

    ids = [r.patient_id for r in rows]
    if st.session_state.get("inbox_open") not in ids:
        st.session_state["inbox_open"] = (active[0].patient_id if active else ids[0])
    by_id = {r.patient_id: r for r in rows}
    pid = st.selectbox("Conversation", ids, key="inbox_open",
                       format_func=lambda i: f"{i}" + (f" · {by_id[i].unread} unread" if by_id[i].unread else ""))

    with _open_store() as store:
        plan_list = store.plans(pid)
        by_plan = store.messages_unread_by_plan("patient", pid)
    plan_ids = [p.id for p in plan_list]
    if plan_ids and st.session_state.get("inbox_plan") not in plan_ids:
        unread_first = [p.id for p in plan_list if by_plan.get(p.id)]
        live = [p.id for p in plan_list if not p.read_only]
        st.session_state["inbox_plan"] = (unread_first or live or plan_ids)[0]
    plans_by_id = {p.id: p for p in plan_list}
    plan_id = None
    if plan_ids:
        plan_id = st.selectbox(
            "Plan of care", plan_ids, key="inbox_plan",
            format_func=lambda i: plans_by_id[i].title + (" · archived" if plans_by_id[i].read_only else
                                                         " · completed" if plans_by_id[i].status == "completed" else "")
            + (f" · {by_plan[i]} unread" if by_plan.get(i) else ""))
    plan = plans_by_id.get(plan_id)
    st.markdown("---")
    left, right = st.columns([2, 1])

    with _open_store() as store:
        enabled = ptmessages.is_enabled(store, pid)
        thread = ptmessages.thread(store, pid, viewer="therapist", plan_id=plan_id)  # opening it marks that plan read
        discharged = store.get_discharge(pid) is not None
        latest = store.list_sessions(pid)[:1]
        flags = ptreview.flags_for(store, pid, "30d").flags if latest else []
        media_dir = store.media_dir

    with left:
        st.markdown(f"### {pid}" + (f" · {plan.title}" if plan else ""))
        wanted = st.toggle("Messaging on for this patient", value=enabled, key="inbox_enabled",
                           help="Off hides the conversation from the patient and refuses new messages; what was written is kept.")
        if wanted != enabled:
            with _open_store() as store:
                ptmessages.set_enabled(store, pid, wanted)
            st.rerun()
        if not thread:
            st.caption("No messages in this plan yet.")
        for m in thread:
            who = "You" if m.sender == "therapist" else pid
            when = m.sent_at[:16].replace("T", " ")
            c1, c2 = st.columns([5, 1.3])
            with c1:
                st.caption(f"{who} · {when}" + (" · sent after a privacy warning" if m.warned else "")
                           + (" · seen" if m.sender == "therapist" and m.read_at else ""))
                if m.removed:
                    st.markdown("*This message was removed.*")
                elif m.media_id:
                    _inbox_voice_note(pid, m.media_id)
                else:
                    if m.body:
                        st.text(m.body)                                   # plain text: never rendered as markup
                    if m.attachments:
                        _inbox_attachments(m, media_dir)
            with c2:
                if not m.removed and not m.media_id and not (plan and plan.read_only) and st.button(
                        "Remove", key=f"inbox_remove_{m.id}",
                        help="For a message that contains identifying details. A marker stays."):
                    with _open_store() as store:
                        ptmessages.remove(store, m.id)
                    st.rerun()
        if discharged:
            st.info("This patient is discharged; the conversation is read-only.")
        elif plan and plan.read_only:
            st.info("This plan of care is archived; its conversation is read-only.")
        elif not enabled:
            st.info("Messaging is off for this patient.")
        else:
            st.text_area("Reply", key="inbox_reply", max_chars=ptmessages.MAX_LENGTH,
                         help="Plain text. Do not include names or contact details.")
            st.file_uploader("Attach up to 4 photos or 1 PDF", type=["jpg", "jpeg", "png", "heic", "pdf"],
                             accept_multiple_files=True, key=f"inbox_files_{st.session_state.get('inbox_files_n', 0)}",
                             help="Photos are re-saved on this computer without location or camera details.")
            reply = st.session_state.get("inbox_reply", "")
            pending = st.session_state.get("inbox_warned") == (pid, reply)
            b1, b2 = st.columns(2)
            b1.button("Send", key="inbox_send", type="primary", on_click=_inbox_send, args=(pid, False, plan_id))
            b2.button("Send anyway", key="inbox_send_anyway", disabled=not pending, on_click=_inbox_send,
                      args=(pid, True, plan_id))
            problem = st.session_state.pop("inbox_error", None)
            if problem:
                st.error(problem)
            if pending:
                st.warning("This reply looks like it contains a " + " and a ".join(ptmessages.check_text(reply)) +
                           ". Edit it, or press Send anyway.")

    with right:
        st.markdown("### Context")
        if latest:
            st.markdown("**Latest session**")
            with _open_store() as store:
                st.caption(ptviews.live_summary_line(store.load_session(latest[0].id)))
            st.caption(f"{latest[0].start_time[:10]} · recorded at {'home' if latest[0].origin == 'home' else 'the clinic'}")
        else:
            st.caption("No sessions recorded yet.")
        st.markdown("**Open flags (30 days)**")
        if flags:
            for f in flags[:5]:
                st.caption(f"[{f.rule}] {f.message}")
        else:
            st.caption("None.")


def page_tracker():
    """Manage the caseload; each section renders only when chosen."""
    st.markdown("## 🗂️ Tracker")
    section = st.radio("Section", TRACKER_SECTIONS, horizontal=True, key="tracker_tab", label_visibility="collapsed")
    if section == "Roster":
        _tracker_roster()
    elif section == "Adherence":
        _tracker_adherence()
    elif section == "Queue":
        _tracker_queue()
    elif section == "Settings":
        _tracker_settings()
    elif section == "Discharged":
        _tracker_discharged()
    elif section == "Export":
        _tracker_export()


def _tracker_roster():
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        sort = st.selectbox("Sort", ["attention", "id"], key="tracker_sort")
    with c2:
        program_ids = ["all"] + [p.id for p in ptprograms.list_programs()] + ["custom"]
        program = st.selectbox("Program", program_ids, key="tracker_program_filter")
    with c3:
        only = st.checkbox("Needs attention only", key="tracker_needs_attention")
    with _open_store() as store:
        rows = pttracker.roster(store, sort=sort, program=None if program == "all" else program, needs_attention=only)
    if not rows:
        st.info("No active patients match.")
        return
    table = pd.DataFrame(ptviews.roster_table_rows(rows)).rename(columns=ptviews.roster_columns())
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"{len(rows)} active patient(s). {ptviews.metric_definition('adherence_pct')}")


def _tracker_adherence():
    pid = st.session_state.get("patient_id") or "unassigned"
    with _open_store() as store:
        try:
            adh = pttracker.adherence_for(store, pid)
            effective = store.effective_thresholds(pid)
        except PTLogError as exc:
            st.error(str(exc))
            return
    if adh.assignment is None:
        st.info(f"No program assigned to {pid}. Assign one on the Patients page.")
        return
    st.markdown(f"**{ptviews.assignment_line(adh)}**")
    if adh.weeks:
        st.dataframe(pd.DataFrame(ptviews.adherence_table_rows(adh)).rename(columns={
            "week": "Week", "from": "From", "to": "To", "recorded": "Recorded / planned (count)",
            "status": "Status", "performed": "Exercises performed", "missing": "Exercises missing"}),
            use_container_width=True, hide_index=True)
    for line in ptviews.adherence_lines(adh)[1:]:
        if line.startswith("Adherence:") or line.startswith("First week") or line.startswith("Starts") or line.startswith("Superseded"):
            st.write(line)
    st.markdown(ptviews.adherence_threshold_line(effective))
    st.caption(ptviews.metric_definition("adherence_pct"))


def _tracker_settings():
    """Installation-wide attention thresholds; patients without an override use these."""
    st.markdown("### Installation thresholds")
    flash = st.session_state.pop("install_thresholds_flash", None)
    if flash:
        st.success(flash)
    with _open_store() as store:
        stored = store.get_installation_thresholds()
    effective = ptthresholds.resolve(None, stored)
    rows = ptviews.threshold_rows(effective)
    _threshold_table(rows)
    st.caption("Patients with their own value (Review → Goals & settings) are not affected by changes here.")
    cols = st.columns(4)
    entered = {}
    for i, r in enumerate(rows):
        with cols[i % 4]:
            entered[r["key"]] = st.number_input(
                f"{r['name']} ({r['unit']})", min_value=r["minimum"], max_value=r["maximum"],
                value=int(r["value"]), step=1, key=f"install_threshold_{r['key']}", help=r["meaning"])
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save installation thresholds", key="install_thresholds_save"):
            changed = {k: int(v) for k, v in entered.items() if int(v) != r_default(k) or k in stored}
            try:
                with _open_store() as store:
                    store.set_installation_thresholds(changed)
                st.session_state["install_thresholds_flash"] = (
                    "Installation thresholds saved." if changed else "No changes: every value is the built-in default.")
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))
    with c2:
        if st.button("Restore built-in defaults", key="install_thresholds_restore"):
            with _open_store() as store:
                store.restore_builtin_thresholds()
            for r in rows:
                st.session_state.pop(f"install_threshold_{r['key']}", None)
            st.rerun()
    with _open_store() as store:
        changes = store.threshold_history(None, limit=50)
    _history_table(changes, "Installation change history")


def r_default(key):
    return ptthresholds.THRESHOLDS[key].default


def _tracker_queue():
    with _open_store() as store:
        st.caption(f"Adherence attention threshold: {store.get_adherence_threshold()}% for the installation "
                   "(change it under Settings; a patient's own value is set in Review → Goals & settings).")
    with _open_store() as store:
        q = pttracker.queue(store)
    if q.count == 0:
        st.success("Caseload is up to date.")
        return
    for kind, items in q.items.items():
        if not items:
            continue
        with st.expander(f"{ptviews.QUEUE_LABELS[kind]} ({len(items)})", expanded=True):
            for it in items:
                (st.warning if kind in ("attention_flag", "practice_gap") else st.info)(f"**{it.patient_id}** — {it.description}  \n→ {it.target}")


def _tracker_discharged():
    with _open_store() as store:
        rows = store.discharged_patients()
    if not rows:
        st.info("No discharged patients.")
        return
    st.dataframe(pd.DataFrame([{"Patient": p.id, "Label": p.label or "", "Discharged on": d.discharged_on, "Reason": d.reason or ""}
                               for p, d in rows]), use_container_width=True, hide_index=True)
    pid = st.selectbox("Patient", [p.id for p, _ in rows], key="tracker_reactivate_select")
    if st.button("Reactivate", key="tracker_reactivate_button"):
        with _open_store() as store:
            store.reactivate(pid)
        st.success(f"Reactivated {pid}")
        st.rerun()


def _tracker_export():
    from src.ptlog.exports import to_roster_csv
    with _open_store() as store:
        rows = pttracker.roster(store)
    now = datetime.now()
    st.download_button("Roster (CSV)", to_roster_csv(rows, now), file_name=f"roster_{now:%Y%m%d_%H%M%S}.csv",
                       mime="text/csv", key="tracker_dl_roster")
    st.caption(f"{len(rows)} active patient(s); the export always includes every active patient.")


# =============================================================================
# PAGE: HOW IT WORKS (Educational)
# =============================================================================

def page_how_it_works():
    """Render the educational page explaining the technology."""
    st.markdown("## 📚 How It Works")
    st.markdown("*Understanding the AI behind Limber*")

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
# PAGES: PEOPLE (admins) AND MY SETTINGS (feature 016)
# =============================================================================

PREF_CSS = {
    "larger_text": "html, body, .stApp, .stMarkdown p, label, input, textarea { font-size: 20px !important; }",
    "high_contrast": ".stApp { background: #FFFFFF !important; } .stApp, .stApp p, .stApp label, h1, h2, h3 "
                     "{ color: #000000 !important; } .stCaption, small { color: #2E2E2E !important; }",
    "reduced_motion": "*, *::before, *::after { animation: none !important; transition: none !important; }",
}
PREF_LABELS = {"larger_text": "Larger text", "high_contrast": "Higher contrast", "reduced_motion": "Less motion"}


def _apply_prefs(prefs):
    rules = " ".join(PREF_CSS[k] for k in ptaccounts.PREFS if prefs.get(k))
    if rules:
        st.markdown(f"<style>{rules}</style>", unsafe_allow_html=True)


def page_my_settings():
    st.markdown("## ⚙️ My settings")
    me = _account()
    with SessionStore(default_db_path()).open() as store:
        current = ptaccounts.get_prefs(store, me.id)
    with st.form("my_settings"):
        chosen = {k: st.checkbox(PREF_LABELS[k], value=current[k]) for k in ptaccounts.PREFS}
        if st.form_submit_button("Save"):
            with SessionStore(default_db_path()).open() as store:
                ptaccounts.set_prefs(store, me.id, chosen)
            st.rerun()
    st.caption("These follow you to every device you sign in on.")


def page_people():
    """Admins: everyone with an account, invitations, and which therapist each patient belongs to."""
    st.markdown("## 🧑‍🤝‍🧑 People")
    me = _account()
    with SessionStore(default_db_path()).open() as store:
        try:
            rows = ptaccounts.people(store, me)
        except PTLogError as exc:
            st.error(str(exc))
            return
        therapists = [a for a in store.account_list() if a.is_therapist and a.status == "active"]
    table = [{"Name": r["display_name"] or "—", "Username": r["username"] or "—", "Role": r["role"],
              "Patient ID": r["patient_id"] or "", "Therapist": r["therapist"] or "",
              "Status": r["status"], "Since / expires": ptviews.date_minute(r["since"])} for r in rows]
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

    st.markdown("### Invite someone")
    role = st.radio("Role", ["therapist", "patient", "admin"], horizontal=True, key="invite_role")
    with st.form("invite_form"):
        therapist_id, patient_id, make_admin = None, None, False
        if role == "patient":
            if not therapists:
                st.info("Invite a therapist first: every patient belongs to one.")
            therapist_id = st.selectbox("Therapist", [t.id for t in therapists],
                                        format_func=lambda i: next(t.username for t in therapists if t.id == i))
            patient_id = st.text_input("Pseudonymous patient ID", placeholder="P-031",
                                       help="An existing patient or a new one. Never a name.")
        elif role == "therapist":
            make_admin = st.checkbox("Also an admin")
        if st.form_submit_button("Create invite link", type="primary"):
            try:
                with SessionStore(default_db_path()).open() as store:
                    token, invite = ptaccounts.create_invite(store, me, role, therapist_id=therapist_id,
                                                             patient_id=patient_id or None, make_admin=make_admin)
                st.session_state.invite_link = f"{PORTAL_URL}/invite/{token}"
                st.session_state.invite_expires = invite.expires_at
            except PTLogError as exc:
                st.error(str(exc))
            else:
                st.rerun()                               # the new invite shows in the table above
    if st.session_state.get("invite_link"):
        st.success("Copy this link now and give it to the person. It is shown only once, works once, and expires "
                   f"{ptviews.date_minute(st.session_state.invite_expires)}. Limber does not send it anywhere.")
        st.code(st.session_state.invite_link, language=None)
        if st.button("Done, hide the link"):
            st.session_state.pop("invite_link", None)
            st.rerun()

    pending = [r for r in rows if r["status"] == "invited"]
    if pending:
        st.markdown("### Revoke an unused invite")
        choice = st.selectbox("Invite", [r["invite_id"] for r in pending],
                              format_func=lambda i: next(f"{r['role']} {r['patient_id'] or ''} · expires "
                                                         f"{ptviews.date_minute(r['since'])}" for r in pending
                                                         if r["invite_id"] == i))
        if st.button("Revoke invite"):
            with SessionStore(default_db_path()).open() as store:
                ptaccounts.revoke_invite(store, me, choice)
            st.rerun()

    accounts_rows = [r for r in rows if r["id"] is not None and r["id"] != me.id]
    if accounts_rows:
        st.markdown("### Disable or re-enable an account")
        target = st.selectbox("Account", [r["id"] for r in accounts_rows],
                              format_func=lambda i: next(f"{r['username']} ({r['role']}, {r['status']})"
                                                         for r in accounts_rows if r["id"] == i))
        status = next(r["status"] for r in accounts_rows if r["id"] == target)
        if st.button("Re-enable" if status == "disabled" else "Disable"):
            try:
                with SessionStore(default_db_path()).open() as store:
                    ptaccounts.set_status(store, me, target, "active" if status == "disabled" else "disabled")
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))

    with SessionStore(default_db_path()).open() as store:
        patient_ids = [p.id for p in store.list_patients() if not p.is_builtin]
    if patient_ids and therapists:
        st.markdown("### Move a patient to another therapist")
        st.caption("The new therapist sees the patient's whole history; the old one no longer sees any of it.")
        c1, c2 = st.columns(2)
        with c1:
            pid = st.selectbox("Patient", patient_ids, key="reassign_patient")
        with c2:
            tid = st.selectbox("To therapist", [t.id for t in therapists], key="reassign_to",
                               format_func=lambda i: next(t.username for t in therapists if t.id == i))
        if st.button("Move patient"):
            with SessionStore(default_db_path()).open() as store:
                ptaccounts.reassign(store, me, pid, tid)
            st.success(f"{pid} now belongs to {next(t.username for t in therapists if t.id == tid)}.")


# =============================================================================
# MAIN APP
# =============================================================================

@st.cache_resource
def _therapist_limiter():
    """One attempt limiter for this app process (shared by every browser tab)."""
    return ptaccess.LoginLimiter()


def therapist_gate() -> bool:
    """True when the therapist app may be shown (feature 007, US6).

    With no therapist password set (a private machine) the app opens as it always has. With one
    set, nothing but this sign-in is rendered until the visitor presents a single-use pass from
    the Limber front page or the password itself."""
    with _open_store() as store:
        if not ptadmin.password_is_set(store):
            st.session_state.pop("account_id", None)
            return True
        who = ptadmin.signed_in(store, st.session_state.get("admin_token"))
        if who is not None:
            st.session_state.account_id = who.id
            return True
        st.session_state.pop("account_id", None)
        a_pass = st.query_params.get("pass")
        if a_pass:
            token = ptadmin.redeem_pass(store, a_pass)
            st.query_params.clear()                      # the pass must not stay in the address bar
            if token:
                st.session_state.admin_token = token
                st.session_state.account_id = ptadmin.signed_in(store, token).id
                return True

    left, middle, right = st.columns([1, 1.2, 1])
    with middle:
        st.markdown(f'''<div class="limber-lockup">{LIMBER_MARK_SVG}<span>Limber</span></div>
            <div class="limber-tag">Therapist sign-in</div>''', unsafe_allow_html=True)
        username = st.text_input("Username", key="therapist_username")
        password = st.text_input("Password", type="password", key="therapist_password")
        if st.button("Sign in", key="therapist_signin", type="primary", use_container_width=True):
            try:
                with _open_store() as store:
                    token = ptadmin.sign_in(store, password, "therapist-app", _therapist_limiter(),
                                            username=username.strip() or None)
                    st.session_state.admin_token = token
                    st.session_state.account_id = ptadmin.signed_in(store, token).id
                st.session_state.pop("therapist_password", None)
                st.rerun()
            except PTLogError as exc:
                st.error(str(exc))
        st.caption("Patients sign in with their access code on the Limber front page.")
    return False


def main():
    """Main application entry point."""
    init_session_state()
    if not therapist_gate():
        return
    me = _account()
    if me is not None:
        with SessionStore(default_db_path()).open() as store:
            _apply_prefs(ptaccounts.get_prefs(store, me.id))
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
    elif page == 'obs_logs':
        page_observation_logs()
    elif page == 'review':
        page_review()
    elif page == 'tracker':
        page_tracker()
    elif page == 'inbox':
        page_inbox()
    elif page == 'learn':
        page_how_it_works()
    elif page == 'people':
        page_people()
    elif page == 'settings':
        page_my_settings()
    else:
        page_home()


if __name__ == "__main__":
    main()
