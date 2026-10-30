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
from src.media.probe import MediaRejected  # noqa: E402
from src.portal import access, accounts, admin, attachments, diary, frames, live, messages, plans, questionnaires, uploads, viewmodels, voice  # noqa: E402
from src.ptlog import origin  # noqa: E402
from src.ptlog.models import PlanArchived, PlanNotFound, PortalError, PTLogError  # noqa: E402
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
    # The camera is used by a guided session and the microphone by a voice note (feature 014); both are
    # allowed only for this origin's own pages, and nothing else is allowed at all.
    "permissions-policy": "camera=(self), microphone=(self), geolocation=()",
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


def _bad(err: Exception) -> JSONResponse:
    """A refused write: 409 when the plan of care is archived (feature 017), otherwise 400."""
    if isinstance(err, PlanArchived):
        return _json({"error": str(err), "archived": True}, 409)
    if isinstance(err, PlanNotFound):
        return _json({"error": str(err)}, 404)
    return _json({"error": str(err)}, 400)


# 4 photos of 15 MB, or one PDF of 20 MB, plus the text and the form's own overhead.
ATTACHMENT_REQUEST_MAX = attachments.MAX_PHOTOS * attachments.PHOTO_MAX + 1024 * 1024


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

    def check_post(request: Request, content_type: str = "application/json") -> Optional[JSONResponse]:
        if (request.headers.get("origin") or "").rstrip("/") not in origins:
            return _json({"error": "This request did not come from the Limber page."}, 403)
        if not request.headers.get("content-type", "").lower().startswith(content_type):
            return _json({"error": f"Send {content_type}."}, 415)
        return None

    media_dir = db_path.parent / "media"

    # ------------------------------------------------------------------ API

    async def login(request: Request):
        refused = check_post(request)
        if refused:
            return refused
        try:
            body = await request.json()
            code = body.get("code") if isinstance(body, dict) else None
            username = body.get("username") if isinstance(body, dict) else None
            password = body.get("password") if isinstance(body, dict) else None
            device = isinstance(body, dict) and body.get("device") is True
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        client = client_of(request)
        with open_store() as store:
            try:
                if username is not None:                      # a patient account (feature 016)
                    device = False
                    token = accounts.patient_sign_in(store, username if isinstance(username, str) else None,
                                                     password if isinstance(password, str) else None, client,
                                                     limiter, clock=clock)
                else:
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
                return _bad(err)

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
                    return _bad(err)
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
                    if body.get("kind") == "questionnaire":
                        # A questionnaire's fields are the items of the assigned instrument, so it is
                        # validated and scored against its definition rather than the entry registry.
                        payload, score = questionnaires.accept(store, patient_id, body.get("data"), now=clock())
                    else:
                        payload, score = entry_rules.validate(body.get("kind"), body.get("data"),
                                                              choices={"item": store.medication_list(patient_id)})
                except PTLogError as err:
                    return _bad(err)
                note = payload.get("note") or ""
                reasons = messages.check_text(note) if note else []
                if reasons and body.get("confirm") is not True:
                    return _json({"error": "This note looks like it contains a " + " and a ".join(reasons) +
                                  ". Limber works without names or contact details. Edit it, or send it anyway.",
                                  "reasons": reasons}, 409)
                recorded_at, adjusted = entry_rules.accept_recorded_at(body.get("recorded_at"), clock())
                before = {e.client_id for e in store.entries(patient_id, body.get("kind"), newest_first=True, limit=50)}
                try:
                    entry = store.entry_add(patient_id, body.get("kind"), payload, score, recorded_at, client_id, phase,
                                            session_id, warned=bool(reasons), time_adjusted=adjusted)
                except PlanArchived as err:
                    return _bad(err)
                return _json(viewmodels.entry_json(entry), 200 if client_id in before else 201)
        return await run_in_threadpool(work)

    def questionnaires_get(request: Request):
        """What this patient has been assigned, what is due, and the items to answer."""
        with open_store() as store:
            patient_id = signed_in(request, store)
            if patient_id is None:
                return _json({"error": "Please sign in."}, 401)
            return _json(questionnaires.view(store, patient_id, now=clock()))

    # ------------------------------------------------------------------ exercise logged without the camera (012)

    async def diary_post(request: Request):
        """A session the patient did without the camera. Always stored as self-reported."""
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
                data = {k: v for k, v in body.items() if k != "confirm"}
                try:
                    session = diary.log(store, patient_id, data, now=clock(), confirm=body.get("confirm") is True)
                except messages.NeedsConfirmation as warn:
                    return _json({"error": str(warn), "reasons": warn.reasons}, 409)
                except PortalError as off:
                    return _json({"error": str(off)}, 403)
                except PTLogError as err:
                    return _bad(err)
                view = viewmodels.today_view(store, patient_id, now=clock())
                return _json({"session_id": session.id, "origin": origin.capture_origin(session),
                              "total_reps": session.total_reps, "summary": diary.summary(session),
                              "week": view["week"], "streak_weeks": view["streak_weeks"],
                              "exercises": view["exercises"]}, 201)
        return await run_in_threadpool(work)

    # ------------------------------------------------------------------ uploads and media (feature 011)

    UPLOAD_KEYS = ("id", "kind", "total_bytes", "chunk_bytes", "total_parts", "received")

    def _upload_json(st):
        return {k: getattr(st, k) for k in UPLOAD_KEYS}

    def _media_json(m):
        return {"id": m.id, "kind": m.kind, "caption": m.caption, "duration": m.duration, "bytes": m.bytes,
                "width": m.width, "height": m.height, "container": m.container, "created_at": m.created_at[:16],
                "reviewed": m.reviewed_at is not None, "deleted": m.deleted_at is not None, "warned": m.warned,
                "type": _mime(m)}

    def _mime(m):
        return {"mp4": "video/mp4", "webm": "video/webm", "m4a": "audio/mp4", "ogg": "audio/ogg"}.get(m.ext, "application/octet-stream")

    def _who(request, store):
        pid = signed_in(request, store)
        if pid is None or store.get_discharge(pid) is not None:
            return None
        return pid

    async def upload_begin(request: Request):
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
                pid = _who(request, store)
                if pid is None:
                    return _json({"error": "Please sign in."}, 401)
                try:
                    st = uploads.begin(store, media_dir, pid, body.get("kind"), body.get("total_bytes"), body.get("sha256"),
                                       chunk_bytes=body.get("chunk_bytes", uploads.CHUNK_BYTES))
                except PTLogError as err:
                    return _bad(err)
                return _json(_upload_json(st), 201)
        return await run_in_threadpool(work)

    def upload_status(request: Request):
        with open_store() as store:
            pid = _who(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            try:
                return _json(_upload_json(uploads.status(store, media_dir, pid, request.path_params["upload_id"])))
            except PTLogError:
                return _json({"error": "Unknown upload."}, 404)

    async def upload_part(request: Request):
        refused = check_post(request, "application/octet-stream")
        if refused:
            return refused
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > uploads.MAX_CHUNK + 1024:
                return _json({"error": "This part is too large."}, 413)

        def work():
            with open_store() as store:
                pid = _who(request, store)
                if pid is None:
                    return _json({"error": "Please sign in."}, 401)
                try:
                    st = uploads.put_part(store, media_dir, pid, request.path_params["upload_id"],
                                          int(request.path_params["index"]), bytes(data))
                except PTLogError as err:
                    return _json({"error": str(err)}, 404 if "Unknown" in str(err) else 400)
                return _json(_upload_json(st))
        return await run_in_threadpool(work)

    async def upload_finish(request: Request):
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
                pid = _who(request, store)
                if pid is None:
                    return _json({"error": "Please sign in."}, 401)
                try:
                    upload_id = request.path_params["upload_id"]
                    open_upload = store.upload_get(upload_id)
                    if open_upload and open_upload.get("kind") == voice.KIND:
                        # A voice note arrives as a message; everything else finishes as a clip.
                        m = voice.finish(store, media_dir, pid, upload_id, confirm=body.get("confirm") is True)
                    else:
                        m = uploads.finish(store, media_dir, pid, upload_id,
                                           caption=body.get("caption") or "", confirm=body.get("confirm") is True)
                except messages.MessagingOff as off:
                    return _json({"error": str(off)}, 403)
                except messages.TooManyMessages as many:
                    return _json({"error": str(many)}, 429)
                except messages.NeedsConfirmation as warn:
                    return _json({"error": str(warn), "reasons": warn.reasons}, 409)
                except MediaRejected as rejected:
                    return _json({"error": str(rejected), "reason": rejected.reason}, 415)
                except PTLogError as err:
                    text = str(err)
                    return _json({"error": text}, 404 if "Unknown" in text else (409 if "missing part" in text else 400))
                return _json(_media_json(m), 201)
        return await run_in_threadpool(work)

    def upload_abandon(request: Request):
        if (request.headers.get("origin") or "").rstrip("/") not in origins:
            return _json({"error": "This request did not come from the Limber page."}, 403)
        with open_store() as store:
            pid = _who(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            try:
                uploads.abandon(store, media_dir, pid, request.path_params["upload_id"])
            except PTLogError:
                return _json({"error": "Unknown upload."}, 404)
            return _json({})

    def media_list(request: Request):
        """Everything this patient sent, clips and voice notes alike; `kind` narrows it."""
        with open_store() as store:
            pid = signed_in(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            wanted = request.query_params.get("kind")
            kind = wanted if wanted in ("clip", voice.KIND) else None
            rows = uploads.list_media(store, pid, kind)
            return _json({"patient_id": pid, "media": [_media_json(m) for m in rows], "notice": uploads.NOTICE})

    def media_file(request: Request):
        with open_store() as store:
            pid = signed_in(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            m = uploads.get_media(store, pid, request.path_params["media_id"])
        if m is None or m.deleted_at is not None:
            return _json({"error": "Not found."}, 404)
        path = uploads.media_path(media_dir, m)
        if not path.is_file():
            return _json({"error": "Not found."}, 404)
        return FileResponse(str(path), media_type=_mime(m), headers={
            "Cache-Control": "private, no-store", "Content-Security-Policy": "sandbox",
            "Content-Disposition": f'inline; filename="{m.kind}.{m.ext}"', "Accept-Ranges": "bytes"})

    def media_delete(request: Request):
        if (request.headers.get("origin") or "").rstrip("/") not in origins:
            return _json({"error": "This request did not come from the Limber page."}, 403)
        with open_store() as store:
            pid = signed_in(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            media_id = request.path_params["media_id"]
            existing = uploads.get_media(store, pid, media_id)
            gone = (voice.delete(store, media_dir, pid, media_id, by="patient")
                    if existing is not None and existing.kind == voice.KIND
                    else uploads.delete_media(store, media_dir, pid, media_id, by="patient"))
            if not gone:
                return _json({"error": "Not found."}, 404)
            return _json({})

    # ------------------------------------------------------------------ plans of care (feature 017)

    def plans_get(request: Request):
        with open_store() as store:
            pid = signed_in(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            return _json({"patient_id": pid, "plans": plans.plans_view(store, pid)})

    def plan_messages_get(request: Request):
        with open_store() as store:
            pid = signed_in(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            try:
                return _json(viewmodels.plan_messages_view(store, pid, request.path_params["plan_id"]))
            except PTLogError as err:
                return _bad(err)

    async def plan_messages_post(request: Request):
        """A message into one plan: JSON for text alone, multipart/form-data with `files` for photos or a PDF."""
        multipart = request.headers.get("content-type", "").lower().startswith("multipart/form-data")
        refused = check_post(request, "multipart/form-data" if multipart else "application/json")
        if refused:
            return refused
        if int(request.headers.get("content-length") or 0) > ATTACHMENT_REQUEST_MAX:
            return _json({"error": "These files are too large to send together."}, 413)
        files = []
        try:
            if multipart:
                form = await request.form(max_files=attachments.MAX_PHOTOS + 1, max_fields=10)
                text, confirm = form.get("text"), form.get("confirm") in ("true", "1", "yes")
                for upload in form.getlist("files"):
                    files.append((upload.content_type or "", await upload.read(attachments.PDF_MAX + 1)))
                await form.close()
            else:
                body = await request.json()
                body = body if isinstance(body, dict) else {}
                text, confirm = body.get("text"), body.get("confirm") is True
        except ValueError:
            return _json({"error": "Send JSON, or a form with the files."}, 400)
        text = text if isinstance(text, str) or text is None else None

        def work():
            with open_store() as store:
                pid = signed_in(request, store)
                if pid is None:
                    return _json({"error": "Please sign in."}, 401)
                try:
                    plan = plans.own_plan(store, pid, request.path_params["plan_id"])
                    sent = messages.send(store, pid, "patient", text, confirm=confirm, plan_id=plan.id,
                                         files=files, media_dir=media_dir)
                    return _json(viewmodels.message_json(sent), 201)
                except messages.NeedsConfirmation as warn:
                    return _json({"error": str(warn), "reasons": warn.reasons}, 409)
                except messages.MessagingOff as off:
                    return _json({"error": str(off)}, 403)
                except messages.TooManyMessages as many:
                    return _json({"error": str(many)}, 429)
                except PTLogError as err:
                    return _bad(err)
        return await run_in_threadpool(work)

    def attachment_file(request: Request):
        with open_store() as store:
            pid = signed_in(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            a = attachments.get(store, pid, request.path_params["attachment_id"])
        if a is None or a.deleted_at is not None:
            return _json({"error": "Not found."}, 404)
        path = attachments.path(media_dir, a)
        if not path.is_file():
            return _json({"error": "Not found."}, 404)
        return FileResponse(str(path), media_type=a.mime, headers={
            "Cache-Control": "private, no-store", "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff", "Content-Disposition": f'inline; filename="{a.kind}.{a.ext}"'})

    def attachment_delete(request: Request):
        if (request.headers.get("origin") or "").rstrip("/") not in origins:
            return _json({"error": "This request did not come from the Limber page."}, 403)
        with open_store() as store:
            pid = signed_in(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            if not attachments.delete(store, media_dir, pid, request.path_params["attachment_id"], by="patient"):
                return _json({"error": "Not found."}, 404)
            return _json({})

    def appointments_get(request: Request):
        with open_store() as store:
            pid = signed_in(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            return _json({"patient_id": pid, "time_zone": str(plans.clinic_zone(store)),
                          "appointments": plans.appointments_view(store, pid)})

    async def appointment_reschedule(request: Request):
        refused = check_post(request)
        if refused:
            return refused
        try:
            body = await request.json()
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        body = body if isinstance(body, dict) else {}
        with open_store() as store:
            pid = signed_in(request, store)
            if pid is None:
                return _json({"error": "Please sign in."}, 401)
            try:
                a = plans.request_reschedule(store, pid, request.path_params["appointment_id"], body.get("note"))
            except PTLogError as err:
                return _bad(err)
            return _json(plans.appointment_json(store, a))

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
        from src.media import transcribe
        return _json({"ok": True, "record": "ok", "pose_assets": pose_assets_present(static_dir),
                      "therapist_sign_in": therapist,
                      # Optional: voice notes arrive and play whether or not this is set up (feature 014).
                      "voice_transcripts": transcribe.available()})

    async def admin_login(request: Request):
        """The therapist door: check the password and hand over to the therapist app with a single-use
        pass. The portal keeps no therapist session and serves no therapist page."""
        refused = check_post(request)
        if refused:
            return refused
        try:
            body = await request.json()
            password = body.get("password") if isinstance(body, dict) else None
            username = body.get("username") if isinstance(body, dict) else None
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        with open_store() as store:
            try:
                who = admin.check_password(store, password if isinstance(password, str) else None, client_of(request),
                                           limiter, username=username if isinstance(username, str) else None)
                a_pass = admin.issue_pass(store, who.id, clock=clock)
            except admin.NotConfigured as missing:
                return _json({"error": str(missing)}, 409)
            except access.LockedOut as locked:
                return _json({"error": str(locked), "retry_after_seconds": locked.retry_after}, 429,
                             {"Retry-After": str(locked.retry_after)})
            except access.AccessDenied as denied:
                return _json({"error": str(denied)}, 401)
        return _json({"redirect": f"{therapist_url.rstrip('/')}/?pass={a_pass}"})

    # ------------------------------------------------------------------ invitations and settings (feature 016)

    def invite_status(request: Request):
        with open_store() as store:
            try:
                inv = accounts.check_invite(store, request.path_params["token"], clock=clock)
            except accounts.InviteInvalid as bad:
                return _json({"error": str(bad)}, 410)
        return _json({"role": inv.role, "admin": inv.make_admin, "expires_at": inv.expires_at})

    async def invite_accept(request: Request):
        """Create the invited account. A patient is signed in here; staff go on to the therapist app."""
        refused = check_post(request)
        if refused:
            return refused
        try:
            body = await request.json()
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        body = body if isinstance(body, dict) else {}
        text = lambda k: body.get(k) if isinstance(body.get(k), str) else None        # noqa: E731
        client = client_of(request)
        with open_store() as store:
            try:
                account = accounts.accept_invite(
                    store, request.path_params["token"], display_name=text("display_name"), username=text("username"),
                    password=text("password"), password_again=text("password_again"),
                    prefs=body.get("prefs") if isinstance(body.get("prefs"), dict) else None, clock=clock)
                if account.role == "patient":
                    token = accounts.patient_sign_in(store, account.username, text("password"), client, limiter,
                                                     clock=clock)
                else:
                    a_pass = admin.issue_pass(store, account.id, clock=clock)
            except accounts.InviteInvalid as bad:
                return _json({"error": str(bad)}, 410)
            except PTLogError as err:
                return _bad(err)
        if account.role != "patient":
            return _json({"redirect": f"{therapist_url.rstrip('/')}/?pass={a_pass}"})
        response = _json({"redirect": "/today", "patient_id": account.patient_id})
        response.set_cookie(COOKIE, token, max_age=int(access.ABSOLUTE_LIMIT.total_seconds()), path="/",
                            httponly=True, samesite="strict", secure=secure_cookie)
        return response

    async def preferences(request: Request):
        with open_store() as store:
            patient_id = signed_in(request, store)
            if patient_id is None:
                return _json({"error": "Please sign in."}, 401)
            if request.method == "GET":
                return _json(accounts.get_patient_prefs(store, patient_id))
        refused = check_post(request)
        if refused:
            return refused
        try:
            body = await request.json()
        except ValueError:
            return _json({"error": "Send JSON."}, 400)
        with open_store() as store:
            patient_id = signed_in(request, store)
            if patient_id is None:
                return _json({"error": "Please sign in."}, 401)
            return _json(accounts.set_patient_prefs(store, patient_id, body if isinstance(body, dict) else {}))

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

    def html_page(name: str, prefs: Optional[dict] = None) -> Response:
        """A page with the reader's accessibility classes already on <html>, so nothing restyles after load."""
        text = (static_dir / f"{name}.html").read_text(encoding="utf-8")
        classes = accounts.css_classes(prefs)
        if classes:
            text = text.replace('<html lang="en">', f'<html lang="en" class="{classes}">', 1)
        return Response(text, media_type="text/html", headers={"Cache-Control": "no-store"})

    def index(_request: Request):
        return html_page("index")

    def invite_page(_request: Request):
        return html_page("invite")

    def inner_page(name: str):
        def page(request: Request):
            with open_store() as store:
                patient_id = signed_in(request, store)
                if patient_id is None:
                    return RedirectResponse("/", status_code=303)
                prefs = accounts.get_patient_prefs(store, patient_id)
            return html_page(name, prefs)
        return page

    routes = [
        Route("/", index),
        Route("/today", inner_page("today")),
        Route("/session", inner_page("session")),
        Route("/progress", inner_page("progress")),
        Route("/messages", inner_page("messages")),
        Route("/checkin", inner_page("checkin")),
        Route("/clip", inner_page("clip")),
        Route("/diary", inner_page("diary")),
        Route("/log", inner_page("log")),
        Route("/questionnaire", inner_page("questionnaire")),
        Route("/voice", inner_page("voice")),
        Route("/settings", inner_page("settings")),
        Route("/invite/{token}", invite_page),
        Route("/api/invites/{token}", invite_status, methods=["GET"]),
        Route("/api/invites/{token}", invite_accept, methods=["POST"]),
        Route("/api/me/preferences", preferences, methods=["GET", "POST"]),
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/today", today),
        Route("/api/progress", progress),
        Route("/api/messages", messages_get, methods=["GET"]),
        Route("/api/messages", messages_post, methods=["POST"]),
        Route("/api/plans", plans_get, methods=["GET"]),
        Route("/api/plans/{plan_id:int}/messages", plan_messages_get, methods=["GET"]),
        Route("/api/plans/{plan_id:int}/messages", plan_messages_post, methods=["POST"]),
        Route("/api/attachments/{attachment_id}", attachment_file, methods=["GET"]),
        Route("/api/attachments/{attachment_id}", attachment_delete, methods=["DELETE"]),
        Route("/api/appointments", appointments_get, methods=["GET"]),
        Route("/api/appointments/{appointment_id:int}/reschedule", appointment_reschedule, methods=["POST"]),
        Route("/api/entries", entries_get, methods=["GET"]),
        Route("/api/entries", entries_post, methods=["POST"]),
        Route("/api/diary", diary_post, methods=["POST"]),
        Route("/api/questionnaires", questionnaires_get),
        Route("/manifest.webmanifest", manifest),
        Route("/api/uploads", upload_begin, methods=["POST"]),
        Route("/api/uploads/{upload_id}", upload_status, methods=["GET"]),
        Route("/api/uploads/{upload_id}", upload_abandon, methods=["DELETE"]),
        Route("/api/uploads/{upload_id}/parts/{index:int}", upload_part, methods=["PUT"]),
        Route("/api/uploads/{upload_id}/finish", upload_finish, methods=["POST"]),
        Route("/api/media", media_list, methods=["GET"]),
        Route("/api/media/{media_id}", media_file, methods=["GET"]),
        Route("/api/media/{media_id}", media_delete, methods=["DELETE"]),
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
