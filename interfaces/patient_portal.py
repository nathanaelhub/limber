#!/usr/bin/env python3
"""
PT Assist patient portal (feature 007): the one patient-facing interface.

A separate launch from the therapist app, with no therapist pages. It only routes and renders:
access rules live in src/portal/access.py, what a patient sees in src/portal/viewmodels.py.

    python interfaces/cli.py portal serve            # http://127.0.0.1:8600

For demo and consented study participants only. Camera video never reaches this service: the
patient's browser finds the body points and sends only those numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from starlette.routing import Mount, Route, WebSocketRoute  # noqa: E402
from starlette.websockets import WebSocket, WebSocketDisconnect  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from src.deploy import preflight  # noqa: E402
from src.portal import pwa  # noqa: E402
from src.ptlog import entries as entry_rules  # noqa: E402
from src.portal import access, admin, frames, live, messages, viewmodels  # noqa: E402
from src.ptlog.models import PTLogError  # noqa: E402
from src.ptlog.store import SessionStore, default_db_path  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "portal_static"
COOKIE = "ptassist_patient"
LOOPBACK = ("127.0.0.1", "localhost", "::1")

CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data: blob:; media-src 'self' blob:; worker-src 'self' blob:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SECURITY_HEADERS = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(self), microphone=(), geolocation=()",
    "cross-origin-opener-policy": "same-origin",
}


class SecurityHeaders:
    """Adds the security headers to every HTTP response, static files included."""

    def __init__(self, app, hsts: bool = False):
        self.app = app
        self.headers = dict(SECURITY_HEADERS)
        if hsts:
            self.headers["strict-transport-security"] = "max-age=31536000"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k.encode(), v.encode()) for k, v in self.headers.items() if k.encode() not in present]
                message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _json(data, status: int = 200, headers: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store", **(headers or {})})


def pose_assets_present(static_dir: Path) -> bool:
    return (static_dir / "vendor" / "lightning" / "model.json").is_file()


def create_app(db_path: Optional[Path] = None, key: Optional[bytes] = None,
               allowed_origins: Iterable[str] = (), clock: Callable[[], datetime] = datetime.now,
               static_dir: Path = STATIC_DIR, trust_proxy: bool = False, secure_cookie: bool = False,
               therapist_url: str = "http://localhost:8501", frame_rate_cap: int = 20,
               max_live_sessions: int = 8) -> Starlette:
    db_path = Path(db_path) if db_path else default_db_path()
    key = key or access.load_key(access.default_key_path(db_path))
    origins = {o.rstrip("/") for o in allowed_origins}
    limiter = access.LoginLimiter(clock=clock)
    registry = live.LiveRegistry(limit=max_live_sessions)

    def open_store() -> SessionStore:
        return SessionStore(db_path, clock=clock).open()

    def client_of(request: Request) -> str:
        address = request.client.host if request.client else "unknown"
        if trust_proxy:
            forwarded = request.headers.get("x-forwarded-for", "")
            address = forwarded.split(",")[0].strip() or address
        return access.client_marker(key, address)

    def signed_in(request: Request, store: SessionStore) -> Optional[str]:
        return access.current_patient(store, request.cookies.get(COOKIE), clock=clock)

    def check_post(request: Request) -> Optional[JSONResponse]:
        if (request.headers.get("origin") or "").rstrip("/") not in origins:
            return _json({"error": "This request did not come from the Limber page."}, 403)
        if not request.headers.get("content-type", "").lower().startswith("application/json"):
            return _json({"error": "Send JSON."}, 415)
        return None

    # ------------------------------------------------------------------ API

    async def login(request: Request):
        refused = check_post(request)
        if refused:
            return refused
        try:
            body = await request.json()
            code = body.get("code") if isinstance(body, dict) else None
            device = isinstance(body, dict) and body.get("device") is True
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        client = client_of(request)
        with open_store() as store:
            try:
                token = access.sign_in(store, key, code if isinstance(code, str) else None, client, limiter,
                                       clock=clock, device=device)
                patient_id = access.current_patient(store, token, clock=clock)
            except access.LockedOut as locked:
                return _json({"error": str(locked), "retry_after_seconds": locked.retry_after}, 429,
                             {"Retry-After": str(locked.retry_after)})
            except access.AccessDenied as denied:
                return _json({"error": str(denied)}, 401)
        response = _json({"patient_id": patient_id})
        lifetime = access.DEVICE_LIMIT if device else access.ABSOLUTE_LIMIT
        response.set_cookie(COOKIE, token, max_age=int(lifetime.total_seconds()), path="/",
                            httponly=True, samesite="strict", secure=secure_cookie)
        return response

    def logout(request: Request):
        refused = check_post(request)
        if refused:
            return refused
        with open_store() as store:
            access.sign_out(store, request.cookies.get(COOKIE), client_of(request))
        response = _json({})
        response.delete_cookie(COOKIE, path="/")
        return response

    def today(request: Request):
        with open_store() as store:
            patient_id = signed_in(request, store)          # the only source of the patient's identity
            if patient_id is None:
                return _json({"error": "Please sign in."}, 401)
            try:
                return _json(viewmodels.today_view(store, patient_id, now=clock()))
            except PTLogError as err:
                return _json({"error": str(err)}, 400)

    def progress(request: Request):
        with open_store() as store:
            patient_id = signed_in(request, store)
            if patient_id is None:
                return _json({"error": "Please sign in."}, 401)
            return _json(viewmodels.progress_view(store, patient_id, now=clock()))

    def messages_get(request: Request):
        with open_store() as store:
            patient_id = signed_in(request, store)
            if patient_id is None:
                return _json({"error": "Please sign in."}, 401)
            return _json(viewmodels.messages_view(store, patient_id))

    async def messages_post(request: Request):
        refused = check_post(request)
        if refused:
            return refused
        try:
            body = await request.json()
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        body = body if isinstance(body, dict) else {}

        def work():
            with open_store() as store:
                patient_id = signed_in(request, store)
                if patient_id is None:
                    return _json({"error": "Please sign in."}, 401)
                try:
                    sent = messages.send(store, patient_id, "patient", body.get("text"), confirm=body.get("confirm") is True)
                    return _json(viewmodels.message_json(sent), 201)
                except messages.NeedsConfirmation as warn:
                    return _json({"error": str(warn), "reasons": warn.reasons}, 409)
                except messages.MessagingOff as off:
                    return _json({"error": str(off)}, 403)
                except messages.TooManyMessages as many:
                    return _json({"error": str(many)}, 429)
                except PTLogError as err:
                    return _json({"error": str(err)}, 400)
        return await run_in_threadpool(work)

    def entries_get(request: Request):
        with open_store() as store:
            patient_id = signed_in(request, store)
            if patient_id is None:
                return _json({"error": "Please sign in."}, 401)
            return _json(viewmodels.entries_view(store, patient_id))

    async def entries_post(request: Request):
        """A patient-reported entry (check-in). Idempotent on client_id, so an offline queue may resend."""
        refused = check_post(request)
        if refused:
            return refused
        try:
            body = await request.json()
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        body = body if isinstance(body, dict) else {}

        def work():
            with open_store() as store:
                patient_id = signed_in(request, store)
                if patient_id is None or store.get_discharge(patient_id) is not None:
                    return _json({"error": "Please sign in."}, 401)
                client_id = body.get("client_id")
                if not isinstance(client_id, str) or not 1 <= len(client_id) <= 64:
                    return _json({"error": "A check-in needs a client id."}, 400)
                phase = body.get("phase") or "standalone"
                if phase not in ("before", "after", "standalone"):
                    return _json({"error": "phase must be before, after, or standalone."}, 400)
                session_id = body.get("session_id")
                if session_id is not None:
                    if not isinstance(session_id, int) or isinstance(session_id, bool):
                        return _json({"error": "session_id must be a number."}, 400)
                    try:
                        if store.load_session(session_id).patient_id != patient_id:
                            raise PTLogError("not yours")
                    except PTLogError:
                        return _json({"error": "That session is not yours."}, 400)
                try:
                    payload, score = entry_rules.validate(body.get("kind"), body.get("data"))
                except PTLogError as err:
                    return _json({"error": str(err)}, 400)
                note = payload.get("note") or ""
                reasons = messages.check_text(note) if note else []
                if reasons and body.get("confirm") is not True:
                    return _json({"error": "This note looks like it contains a " + " and a ".join(reasons) +
                                  ". Limber works without names or contact details. Edit it, or send it anyway.",
                                  "reasons": reasons}, 409)
                recorded_at, adjusted = entry_rules.accept_recorded_at(body.get("recorded_at"), clock())
                before = {e.client_id for e in store.entries(patient_id, body.get("kind"), newest_first=True, limit=50)}
                entry = store.entry_add(patient_id, body.get("kind"), payload, score, recorded_at, client_id, phase,
                                        session_id, warned=bool(reasons), time_adjusted=adjusted)
                return _json(viewmodels.entry_json(entry), 200 if client_id in before else 201)
        return await run_in_threadpool(work)

    def manifest(_request: Request):
        return _json(pwa.manifest(), headers={"Content-Type": "application/manifest+json"})

    _precache = pwa.precache(static_dir)
    _sw = pwa.service_worker(_precache)

    def service_worker(_request: Request):
        return Response(_sw, media_type="application/javascript", headers={"Cache-Control": "no-store"})

    def health(_request: Request):
        """Used by the proxy and the uptime check: proves the record can be read and written."""
        if preflight._record_writable(db_path) is not None:
            return _json({"ok": False, "record": "unavailable"}, 503)
        with open_store() as store:
            therapist = admin.password_is_set(store)
        return _json({"ok": True, "record": "ok", "pose_assets": pose_assets_present(static_dir),
                      "therapist_sign_in": therapist})

    async def admin_login(request: Request):
        """The therapist door: check the password and hand over to the therapist app with a single-use
        pass. The portal keeps no therapist session and serves no therapist page."""
        refused = check_post(request)
        if refused:
            return refused
        try:
            body = await request.json()
            password = body.get("password") if isinstance(body, dict) else None
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        with open_store() as store:
            try:
                admin.check_password(store, password if isinstance(password, str) else None, client_of(request), limiter)
                a_pass = admin.issue_pass(store, clock=clock)
            except admin.NotConfigured as missing:
                return _json({"error": str(missing)}, 409)
            except access.LockedOut as locked:
                return _json({"error": str(locked), "retry_after_seconds": locked.retry_after}, 429,
                             {"Retry-After": str(locked.retry_after)})
            except access.AccessDenied as denied:
                return _json({"error": str(denied)}, 401)
        return _json({"redirect": f"{therapist_url.rstrip('/')}/?pass={a_pass}"})

    # ------------------------------------------------------------------ guided session

    STATE_KEYS = ("exercise", "index", "rep_count", "phase", "form_status", "form_messages", "feedback",
                  "set_complete", "seen", "notice", "target_reps")
    IDLE_SECONDS, MAX_SECONDS, BAD_LIMIT, RECHECK_EVERY = 60, 60 * 60, 10, 15

    def _patient_for(token):
        with open_store() as store:
            return access.current_patient(store, token, clock=clock)

    def _audit(event, patient_id, detail=None):
        with open_store() as store:
            store.portal_audit_add(event, patient_id, None, detail)

    async def session_socket(ws: WebSocket):
        """The patient's browser sends body points; the service answers with what the engine sees."""
        token = ws.cookies.get(COOKIE)
        origin_ok = (ws.headers.get("origin") or "").rstrip("/") in origins
        patient_id = await run_in_threadpool(_patient_for, token) if origin_ok else None
        if patient_id is None:                                  # refused before the connection is accepted
            await ws.close(code=1008)
            return
        await ws.accept()
        session, bad, accepted = None, 0, 0
        last_sent, last_sent_at, started_at = None, 0.0, asyncio.get_running_loop().time()

        async def send_state(state, force=False):
            nonlocal last_sent, last_sent_at
            if state is None:
                return
            now = asyncio.get_running_loop().time()
            key = tuple(str(state.get(k)) for k in STATE_KEYS)
            if force or key != last_sent or now - last_sent_at >= 0.2:
                last_sent, last_sent_at = key, now
                await ws.send_json(state)

        async def close_with(reason, code=1008):
            if session is not None:
                await run_in_threadpool(session.interrupt, reason)
            await ws.close(code=code)

        try:
            while True:
                try:
                    text = await asyncio.wait_for(ws.receive_text(), timeout=IDLE_SECONDS)
                except asyncio.TimeoutError:
                    if session is not None:
                        await ws.send_json(await run_in_threadpool(session.stop))
                    await ws.close(code=1000)
                    return
                try:
                    message = frames.parse(text)
                    kind = message["type"]
                    if kind == "start":
                        if session is None:
                            try:
                                session = await run_in_threadpool(
                                    lambda: live.PortalLiveSession.start(db_path, patient_id, registry,
                                                                         pose_model=message.get("pose_model") or live.DEFAULT_POSE_MODEL,
                                                                         clock=clock, rate_cap=frame_rate_cap))
                            except live.LiveRefused as refused:
                                await run_in_threadpool(_audit, "live_refused", patient_id, refused.reason)
                                await ws.send_json({"type": "refused", "reason": refused.reason, "message": str(refused)})
                                await ws.close(code=1000)
                                return
                        await send_state(session.state(), force=True)
                    elif session is None:
                        raise frames.FrameError("start first")
                    elif kind == "frame":
                        state = await run_in_threadpool(session.handle_frame, message)
                        if state is not None:
                            accepted += 1
                            await send_state(state)
                            if accepted % RECHECK_EVERY == 0 and await run_in_threadpool(_patient_for, token) is None:
                                await close_with("access_revoked")
                                return
                    elif kind == "next":
                        await send_state(await run_in_threadpool(session.next), force=True)
                    elif kind == "stop":
                        await ws.send_json(await run_in_threadpool(session.stop))
                        await ws.close(code=1000)
                        return
                except frames.FrameError:
                    bad += 1
                    if bad >= BAD_LIMIT:
                        await run_in_threadpool(_audit, "live_refused", patient_id, "bad_frames")
                        await close_with("bad_frames")
                        return
                if session is not None and asyncio.get_running_loop().time() - started_at > MAX_SECONDS:
                    await ws.send_json(await run_in_threadpool(session.stop))
                    await ws.close(code=1000)
                    return
        except WebSocketDisconnect:
            if session is not None:
                await run_in_threadpool(session.interrupt, "portal_disconnected")

    # ------------------------------------------------------------------ pages

    def index(_request: Request):
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-store"})

    def inner_page(name: str):
        def page(request: Request):
            with open_store() as store:
                if signed_in(request, store) is None:
                    return RedirectResponse("/", status_code=303)
            return FileResponse(static_dir / f"{name}.html", headers={"Cache-Control": "no-store"})
        return page

    routes = [
        Route("/", index),
        Route("/today", inner_page("today")),
        Route("/session", inner_page("session")),
        Route("/progress", inner_page("progress")),
        Route("/messages", inner_page("messages")),
        Route("/checkin", inner_page("checkin")),
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/today", today),
        Route("/api/progress", progress),
        Route("/api/messages", messages_get, methods=["GET"]),
        Route("/api/messages", messages_post, methods=["POST"]),
        Route("/api/entries", entries_get, methods=["GET"]),
        Route("/api/entries", entries_post, methods=["POST"]),
        Route("/manifest.webmanifest", manifest),
        Route("/sw.js", service_worker),
        Route("/api/health", health),
        Route("/api/admin/login", admin_login, methods=["POST"]),
        Route("/favicon.ico", lambda _r: FileResponse(static_dir / "favicon.png")),
        WebSocketRoute("/ws/session", session_socket),
        Mount("/static", StaticFiles(directory=str(static_dir)), name="static"),
    ]
    app = Starlette(routes=routes)
    app.state.db_path, app.state.key, app.state.origins, app.state.clock = db_path, key, origins, clock
    app.state.open_store, app.state.signed_in_token = open_store, lambda token, store: access.current_patient(
        store, token, clock=clock)
    app.add_middleware(SecurityHeaders, hsts=secure_cookie)
    return app


