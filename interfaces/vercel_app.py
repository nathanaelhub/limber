"""
The patient portal as a Vercel Python function (feature 020, slice D). Vercel loads `app` from the generated
`index.py` (see deploy/vercel/). Every hosted setting is required; a missing one stops the function from starting
with a plain reason, rather than running half-configured.

The therapist side is the 019 clinic app, mounted at /therapist beside the portal in this one function. The two stay
separate apps with their own routes, cookies and static files (constitution 1.5.1); only the address is shared.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

REQUIRED = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "LIMBER_DEMO", "LIMBER_PUBLIC_ORIGIN", "PTASSIST_PORTAL_KEY",
            "LIMBER_R2_ACCOUNT_ID", "LIMBER_R2_BUCKET", "LIMBER_R2_ACCESS_KEY_ID", "LIMBER_R2_SECRET_ACCESS_KEY")

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


# Vercel ends a function's connection at 300 s (measured 2026-11-12: cut at 300-310 s, close code 1006). Live
# sessions end each connection between reps after this long (at most 15 s more) and the page resumes them.
SEGMENT_SECONDS = 270


class PrefixRouter:
    """Sends /therapist and everything under it to the clinic app, and every other request to the portal."""

    def __init__(self, prefix: str, inner, outer):
        self.prefix, self.inner, self.outer = prefix, inner, outer

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                return await self.inner(scope, receive, send)
        return await self.outer(scope, receive, send)


def build(db_path: Path, origin: str, key: Optional[bytes] = None, ws_segment_seconds: float = SEGMENT_SECONDS):
    from starlette.responses import JSONResponse
    from interfaces import clinic
    from interfaces.patient_portal import create_app
    from src.ptlog import backend
    origin = origin.rstrip("/")
    secure = origin.startswith("https://")
    portal = create_app(db_path=db_path, key=key, allowed_origins=[origin], trust_proxy=True, secure_cookie=secure,
                        therapist_url=f"{origin}/therapist", ws_segment_seconds=ws_segment_seconds)
    therapist = clinic.create_app(db_path=db_path, key=key, allowed_origins=[origin], trust_proxy=True,
                                  secure_cookie=secure)

    async def demo_unavailable(_request, exc):
        # A visit while the demo is being reset, or a record that isn't the demo: a plain answer, not an error page.
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Retry-After": "120"})

    for app in (portal, therapist):
        app.add_exception_handler(backend.HostedRecordRefused, demo_unavailable)
    router = PrefixRouter("/therapist", therapist, portal)
    router.portal, router.clinic = portal, therapist
    return router


def _app_from_environment():
    check_settings(os.environ)
    use_clinic_time(os.environ)
    db = Path(os.environ.get("PTASSIST_DB", "/tmp/limber/replica.db"))
    db.parent.mkdir(parents=True, exist_ok=True)
    segment = float(os.environ.get("LIMBER_WS_SEGMENT_SECONDS") or SEGMENT_SECONDS)
    return build(db, os.environ["LIMBER_PUBLIC_ORIGIN"], ws_segment_seconds=segment)


app = _app_from_environment() if os.environ.get("VERCEL") else None
