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
from starlette.routing import Mount, Route  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from src.portal import access, viewmodels  # noqa: E402
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
               static_dir: Path = STATIC_DIR, trust_proxy: bool = False, secure_cookie: bool = False) -> Starlette:
    db_path = Path(db_path) if db_path else default_db_path()
    key = key or access.load_key(access.default_key_path(db_path))
    origins = {o.rstrip("/") for o in allowed_origins}
    limiter = access.LoginLimiter(clock=clock)

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
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        client = client_of(request)
        with open_store() as store:
            try:
                token = access.sign_in(store, key, code if isinstance(code, str) else None, client, limiter, clock=clock)
                patient_id = access.current_patient(store, token, clock=clock)
            except access.LockedOut as locked:
                return _json({"error": str(locked), "retry_after_seconds": locked.retry_after}, 429,
                             {"Retry-After": str(locked.retry_after)})
            except access.AccessDenied as denied:
                return _json({"error": str(denied)}, 401)
        response = _json({"patient_id": patient_id})
        response.set_cookie(COOKIE, token, max_age=int(access.ABSOLUTE_LIMIT.total_seconds()), path="/",
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

    def health(_request: Request):
        return _json({"ok": True, "pose_assets": pose_assets_present(static_dir)})

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
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/today", today),
        Route("/api/health", health),
        Route("/favicon.ico", lambda _r: FileResponse(static_dir / "favicon.png")),
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
    args = parser.parse_args(argv)

    problem = serve_problem(args.host, args.certfile, args.keyfile, args.insecure_http)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    scheme = "https" if args.certfile else "http"
    origins = [f"{scheme}://{h}:{args.port}" for h in {args.host, "127.0.0.1", "localhost"}] + list(args.public_origin)
    secure = bool(args.certfile) or any(o.startswith("https://") for o in args.public_origin)
    app = create_app(allowed_origins=origins, trust_proxy=args.trust_proxy, secure_cookie=secure)
    if args.host not in LOOPBACK and not args.certfile:
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
