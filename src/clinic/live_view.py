"""The therapist's Live session page (feature 019 slice 7), from the design export's LiveSession screens. The
camera and the pose model run in this browser; live.js sends the body points and draws what the engine says."""

from __future__ import annotations

from html import escape
from typing import List, Optional

from src.clinic import shell
from src.clinic.patients_view import field, select


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def content(patients: List[str], chosen: Optional[str], exercises: List[tuple]) -> str:
    if not patients:
        return ('<div class="page-head"><h1>Live session</h1></div><p class="dim">Register a patient first: every '
                'session is recorded under one.</p>')
    setup = ('<form class="stack" data-live-setup novalidate><div class="rowflex top-row">'
             + select("Patient", "patient_id", [(p, p) for p in patients], chosen or patients[0], cls="w-day")
             + select("Exercise", "exercise", exercises, cls="w-wide")
             + field("Target reps (optional)", "target_reps", "", "number", cls="w-day", extra=' min="1" max="100"')
             + select("Camera", "camera", [("user", "Front"), ("environment", "Back")], "user", cls="w-day")
             + '</div><div class="rowflex"><button class="btn" type="submit">Start the session</button></div>'
             '<p class="error-text" role="alert" data-error hidden></p>'
             '<p class="small dim">The camera stays in this browser; only the body points are sent. The session is '
             'recorded under the patient as measured by browser pose.</p></form>')
    live = ('<section class="live-grid" data-live hidden><div class="cam-wrap"><video data-cam muted playsinline>'
            '</video><canvas data-overlay></canvas></div><div class="stack">'
            '<div class="facts"><div class="fact"><span class="lbl" data-exercise>Exercise</span>'
            '<span class="val"><span data-reps>0</span> <small>of <span data-target>—</span></small></span>'
            '<span class="small dim">Reps counted</span></div>'
            '<div class="fact"><span class="lbl">Angle</span><span class="val" data-angle>—</span>'
            '<span class="small dim" data-phase></span></div></div>'
            '<p class="strong" role="status" data-form></p><ul class="lines" data-messages></ul>'
            '<p class="small warn-text" role="alert" data-notice hidden></p>'
            '<div class="rowflex top-row">' + select("Switch to", "switch_to", exercises, cls="w-wide")
            + '<button class="btn quiet small" type="button" data-act="switch">Switch exercise</button></div>'
            '<div class="rowflex top-row">' + field("New target", "new_target", "", "number", cls="w-day",
                                                    extra=' min="1" max="100"')
            + '<button class="btn quiet small" type="button" data-act="target">Set target</button></div>'
            '<div class="rowflex"><button class="btn quiet small" type="button" data-act="reset">Reset count</button>'
            '<button class="btn quiet small" type="button" data-act="shot">Screenshot</button>'
            '<button class="btn" type="button" data-act="stop">Stop and save</button></div></div></section>')
    done = ('<section class="stack" data-done hidden><h2>Session saved</h2><p data-done-lead></p>'
            '<ul class="lines" data-summary></ul><div class="rowflex"><a class="btn" data-log href="#">Open its log</a>'
            '<a class="btn quiet" href="/therapist/live">Start another</a></div></section>')
    return ('<div class="page-head"><div class="stack tight"><h1>Live session</h1><p class="dim">Count reps and check '
            f'form while the patient exercises in front of this computer\'s camera.</p></div></div>{setup}{live}{done}')


def page(account, classes: str, patients: List[str], chosen: Optional[str], exercises: List[tuple]) -> str:
    body = shell.top_bar(account, "live") + f'<main class="page wide" id="main">{content(patients, chosen, exercises)}</main>'
    scripts = ("clinic.js",) + tuple(f"vendor/{n}" for n in ("tf-core.min.js", "tf-converter.min.js",
                                                             "tf-backend-webgl.min.js", "pose-detection.min.js")) + (
        "live.js",)
    return shell.document("Live session", body, classes, scripts=scripts)
