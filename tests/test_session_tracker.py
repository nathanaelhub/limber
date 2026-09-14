"""
Tests for Session Tracking Module
==================================

Tests the analysis methods (trends, comparison, attention flags, summary card).
The writer methods were retired by the unified session log (specs/001-unified-session-log).

Run with:
    pytest tests/test_session_tracker.py -v
"""

import pytest
import json
import csv
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.session_tracker import (
    SessionTracker,
    SessionData,
    ExerciseRecord,
    ProgressMetrics,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test data."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def session_tracker(temp_data_dir):
    """Create a SessionTracker with temporary storage."""
    return SessionTracker(data_dir=temp_data_dir, patient_id="test_patient")


@pytest.fixture
def sample_exercise_record():
    """Create a sample exercise record."""
    return ExerciseRecord(
        exercise_name="Knee Extension",
        reps_completed=10,
        target_reps=10,
        avg_form_score=85.0,
        min_rom=90.0,
        max_rom=165.0,
        rom_range=75.0,
        avg_rep_duration=2.5,
        form_warnings=["Minor hip movement"],
        notes="Good session"
    )


@pytest.fixture
def multiple_sessions(temp_data_dir):
    """Create a tracker with multiple sessions for progress testing."""
    tracker = SessionTracker(data_dir=temp_data_dir, patient_id="progress_test")

    # Create several sessions over time
    dates = [
        datetime.now() - timedelta(days=20),
        datetime.now() - timedelta(days=15),
        datetime.now() - timedelta(days=10),
        datetime.now() - timedelta(days=5),
        datetime.now(),
    ]

    # ROM improves over time: 70 -> 75 -> 78 -> 82 -> 85
    roms = [70, 75, 78, 82, 85]
    # Form scores: 75 -> 78 -> 80 -> 82 -> 85
    forms = [75, 78, 80, 82, 85]

    for i, (date, rom, form) in enumerate(zip(dates, roms, forms)):
        session = SessionData(
            session_id=f"progress_test_{date.strftime('%Y%m%d_%H%M%S')}",
            patient_id="progress_test",
            date=date.strftime('%Y-%m-%d'),
            start_time="10:00:00",
            end_time="10:30:00",
            duration_minutes=30,
            exercises=[
                ExerciseRecord(
                    exercise_name="Knee Extension",
                    reps_completed=10,
                    target_reps=10,
                    avg_form_score=form,
                    min_rom=90.0,
                    max_rom=90.0 + rom,
                    rom_range=rom,
                    avg_rep_duration=2.5
                )
            ],
            overall_form_score=form
        )
        tracker.session_history.append(session)

    return tracker


# =============================================================================
# SESSION TRACKER INITIALIZATION TESTS
# =============================================================================

class TestSessionTrackerInit:
    """Tests for SessionTracker initialization."""

    def test_tracker_creation(self, temp_data_dir):
        """Test basic tracker creation."""
        tracker = SessionTracker(data_dir=temp_data_dir, patient_id="test123")

        assert tracker.patient_id == "test123"
        assert tracker.data_dir == Path(temp_data_dir)
        assert tracker.current_session is None
        assert len(tracker.session_history) == 0

# =============================================================================
# DATA PERSISTENCE TESTS
# =============================================================================

class TestSessionRetrieval:
    """Tests for retrieving session data."""

    def test_get_nonexistent_session(self, session_tracker):
        """Should return None for nonexistent session."""
        session = session_tracker.get_session_by_id("nonexistent_id")
        assert session is None

    def test_get_recent_sessions(self, multiple_sessions):
        """Test getting recent sessions."""
        recent = multiple_sessions.get_recent_sessions(count=3)

        assert len(recent) == 3
        # Should be most recent (last in history)
        assert recent[-1] == multiple_sessions.session_history[-1]


# =============================================================================
# PROGRESS TRACKING TESTS
# =============================================================================

class TestProgressTracking:
    """Tests for progress calculation."""

    def test_calculate_progress(self, multiple_sessions):
        """Test progress calculation over time."""
        progress = multiple_sessions.calculate_progress("Knee Extension", days_back=30)

        assert progress is not None
        assert progress.exercise_name == "Knee Extension"
        assert progress.sessions_count == 5

    def test_progress_rom_trend(self, multiple_sessions):
        """ROM should show improving trend."""
        progress = multiple_sessions.calculate_progress("Knee Extension", days_back=30)

        assert progress.rom_trend == "improving"
        assert progress.rom_change_percent > 0

    def test_progress_form_score_trend(self, multiple_sessions):
        """Form score should show improving trend."""
        progress = multiple_sessions.calculate_progress("Knee Extension", days_back=30)

        assert progress.form_score_trend == "improving"
        assert progress.form_score_change > 0

    def test_progress_insufficient_data(self, session_tracker):
        """Should return None with insufficient data."""
        progress = session_tracker.calculate_progress("Knee Extension", days_back=30)
        assert progress is None

    def test_compare_sessions(self, multiple_sessions):
        """Test comparing two sessions."""
        sessions = multiple_sessions.session_history
        comparison = multiple_sessions.compare_sessions(
            sessions[0].session_id,
            sessions[-1].session_id
        )

        assert "session1" in comparison
        assert "session2" in comparison
        assert "score_change" in comparison
        assert "exercises" in comparison

    def test_exercises_needing_attention(self, temp_data_dir):
        """Test identifying exercises that need attention."""
        tracker = SessionTracker(data_dir=temp_data_dir, patient_id="attention_test")

        # Create sessions with declining form
        for i in range(5):
            date = datetime.now() - timedelta(days=i)
            session = SessionData(
                session_id=f"attention_{i}",
                patient_id="attention_test",
                date=date.strftime('%Y-%m-%d'),
                start_time="10:00:00",
                end_time="10:30:00",
                duration_minutes=30,
                exercises=[
                    ExerciseRecord(
                        exercise_name="Problem Exercise",
                        reps_completed=8,
                        target_reps=10,
                        avg_form_score=80 - i * 5,  # Declining: 80, 75, 70, 65, 60
                        min_rom=90,
                        max_rom=150,
                        rom_range=60,
                        avg_rep_duration=2.5,
                        form_warnings=["Issue " + str(i)]
                    )
                ],
                overall_form_score=80 - i * 5
            )
            tracker.session_history.append(session)

        concerns = tracker.get_exercises_needing_attention()

        # Should identify the declining exercise
        assert len(concerns) > 0
        assert any(c["exercise"] == "Problem Exercise" for c in concerns)


# =============================================================================
# VISUALIZATION TESTS
# =============================================================================

class TestVisualization:
    """Tests for visualization methods."""

    def test_summary_card_no_session(self, session_tracker):
        """Should handle no session gracefully."""
        summary = session_tracker.generate_session_summary_card()
        assert "No session data available" in summary


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================
