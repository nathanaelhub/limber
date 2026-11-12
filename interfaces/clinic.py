#!/usr/bin/env python3
"""
The Limber clinic app (feature 019): the therapist side, as a stateless web app under /therapist.

It replaces the Streamlit therapist app one slice at a time. It only routes and renders: the rules live in
src/clinic/ and the record's own modules. Every route is registered with the role it needs, and every request
opens one store that is limited to the signed-in person's patients before any handler sees it.

    python interfaces/cli.py clinic                  # http://127.0.0.1:8502/therapist/
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from starlette.applications import Starlette  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import HTMLResponse, RedirectResponse, Response  # noqa: E402
from starlette.routing import Mount, Route  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from interfaces import web_common  # noqa: E402
from interfaces.web_common import json_response  # noqa: E402
from src.clinic import nav, prefs as clinic_prefs, shell, signin  # noqa: E402
from src.portal import access, accounts as ptaccounts, admin  # noqa: E402
from src.ptlog.models import Account, PTLogError  # noqa: E402
from src.ptlog.store import SessionStore, default_db_path  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "clinic_static"
PREFIX = signin.PREFIX


@dataclass
class Ctx:
    """What a handler gets: the request, one store already limited to this person's patients, who they are,
    their display classes, and the JSON body of a write."""
    request: Request
    store: SessionStore
    account: Optional[Account]
    classes: str
    body: Any = None


@dataclass(frozen=True)
class ClinicRoute:
    path: str
    need: str
    methods: tuple
    kind: str            # "page" or "api"
    name: str


def create_app(db_path: Optional[Path] = None, key: Optional[bytes] = None,
               allowed_origins: Iterable[str] = (), clock: Callable[[], datetime] = datetime.now,
               static_dir: Path = STATIC_DIR, trust_proxy: bool = False, secure_cookie: bool = False,
               portal_url: str = "/") -> Starlette:
    db_path = Path(db_path) if db_path else default_db_path()
    key = key or access.load_key(access.default_key_path(db_path))
    origins = {o.rstrip("/") for o in allowed_origins}
    from src.ptlog import backend as record_backend
    # On the hosted demo every instance must count the same failures, so they live in the record (feature 020).
    limiter = access.RecordLoginLimiter(clock=clock) if record_backend.hosted() else access.LoginLimiter(clock=clock)
    registry: List[ClinicRoute] = []
    routes: list = []

    def open_store() -> SessionStore:
        return SessionStore(db_path, clock=clock).open()

    def client_of(request: Request) -> str:
        return access.client_marker(key, web_common.client_address(request, trust_proxy))

    def set_cookie(response: Response, token: str) -> None:
        response.set_cookie(signin.COOKIE, token, max_age=signin.LIFETIME_SECONDS, path=PREFIX, httponly=True,
                            samesite="strict", secure=secure_cookie)

    def html(text: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(text, status_code=status, headers={"Cache-Control": "no-store"})

    def refuse(status: int, kind: str, request: Request, account: Optional[Account], classes: str) -> Response:
        if kind == "api":
            message = "Sign in again to carry on." if status == 401 else "This is not part of your role."
            return json_response({"error": message, "signed_out": status == 401}, status)
        if status == 401:
            target = signin.safe_next(request.url.path + (f"?{request.url.query}" if request.url.query else ""))
            where = f"{PREFIX}/signin" + (f"?next={quote(target, safe='/')}" if target else "")
            return RedirectResponse(where, status_code=303, headers={"Cache-Control": "no-store"})
        return html(shell.refused(account, classes), 403)

    def clinic_route(path: str, handler: Callable[[Ctx], Response], need: str, methods=("GET",),
                     kind: str = "page") -> None:
        """Register a route under /therapist with the role it needs. The only way a route is added."""
        if need not in signin.NEEDS:
            raise ValueError(f"{path}: a route needs one of {', '.join(signin.NEEDS)}")
        full = PREFIX + path

        def run(request: Request, body: Any) -> Response:
            with open_store() as store:
                account = signin.account_for(store, request.cookies.get(signin.COOKIE), clock)
                classes = clinic_prefs.classes(ptaccounts.get_prefs(store, account.id)) if account else ""
                status = signin.require(account, need)
                if status:
                    return refuse(status, kind, request, account, classes)
                ptaccounts.restrict(store, account)          # always: no handler sees an unrestricted store
                try:
                    return handler(Ctx(request, store, account, classes, body))
                except PTLogError as err:
                    return web_common.bad(err)

        async def endpoint(request: Request) -> Response:
            body = None
            if request.method == "POST":
                refused = web_common.check_post(request, origins, page_name="Limber clinic")
                if refused:
                    return refused
                try:
                    body = await request.json()
                except ValueError:
                    return json_response({"error": "Send JSON."}, 400)
            return await run_in_threadpool(run, request, body)

        name = full.strip("/").replace("/", ".") + ":" + ",".join(methods)
        registry.append(ClinicRoute(full, need, tuple(methods), kind, name))
        routes.append(Route(full, endpoint, methods=list(methods), name=name))

    # ------------------------------------------------------------------ sign-in (T006)

    def start(ctx: Ctx) -> Response:
        """The Therapist door lands here with a single-use pass; exchange it and drop it from the address."""
        request = ctx.request
        a_pass = request.query_params.get("pass")
        target = signin.safe_next(request.query_params.get("next"))
        if a_pass:
            token = admin.redeem_pass(ctx.store, a_pass, clock)
            if token is None:
                return RedirectResponse(f"{PREFIX}/signin?expired=1", status_code=303,
                                        headers={"Cache-Control": "no-store"})
            account = admin.signed_in(ctx.store, token, clock)
            response = RedirectResponse(target or nav.home(account), status_code=303,
                                        headers={"Cache-Control": "no-store"})
            set_cookie(response, token)
            return response
        account = signin.account_for(ctx.store, request.cookies.get(signin.COOKIE), clock)
        where = (target or nav.home(account)) if account else f"{PREFIX}/signin"
        return RedirectResponse(where, status_code=303, headers={"Cache-Control": "no-store"})

    def sign_in_page(ctx: Ctx) -> Response:
        if signin.account_for(ctx.store, ctx.request.cookies.get(signin.COOKIE), clock):
            return RedirectResponse(signin.safe_next(ctx.request.query_params.get("next"))
                                    or f"{PREFIX}/", status_code=303)
        note = ("That sign-in link had already been used or was too old. Sign in here instead."
                if ctx.request.query_params.get("expired") else "")
        return html(shell.sign_in(admin.password_is_set(ctx.store), note=note))

    def login(ctx: Ctx) -> Response:
        body = ctx.body if isinstance(ctx.body, dict) else {}
        username, password = body.get("username"), body.get("password")
        try:
            token = admin.sign_in(ctx.store, password if isinstance(password, str) else None,
                                  client_of(ctx.request), limiter, clock=clock,
                                  username=username if isinstance(username, str) else None)
        except admin.NotConfigured as missing:
            return json_response({"error": str(missing)}, 409)
        except access.LockedOut as locked:
            return json_response({"error": str(locked), "retry_after_seconds": locked.retry_after}, 429,
                                 {"Retry-After": str(locked.retry_after)})
        except access.AccessDenied as denied:
            return json_response({"error": str(denied)}, 401)
        account = admin.signed_in(ctx.store, token, clock)
        target = signin.safe_next(body.get("next") if isinstance(body.get("next"), str) else None)
        response = json_response({"redirect": target or nav.home(account)})
        set_cookie(response, token)
        return response

    def logout(ctx: Ctx) -> Response:
        admin.sign_out(ctx.store, ctx.request.cookies.get(signin.COOKIE), client_of(ctx.request))
        response = json_response({"redirect": f"{PREFIX}/signin"})
        response.delete_cookie(signin.COOKIE, path=PREFIX, httponly=True, samesite="strict", secure=secure_cookie)
        return response

    # ------------------------------------------------------------------ me and settings (T007)

    def me(ctx: Ctx) -> Response:
        a = ctx.account
        return json_response({"username": a.username, "display_name": a.display_name, "role": a.role,
                              "is_admin": a.is_admin, "prefs": ptaccounts.get_prefs(ctx.store, a.id),
                              "online": [p.key for p in nav.online(a)]})

    def get_preferences(ctx: Ctx) -> Response:
        return json_response({"prefs": ptaccounts.get_prefs(ctx.store, ctx.account.id)})

    def set_preferences(ctx: Ctx) -> Response:
        saved = ptaccounts.set_prefs(ctx.store, ctx.account.id, ctx.body if isinstance(ctx.body, dict) else None)
        return json_response({"prefs": saved, "classes": clinic_prefs.classes(saved)})

    def settings_page(ctx: Ctx) -> Response:
        return html(shell.settings(ctx.account, ptaccounts.get_prefs(ctx.store, ctx.account.id), ctx.classes))

    def health(ctx: Ctx) -> Response:
        return json_response({"ok": True, "record": "ok", "staff_sign_in": admin.password_is_set(ctx.store)})

    def placeholder(page_info: nav.Page) -> Callable[[Ctx], Response]:
        def show(ctx: Ctx) -> Response:
            return html(shell.not_online(ctx.account, page_info, ctx.classes))
        return show

    clinic_route("/", start, "public")
    clinic_route("/signin", sign_in_page, "public")
    clinic_route("/api/login", login, "public", methods=("POST",), kind="api")
    clinic_route("/api/logout", logout, "any", methods=("POST",), kind="api")
    clinic_route("/api/health", health, "public", kind="api")
    clinic_route("/api/me", me, "any", kind="api")
    clinic_route("/api/me/preferences", get_preferences, "any", kind="api")
    clinic_route("/api/me/preferences", set_preferences, "any", methods=("POST",), kind="api")
    clinic_route("/settings", settings_page, "any")
    for page_info in nav.PAGES:
        if not page_info.online:
            clinic_route(page_info.path, placeholder(page_info), page_info.need)

    async def bare_prefix(request: Request) -> Response:
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"{PREFIX}/{query}", status_code=308, headers={"Cache-Control": "no-store"})

    registry.append(ClinicRoute(PREFIX + "/static", "public", ("GET",), "static", "static"))
    routes.append(Route(PREFIX, bare_prefix))
    routes.append(Mount(PREFIX + "/static", StaticFiles(directory=str(static_dir)), name="static"))

    app = Starlette(routes=routes)
    app.state.registry = registry
    app.state.db_path, app.state.key, app.state.origins, app.state.clock = db_path, key, origins, clock
    app.state.open_store = open_store
    # The clinic needs no camera or microphone yet; slice 7 (live session) widens this for its own page.
    app.add_middleware(web_common.SecurityHeaders, hsts=secure_cookie)
    return app


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Limber clinic app (demo and study use only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--public-origin", action="append", default=[], metavar="URL",
                        help="An address staff use to reach this app, e.g. a tunnel's https URL (repeatable)")
    parser.add_argument("--trust-proxy", action="store_true", help="Read the visitor's address from X-Forwarded-For")
    args = parser.parse_args(argv)
    origins = [f"http://{h}:{args.port}" for h in {args.host, "127.0.0.1", "localhost"}] + list(args.public_origin)
    secure = any(o.startswith("https://") for o in args.public_origin)
    app = create_app(allowed_origins=origins, trust_proxy=args.trust_proxy, secure_cookie=secure)
    if args.host not in ("127.0.0.1", "localhost", "::1") and not secure:
        print("WARNING: serving plain HTTP beyond this machine. Put the clinic app behind HTTPS.")
    print(f"Limber clinic app on http://{args.host}:{args.port}{PREFIX}/  (demo and study use only)")
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