def serve_problem(host: str, certfile: Optional[str], keyfile: Optional[str], insecure_http: bool) -> Optional[str]:
    """Why the service must not start with these options, or None. Pure, so it is testable."""
    if bool(certfile) != bool(keyfile):
        return "Give both --certfile and --keyfile, or neither."
    if host not in LOOPBACK and not certfile and not insecure_http:
        return (f"Refusing to listen on {host} without a secure connection: browsers only allow the camera on "
                "HTTPS or localhost, and sign-in codes would travel in the clear. Use a temporary HTTPS tunnel to "
                "127.0.0.1 with --public-origin, or pass --certfile and --keyfile, or --insecure-http to override.")
    return None


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Limber patient portal (demo and study use only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8600)
    parser.add_argument("--public-origin", action="append", default=[], metavar="URL",
                        help="An address patients use to reach this service, e.g. a tunnel's https URL (repeatable)")
    parser.add_argument("--trust-proxy", action="store_true", help="Read the visitor's address from X-Forwarded-For")
    parser.add_argument("--certfile")
    parser.add_argument("--keyfile")
    parser.add_argument("--insecure-http", action="store_true")
    parser.add_argument("--therapist-url", default="http://localhost:8501",
                        help="Where the therapist app runs; the front page's therapist door hands over to it")
    args = parser.parse_args(argv)

    problem = serve_problem(args.host, args.certfile, args.keyfile, args.insecure_http)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    scheme = "https" if args.certfile else "http"
    origins = [f"{scheme}://{h}:{args.port}" for h in {args.host, "127.0.0.1", "localhost"}] + list(args.public_origin)
    secure = bool(args.certfile) or any(o.startswith("https://") for o in args.public_origin)
    app = create_app(allowed_origins=origins, trust_proxy=args.trust_proxy, secure_cookie=secure,
                     therapist_url=args.therapist_url)
    behind_https_proxy = any(o.startswith("https://") for o in args.public_origin)
    if args.host not in LOOPBACK and not args.certfile and not behind_https_proxy:
        print("WARNING: serving plain HTTP beyond this machine. Cameras will not work in patients' browsers.")
    if not pose_assets_present(STATIC_DIR):
        print("Pose assets are not installed; sessions will say setup is incomplete. Run: "
              "python scripts/fetch_portal_assets.py")
    print(f"Limber patient portal on {scheme}://{args.host}:{args.port}  (demo and study use only)")
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, ssl_certfile=args.certfile, ssl_keyfile=args.keyfile,
                log_level="warning", ws_max_size=4096)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
