"""Gate G2 (019) = G5 (020): browser pose against the clinic model, replayed through the real engine.

The fixtures are body points captured once from the three Ultralytics demo clips, at 15 frames a second: MoveNet
Lightning in headless Chrome (as the patient app runs it) and YOLO11m-pose (as the clinic runs it). These tests pin
what the engine makes of them, so a change to the engine or to the hosted video path that moves a rep count or a
range of motion is seen. Hand counts: 4 squats, 4 push-ups, 3 leg extensions (issue #23)."""

from pathlib import Path

import pytest

from scripts import compare_pose

POINTS = Path(__file__).resolve().parent / "fixtures" / "pose"


@pytest.fixture(scope="module")
def rows():
    return {(r["clip"].split(".")[0], r["exercise"], r["model"]): r for r in compare_pose.compare(POINTS)}


def test_every_clip_and_model_is_replayed(rows):
    assert len(rows) == 10


@pytest.mark.parametrize("clip,exercise", [("Squats", "squat"), ("Pushups", "pushup"), ("Pushups", "pushup_right")])
def test_both_models_count_the_squats_and_push_ups(rows, clip, exercise):
    for model in ("yolo11m-pose", "movenet-lightning-4"):
        assert rows[(clip, exercise, model)]["reps"] == 4, model


def test_range_of_motion_differs_by_model_as_007_found(rows):
    def rom(clip, ex, model):
        return rows[(clip, ex, model)]["rom"]
    assert rom("Squats", "squat", "yolo11m-pose") == pytest.approx(117.5, abs=0.5)
    assert rom("Squats", "squat", "movenet-lightning-4") == pytest.approx(109.4, abs=0.5)
    assert rom("Pushups", "pushup", "movenet-lightning-4") - rom("Pushups", "pushup", "yolo11m-pose") == \
        pytest.approx(13.9, abs=1.0)


def test_neither_model_counts_the_leg_extensions_from_this_angle(rows):
    """Issue #23: the camera is in front at an angle; both models undercount the 3 reps."""
    for ex in ("knee_extension", "knee_extension_right"):
        assert rows[("Legextension", ex, "yolo11m-pose")]["reps"] < 3
        assert rows[("Legextension", ex, "movenet-lightning-4")]["reps"] == 0
        assert rows[("Legextension", ex, "movenet-lightning-4")]["partials"] == 3
