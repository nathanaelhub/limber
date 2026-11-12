"""
The patient portal as a Vercel Python function (feature 020, slice D). Vercel loads `app` from the generated
`index.py` (see deploy/vercel/). Every hosted setting is required; a missing one stops the function from starting
with a plain reason, rather than running half-configured.

The therapist app is not deployed to Vercel (Streamlit needs one long-lived server); until the 019 clinic app's
pages go online, the Therapist door explains that (spec 020, Story 5).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

REQUIRED = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "LIMBER_DEMO", "LIMBER_PUBLIC_ORIGIN", "PTASSIST_PORTAL_KEY",
            "LIMBER_R2_ACCOUNT_ID", "LIMBER_R2_BUCKET", "LIMBER_R2_ACCESS_KEY_ID", "LIMBER_R2_SECRET_ACCESS_KEY")

THERAPIST_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Limber · Therapist</title><link rel="stylesheet" href="/static/portal.css"></head>
<body><main class="card">
<h1>The therapist app isn't online in this demo yet</h1>
<p>Your sign-in worked. In this hosted demo only the patient side is online so far. The therapist app runs on the
clinic's own computer, and its new version is being built to work here too.</p>
<p><a href="/">Back to the front page</a></p>
</main></body></html>"""


def use_clinic_time(env: Mapping[str, str]) -> None:
    """The record stores clinic-local times (datetime.now()). Vercel's clock is UTC and it reserves the TZ setting,
    so the zone comes from LIMBER_TIME_ZONE, defaulting to the clinic default."""
    import time
    from src.portal.plans import DEFAULT_TIME_ZONE
    os.environ["TZ"] = (env.get("LIMBER_TIME_ZONE") or "").strip() or DEFAULT_TIME_ZONE
    time.tzset()


def check_settings(env: Mapping[str, str]) -> None:
    missing = [k for k in REQUIRED if not (env.get(k) or "").strip()]
    if missing:
        raise RuntimeError("The hosted demo needs these settings in Vercel: " + ", ".join(missing))
    if env["LIMBER_DEMO"] != "1":
        raise RuntimeError("LIMBER_DEMO must be 1: the hosted record is the simulated demo only.")


def build(db_path: Path, origin: str, key: Optional[bytes] = None):
    from starlette.responses import HTMLResponse
    from interfaces.patient_portal import create_app
    origin = origin.rstrip("/")
    app = create_app(db_path=db_path, key=key, allowed_origins=[origin], trust_proxy=True,
                     secure_cookie=origin.startswith("https://"), therapist_url=f"{origin}/therapist")

    async def therapist_door(_request):
        return HTMLResponse(THERAPIST_PAGE, headers={"Cache-Control": "no-store"})

    app.router.add_route("/therapist", therapist_door, methods=["GET"])

    from starlette.responses import JSONResponse
    from src.ptlog import backend

    async def demo_unavailable(_request, exc):
        # A visit while the demo is being reset, or a record that isn't the demo: a plain answer, not an error page.
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Retry-After": "120"})

    app.add_exception_handler(backend.HostedRecordRefused, demo_unavailable)
    return app


def _app_from_environment():
    check_settings(os.environ)
    use_clinic_time(os.environ)
    db = Path(os.environ.get("PTASSIST_DB", "/tmp/limber/replica.db"))
    db.parent.mkdir(parents=True, exist_ok=True)
    return build(db, os.environ["LIMBER_PUBLIC_ORIGIN"])


app = _app_from_environment() if os.environ.get("VERCEL") else None
