"""How it works (feature 019 slice 6, T029): what Limber measures and how, from the code itself. No placeholder
images and no calculator (SC-003): the form score is the engine's own rule (analyze.py, _calculate_form_score), the
measures are views.METRIC_DEFINITIONS, and the comparison of models is gate G2's."""

from __future__ import annotations

from html import escape

from src.clinic import shell
from src.ptlog import views

KEYPOINTS = ("nose", "left eye", "right eye", "left ear", "right ear", "left shoulder", "right shoulder", "left elbow",
             "right elbow", "left wrist", "right wrist", "left hip", "right hip", "left knee", "right knee",
             "left ankle", "right ankle")
MEASURES = ("rom", "form_score", "duration_seconds", "avg_form_score", "avg_rom", "total_reps", "tempo_sd",
            "partial_share", "adherence_pct")


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def content(exercises) -> str:
    ex_rows = "".join(
        f"<tr><td>{_e(cfg.name)}</td><td>{_e(' – '.join(KEYPOINTS[i] for i in cfg.keypoints))}</td>"
        f'<td class="r">{cfg.down_angle:g}°</td><td class="r">{cfg.up_angle:g}°</td><td>{_e(cfg.side)}</td></tr>'
        for cfg in exercises.values())
    measures = "".join(f"<dt>{_e(views.metric_label(m))}</dt><dd>{_e(views.metric_definition(m))}</dd>"
                       for m in MEASURES)
    return (
        '<div class="page-head"><div class="stack tight"><h1>How it works</h1><p class="dim">What Limber measures, how, '
        'and how far to trust it.</p></div></div>'
        '<section class="sec"><h2>1. Finding the body</h2>'
        '<p>A pose model finds 17 body points in each frame: nose, eyes, ears, shoulders, elbows, wrists, hips, knees '
        'and ankles, each with a confidence from 0 to 1. A point below 0.3 is ignored, and a frame without the points '
        'an exercise needs is skipped rather than guessed.</p>'
        '<ul class="lines"><li><span class="strong">In the browser (MoveNet Lightning)</span><span class="grow-col">'
        'The patient app\'s guided sessions, and video analysis on this demo. The video never leaves the device; only '
        'the points are sent, 15 times a second.</span></li>'
        '<li><span class="strong">On the clinic computer (YOLO11m-pose)</span><span class="grow-col">Video analysis on '
        'a local install.</span></li></ul></section>'
        '<section class="sec"><h2>2. From points to an angle</h2><p>Each exercise names three points: two ends and the '
        'joint between them. The angle at the joint is the angle between the two lines from the joint to the ends '
        '(from their dot product), in degrees, 0 to 180. It is smoothed over the last five frames.</p>'
        f'<div class="scroll" tabindex="0" role="region" aria-label="Exercises, scrolls sideways when wide">'
        '<table class="table"><thead><tr><th scope="col">Exercise</th><th scope="col">Points (end – joint – end)</th>'
        '<th scope="col" class="r">Flexed angle</th><th scope="col" class="r">Extended angle</th><th scope="col">Side'
        f'</th></tr></thead><tbody>{ex_rows}</tbody></table></div></section>'
        '<section class="sec"><h2>3. Counting reps</h2><p>A rep is counted when the angle travels from one end of the '
        'movement past the other and back. A movement that turns back before reaching the far end is a partial rep: '
        'it is recorded, but not counted.</p></section>'
        '<section class="sec"><h2>4. The form score, 0 to 100</h2><p>Every counted rep gets a score from three parts:</p>'
        '<ul class="lines"><li><span class="strong">Range, 40 points</span><span class="grow-col">The angle the rep '
        'covered, as a share of the exercise\'s range (flexed to extended), up to 1.</span></li>'
        '<li><span class="strong">Smoothness, 30 points</span><span class="grow-col">1 ÷ (1 + the spread of the '
        'frame-to-frame changes in angle): a jerky rep scores less.</span></li>'
        '<li><span class="strong">Balance, 30 points</span><span class="grow-col">How evenly the rep\'s frames fall '
        'above and below its midpoint: up and down phases of similar length score more.</span></li></ul>'
        '<p class="small dim">A rep with fewer than two angles scores 50; a part without enough data scores half its '
        'points.</p></section>'
        '<section class="sec"><h2>5. How far to trust the numbers</h2>'
        '<p>On side-on clips the two pose models agree on rep counts and form scores (within 2 points), but not on '
        'range of motion: on the test clips the browser model read 8° less on squats and 14–21° more on push-ups. So '
        'sessions are kept apart by how they were measured (in the clinic, by browser pose from a video, at home), and '
        'their range of motion is never compared across those groups.</p>'
        '<p>A camera in front of the person, or anything covering the joint, can hide the movement: on an angled '
        'leg-extension clip both models counted fewer than the 3 reps. When a set has more partial reps than full '
        'ones, Limber says so beside the count.</p></section>'
        f'<section class="sec"><h2>6. The measures</h2><dl class="kv">{measures}</dl></section>')


def page(account, classes: str, exercises) -> str:
    body = shell.top_bar(account, "how") + f'<main class="page wide" id="main">{content(exercises)}</main>'
    return shell.document("How it works", body, classes)
