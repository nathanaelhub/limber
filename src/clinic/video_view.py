"""The Video analysis page (feature 019 slice 6), from the design export's VideoAnalysis screen. The clip stays in
the browser; video.js finds the body points and sends only those."""

from __future__ import annotations

from html import escape
from typing import List

from src.clinic import shell
from src.clinic.patients_view import field, select

VENDOR = "/therapist/static/vendor"


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def content(patients: List[str], exercises: List[tuple]) -> str:
    if not patients:
        return ('<div class="page-head"><h1>Video analysis</h1></div><p class="dim">Register a patient first: every '
                'analysis is recorded under one.</p>')
    form = (f'<form class="stack" data-video novalidate>'
            '<div class="rowflex top-row">' + select("Patient", "patient_id", [(p, p) for p in patients], cls="w-day")
            + select("Exercise", "exercise", exercises, cls="w-wide")
            + field("Target reps (optional)", "target_reps", "", "number", cls="w-day", extra=' min="1" max="100"')
            + "</div>"
            + field("Describe the clip (optional)", "label", "", extra=' maxlength="60" placeholder="Side view, week 3"',
                    hint="Never a name. The file's own name is not used.")
            + '<label class="field"><span>Clip</span><input class="input" type="file" name="clip" accept="video/*" '
            'required><span class="hint">MP4, MOV or WebM, up to 15 minutes. Film from the side, with the whole body '
            'in view.</span></label>'
            '<div class="rowflex"><button class="btn" type="submit">Analyse the clip</button></div>'
            '<p class="small" role="status" data-progress hidden></p>'
            '<p class="error-text" role="alert" data-error hidden></p></form>')
    return ('<div class="page-head"><div class="stack tight"><h1>Video analysis</h1><p class="dim">The clip is analysed '
            'in this browser and is never uploaded. Only the body points found in it are sent, and the session is '
            'recorded under the patient as a video measured by browser pose (MoveNet).</p></div></div>'
            f'{form}<video class="vh" data-clip muted playsinline></video><canvas class="vh" data-canvas></canvas>'
            '<p class="small dim">Browser pose counts reps and scores form like the clinic model, but reads range of '
            'motion differently, so these sessions are kept apart from others in Review. See How it works.</p>')


def page(account, classes: str, patients: List[str], exercises: List[tuple]) -> str:
    body = shell.top_bar(account, "video") + f'<main class="page wide" id="main">{content(patients, exercises)}</main>'
    scripts = ("clinic.js",) + tuple(f"vendor/{n}" for n in ("tf-core.min.js", "tf-converter.min.js",
                                                             "tf-backend-webgl.min.js", "pose-detection.min.js")) + (
        "video.js",)
    return shell.document("Video analysis", body, classes, scripts=scripts)
