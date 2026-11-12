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
from datetime import date, datetime
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
from src.clinic import inbox as clinic_inbox, inbox_view  # noqa: E402
from src.clinic import assist_view, patients as clinic_patients, patients_view  # noqa: E402
from src.clinic import people as clinic_people, schedule as clinic_schedule, schedule_people_view  # noqa: E402
from src.assist import assistant, config as ai_config  # noqa: E402
from src.clinic.inbox import NotYours  # noqa: E402
from src.media import files as media_files  # noqa: E402
from src.portal import messages as ptmessages, plans as ptplans  # noqa: E402
from src.portal import access, accounts as ptaccounts, admin, attachments  # noqa: E402
from src.ptlog.models import Account, PatientNotFoundError, PlanNotFound, PTLogError  # noqa: E402
from src.ptlog.store import SessionStore, default_db_path  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "clinic_static"
PREFIX = signin.PREFIX


# 4 photos of 15 MB, or one PDF of 20 MB, plus the text and the form's own overhead.
FILES_REQUEST_MAX = attachments.MAX_PHOTOS * attachments.PHOTO_MAX + 1024 * 1024


async def _form_body(request: Request) -> dict:
    """A reply with photos or a PDF sent as a form (local installs; the hosted demo uploads straight to its bucket)."""
    form = await request.form(max_files=attachments.MAX_PHOTOS + 1, max_fields=10)
    body = {k: form.get(k) for k in ("text", "plan_id")}
    body["confirm"] = form.get("confirm") in ("true", "1", "yes")
    body["from_draft"] = form.get("from_draft") in ("true", "1", "yes")
    body["files"] = [(u.content_type or "", await u.read(attachments.PDF_MAX + 1)) for u in form.getlist("files")]
    await form.close()
    return body


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
               portal_url: str = "http://localhost:8600") -> Starlette:
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

    def not_found(kind: str, account: Optional[Account], classes: str) -> Response:
        if kind == "page":
            return html(shell.not_found(account, classes), 404)
        return json_response({"error": "Not found."}, 404)

    def clinic_route(path: str, handler: Callable[[Ctx], Response], need: str, methods=("GET",),
                     kind: str = "page", files: bool = False) -> None:
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
                except (NotYours, PatientNotFoundError, PlanNotFound):
                    # Another therapist's patient, plan, message, visit or file is answered as if it didn't exist.
                    return not_found(kind, account, classes)
                except PTLogError as err:
                    return web_common.bad(err)

        async def endpoint(request: Request) -> Response:
            body = None
            if request.method == "POST":
                multipart = files and request.headers.get("content-type", "").lower().startswith("multipart/form-data")
                refused = web_common.check_post(request, origins, "multipart/form-data" if multipart
                                                else "application/json", page_name="Limber clinic")
                if refused:
                    return refused
                if multipart:
                    if int(request.headers.get("content-length") or 0) > FILES_REQUEST_MAX:
                        return json_response({"error": "These files are too large to send together."}, 413)
                    try:
                        body = await _form_body(request)
                    except ValueError:
                        return json_response({"error": "Send a form with the files."}, 400)
                else:
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

    # ------------------------------------------------------------------ Inbox (slice 2)

    media_dir = db_path.parent / "media"

    def inbox_side(store: SessionStore, current=None) -> tuple:
        items = clinic_inbox.needs_you(store)
        return items, inbox_view.side(items, clinic_inbox.conversations(store), clock(), current)

    def inbox_page(ctx: Ctx) -> Response:
        items, side_html = inbox_side(ctx.store)
        pane = inbox_view.empty_pane() if items else inbox_view.all_clear_pane()
        return html(inbox_view.page(ctx.account, ctx.classes, side_html, pane))

    def conversation_page(ctx: Ctx) -> Response:
        store, pid = ctx.store, clinic_inbox.own_patient(ctx.store, ctx.request.path_params["patient_id"])
        wanted = ctx.request.query_params.get("plan")
        plan = clinic_inbox.own_plan(store, pid, wanted) if wanted else clinic_inbox.default_plan(store, pid)
        plans = store.plans(pid)
        messages = clinic_inbox.thread(store, pid, plan)             # never marks read (FR-007)
        from src.media import transcribe
        voices = {m.media_id: (store.media_get(m.media_id), store.transcription_for(m.media_id))
                  for m in messages if m.media_id}
        state = clinic_inbox.reply_state(store, pid, plan)
        flagged, words = clinic_inbox.withheld(store, pid, plan.id if plan else None)
        requests = [(a, ptplans.appointment_json(store, a)) for a in ptplans.reschedule_requests(store)
                    if a.patient_id == pid and (plan is None or a.plan_id == plan.id)]
        bits = []
        if plan:
            bits.append(f"Started {datetime.fromisoformat(plan.start_date[:10]).strftime('%-d %b %Y')}")
        upcoming = [v for v in ptplans.appointments_view(store, pid) if v["state"] == "upcoming"]
        if upcoming:
            bits.append("Next visit " + datetime.fromisoformat(upcoming[0]["starts_local"]).strftime("%a %-d %b, %H:%M"))
        pane = inbox_view.conversation(
            pid, plan, plans, store.messages_unread_by_plan("patient", pid), messages, clock(), state,
            ptmessages.is_enabled(store, pid), clinic_inbox.assist_on(store, pid), flagged, words, voices,
            transcribe.available(), " · ".join(bits) or "No plan of care yet", requests)
        _, side_html = inbox_side(store, (pid, plan.id if plan else None))
        return html(inbox_view.page(ctx.account, ctx.classes, side_html, pane, title=f"Inbox · {pid}"))

    def _patient_plan(ctx: Ctx):
        pid = clinic_inbox.own_patient(ctx.store, ctx.request.path_params["patient_id"])
        body = ctx.body if isinstance(ctx.body, dict) else {}
        return pid, clinic_inbox.own_plan(ctx.store, pid, body.get("plan_id")), body

    def mark_read(ctx: Ctx) -> Response:
        pid, plan, _ = _patient_plan(ctx)
        clinic_inbox.mark_read(ctx.store, pid, plan)
        return json_response({"ok": True})

    def reply(ctx: Ctx) -> Response:
        pid, plan, body = _patient_plan(ctx)
        text = body.get("text") if isinstance(body.get("text"), str) or body.get("text") is None else None
        uploaded = body.get("uploaded")
        sending = body.get("files") or []
        try:
            if uploaded is not None:
                sending = attachments.take_uploaded(media_dir, pid, uploaded)
            try:
                sent = clinic_inbox.send(ctx.store, pid, plan, text, confirm=body.get("confirm") is True,
                                         files=sending, from_draft=body.get("from_draft") is True,
                                         media_dir=media_dir)
            finally:
                if uploaded is not None:
                    attachments.discard_uploaded(media_dir, pid, uploaded)
        except ptmessages.NeedsConfirmation as warn:
            return json_response({"error": str(warn), "reasons": warn.reasons, "needs_confirm": True}, 409)
        except ptmessages.MessagingOff as off:
            return json_response({"error": str(off)}, 403)
        return json_response({"id": sent.id}, 201)

    def upload_links(ctx: Ctx) -> Response:
        pid = clinic_inbox.own_patient(ctx.store, ctx.request.path_params["patient_id"])
        declared = (ctx.body or {}).get("files") if isinstance(ctx.body, dict) else None
        if not isinstance(declared, list) or not all(isinstance(f, dict) for f in declared):
            return json_response({"error": "Say which files will be sent."}, 400)
        fs = media_files.at(media_dir)
        if not fs.remote:
            return json_response({"error": "Files are sent with the reply on this installation."}, 501)
        types = attachments.check_declared([(f.get("type"), f.get("size")) for f in declared])
        links = []
        for mime in types:
            key = attachments.upload_key(pid, mime)
            links.append({"key": key, "url": fs.signed_put(key, mime), "type": mime})
        return json_response({"uploads": links})

    def draft(ctx: Ctx) -> Response:
        """An AI draft for the reply box. It is never sent: the therapist edits it and presses Send."""
        pid, plan, _ = _patient_plan(ctx)
        if not clinic_inbox.assist_on(ctx.store, pid):
            return json_response({"state": "off", "notice": clinic_inbox.DRAFT_NOTICES["off"]})
        from src.assist import assistant
        result = assistant.draft_reply(ctx.store, pid, plan.id if plan else None, account_id=ctx.account.id)
        if result.state == "ok":
            return json_response({"state": "ok", "text": result.text})
        return json_response({"state": result.state, "notice": clinic_inbox.DRAFT_NOTICES.get(
            result.state, clinic_inbox.DRAFT_NOTICES["unavailable"])})

    def handled(ctx: Ctx) -> Response:
        pid, plan, _ = _patient_plan(ctx)
        from src.assist import assistant
        flagged, _words = clinic_inbox.withheld(ctx.store, pid, plan.id if plan else None)
        for m in flagged:
            assistant.mark_handled(ctx.store, m.id, ctx.account.id)
        return json_response({"handled": len(flagged)})

    def messaging(ctx: Ctx) -> Response:
        pid = clinic_inbox.own_patient(ctx.store, ctx.request.path_params["patient_id"])
        on = isinstance(ctx.body, dict) and ctx.body.get("enabled") is True
        ptmessages.set_enabled(ctx.store, pid, on)
        return json_response({"enabled": on})

    def remove_message(ctx: Ctx) -> Response:
        pid = ctx.request.path_params["patient_id"]
        m = clinic_inbox.own_message(ctx.store, pid, ctx.request.path_params["message_id"])
        plan = ctx.store.plan_get(m.plan_id) if m.plan_id is not None else None
        if plan is not None and plan.read_only:
            return json_response({"error": "This plan is archived, so its conversation is read-only.",
                                  "archived": True}, 409)
        ptmessages.remove(ctx.store, m.id)
        return json_response({"removed": m.id})

    def voice_action(action: str) -> Callable[[Ctx], Response]:
        def act(ctx: Ctx) -> Response:
            pid = clinic_inbox.own_patient(ctx.store, ctx.request.path_params["patient_id"])
            media = clinic_inbox.own_voice(ctx.store, pid, ctx.request.path_params["media_id"])
            from src.portal import uploads, voice
            if action == "heard":
                uploads.mark_reviewed(ctx.store, media.id)
            elif action == "delete":
                voice.delete(ctx.store, media_dir, pid, media.id, by="therapist")
            else:
                job = ctx.store.transcription_for(media.id)
                if job is None:
                    raise NotYours()
                ctx.store.transcription_remove_text(job.id)
            return json_response({"ok": True})
        return act

    def answer_visit(ctx: Ctx) -> Response:
        pid = clinic_inbox.own_patient(ctx.store, ctx.request.path_params["patient_id"])
        a = clinic_inbox.own_appointment(ctx.store, pid, ctx.request.path_params["appointment_id"])
        body = ctx.body if isinstance(ctx.body, dict) else {}
        note = body.get("note") if isinstance(body.get("note"), str) else ""
        if body.get("answer") == "keep":
            ptplans.decline_request(ctx.store, a.id, note)
        elif body.get("answer") == "move":
            date, at = body.get("date"), body.get("time")
            if not (isinstance(date, str) and isinstance(at, str)):
                return json_response({"error": "Choose the day and the time."}, 400)
            ptplans.move(ctx.store, a.id, f"{date}T{at}")
            if note.strip():
                ctx.store.appointment_update(a.id, response_note=note.strip()[:300])
        else:
            return json_response({"error": "Choose an answer."}, 400)
        return json_response({"ok": True})

    def attachment_file(ctx: Ctx) -> Response:
        pid = clinic_inbox.own_patient(ctx.store, ctx.request.path_params["patient_id"])
        a = attachments.get(ctx.store, pid, ctx.request.path_params["attachment_id"])
        if a is None or a.deleted_at is not None:
            raise NotYours()
        served = media_files.at(media_dir).response(attachments.rel(a), a.mime, f"{a.kind}.{a.ext}",
                                                    {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
        if served is None:
            raise NotYours()
        return served

    def voice_file(ctx: Ctx) -> Response:
        pid = clinic_inbox.own_patient(ctx.store, ctx.request.path_params["patient_id"])
        m = clinic_inbox.own_voice(ctx.store, pid, ctx.request.path_params["media_id"])
        if m.deleted_at is not None:
            raise NotYours()
        from src.portal import uploads
        served = media_files.at(media_dir).response(uploads.media_rel(m), web_common.media_mime(m),
                                                    f"voice.{m.ext}", {"Cache-Control": "no-store"})
        if served is None:
            raise NotYours()
        return served

    api = "/api/inbox/{patient_id}"
    clinic_route("/inbox", inbox_page, "therapist")
    clinic_route("/inbox/{patient_id}", conversation_page, "therapist")
    clinic_route(api + "/read", mark_read, "therapist", methods=("POST",), kind="api")
    clinic_route(api + "/reply", reply, "therapist", methods=("POST",), kind="api", files=True)
    clinic_route(api + "/uploads", upload_links, "therapist", methods=("POST",), kind="api")
    clinic_route(api + "/draft", draft, "therapist", methods=("POST",), kind="api")
    clinic_route(api + "/handled", handled, "therapist", methods=("POST",), kind="api")
    clinic_route(api + "/messaging", messaging, "therapist", methods=("POST",), kind="api")
    clinic_route(api + "/messages/{message_id:int}/remove", remove_message, "therapist", methods=("POST",),
                 kind="api")
    for action in ("heard", "delete", "text"):
        clinic_route(api + f"/voice/{{media_id}}/{action}", voice_action(action), "therapist", methods=("POST",),
                     kind="api")
    clinic_route(api + "/visits/{appointment_id:int}/answer", answer_visit, "therapist", methods=("POST",),
                 kind="api")
    clinic_route("/files/{patient_id}/attachments/{attachment_id}", attachment_file, "therapist", kind="api")
    clinic_route("/files/{patient_id}/voice/{media_id}", voice_file, "therapist", kind="api")

    # ------------------------------------------------------------------ Patients (slice 3a)

    def own_real_patient(store: SessionStore, patient_id: str):
        """A patient on this caseload; the built-in placeholder patient has no page."""
        clinic_inbox.own_patient(store, patient_id)
        patient = store.get_patient(patient_id)
        if patient is None or patient.is_builtin:
            raise NotYours()
        return patient

    def patients_html(ctx: Ctx, pane: str, current: Optional[str] = None, title: str = "Patients") -> Response:
        rows = clinic_patients.rows(ctx.store, clock())
        side_html = patients_view.side(rows, current, ctx.request.query_params.get("discharged") == "1")
        return html(patients_view.page(ctx.account, ctx.classes, side_html, pane, title))

    def patients_page(ctx: Ctx) -> Response:
        return patients_html(ctx, patients_view.pick_pane())

    def register_page(ctx: Ctx) -> Response:
        return patients_html(ctx, patients_view.register_pane(), title="Register a patient")

    def patient_tab(tab: str) -> Callable[[Ctx], Response]:
        def show(ctx: Ctx) -> Response:
            store, now = ctx.store, clock()
            patient = own_real_patient(store, ctx.request.path_params["patient_id"])
            pid = patient.id
            if tab == "overview":
                visits = [ptplans.appointment_json(store, a) for a in store.appointments(pid)]
                plans = store.plans(pid)
                body = patients_view.overview(
                    pid, clinic_patients.facts(store, pid, now), patients_view.plans_section(pid, plans),
                    patients_view.visits_section(pid, visits, [p for p in plans if not p.read_only],
                                                 str(ptplans.clinic_zone(store)), now.date()),
                    assist_view.summary_section(pid, ai_config.available(),
                                                bool(assistant.switches(store, pid)["summaries"])))
            elif tab == "notes":
                body = assist_view.notes_tab(pid, assistant.notes(store, pid))
            elif tab == "ai":
                if not ai_config.available():
                    raise NotYours()                       # no key, no AI control anywhere (018 SC-003)
                from src.assist import coach
                switches = assistant.switches(store, pid)
                body = assist_view.ai_tab(pid, switches, {k: store.assist_switched_on_at(pid, k) for k in switches},
                                          {"summaries": assistant.NOTICE_SUMMARIES, "coach": assistant.NOTICE_COACH},
                                          coach.conversations(store, pid))
            elif tab == "exercises":
                from src.ptlog import instruments, programs, questionnaires
                installed = instruments.load()
                live = {a.instrument_key for a in store.assignments(pid)}
                catalog = programs.load_catalog()
                body = patients_view.exercises(
                    pid, programs.list_programs(), [(k, programs.exercise_name(k)) for k in catalog.exercises],
                    clinic_patients.program_rows(store, pid, now.date()),
                    clinic_patients.questionnaire_rows(store, pid, installed, now.date()),
                    [(i.key, i.name) for i in installed.listed() if i.key not in live],
                    list(questionnaires.INTERVALS),
                    [f"The questionnaire file {x.file} could not be used: {x.message}" for x in installed.problems],
                    now.date())
            else:
                status = store.portal_status(pid)
                history = [(h.at[:16].replace("T", " "), h.event, h.detail or "")
                           for h in store.portal_audit_list(pid, limit=20)]
                body = patients_view.details(patient, store.get_discharge(pid), store.diary_enabled(pid),
                                             store.medication_list(pid), clinic_patients.access_line(status),
                                             status.state == "active", history)
            pane = patients_view.patient_pane(pid, clinic_patients.header(store, pid, now.date()), tab,
                                              ptmessages.unread_count(store, pid, "therapist"), body,
                                              ai=ai_config.available())
            return patients_html(ctx, pane, pid, title=f"Patients · {pid}")
        return show

    def _body(ctx: Ctx) -> dict:
        return ctx.body if isinstance(ctx.body, dict) else {}

    def _text(body: dict, key: str) -> Optional[str]:
        value = body.get(key)
        return value if isinstance(value, str) else None

    def _day(value) -> Optional[date]:
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            raise PTLogError("Give the date as a day, for example 2026-11-20.") from None

    def ok() -> Response:
        return json_response({"ok": True})

    def register(ctx: Ctx) -> Response:
        body = _body(ctx)
        pid = (_text(body, "patient_id") or "").strip()
        ptaccounts.add_patient(ctx.store, ctx.account, pid, label=(_text(body, "label") or "").strip() or None,
                               notes=(_text(body, "notes") or "").strip() or None)
        return json_response({"redirect": f"{PREFIX}/patients/{pid}"}, 201)

    def patient_api(action: str) -> Callable[[Ctx], Response]:
        def run(ctx: Ctx) -> Response:
            store, body = ctx.store, _body(ctx)
            pid = own_real_patient(store, ctx.request.path_params["patient_id"]).id
            if action == "details":
                store.update_patient(pid, label=_text(body, "label") or "", notes=_text(body, "notes") or "")
            elif action == "delete":
                if (_text(body, "confirm") or "").strip() != pid:
                    return json_response({"error": f"Type {pid} exactly to confirm."}, 400)
                store.delete_patient(pid)
                return json_response({"redirect": f"{PREFIX}/patients"})
            elif action == "discharge":
                store.discharge(pid, _day(body.get("on")), (_text(body, "reason") or "").strip() or None)
            elif action == "reactivate":
                store.reactivate(pid)
            elif action == "open-plan":
                ptplans.open_plan(store, pid, _text(body, "title"), _text(body, "diagnosis") or "",
                                  body.get("diagnosis_visible") is True)
            elif action == "add-visit":
                plan = clinic_inbox.own_plan(store, pid, body.get("plan_id"))
                minutes = body.get("minutes") if isinstance(body.get("minutes"), int) else 45
                ptplans.schedule(store, pid, f"{_text(body, 'date') or ''}T{_text(body, 'time') or ''}", minutes,
                                 _text(body, "note") or "", plan_id=plan.id if plan else None)
            elif action == "program":
                from src.ptlog import programs
                per_week = body.get("per_week") if isinstance(body.get("per_week"), int) else 3
                start, end = _day(body.get("start")), _day(body.get("end"))
                if body.get("program") == "custom":
                    keys = programs.validate_exercise_keys([k for k in body.get("keys") or [] if isinstance(k, str)])
                    store.assign_program(pid, "custom", "Custom", keys, per_week, start, end)
                else:
                    prog = programs.get_program(_text(body, "program") or "")
                    if prog is None:
                        return json_response({"error": "Choose a program."}, 400)
                    store.assign_program(pid, prog.id, prog.name, prog.exercise_keys, per_week, start, end)
            elif action == "questionnaire":
                from src.ptlog import instruments, questionnaires
                chosen, interval = _text(body, "instrument"), _text(body, "interval")
                if chosen not in instruments.load().by_key or interval not in questionnaires.INTERVAL_KEYS:
                    return json_response({"error": "Choose a questionnaire and how often."}, 400)
                store.assign_instrument(pid, chosen, interval)
            elif action == "logging":
                store.set_diary_enabled(pid, body.get("diary") is True)
                lines = clinic_patients.medication_lines(body.get("medications"))
                saved = store.set_medication_list(pid, lines)
                warned = [n.strip() for n in lines if ptmessages.check_text(n.strip())]
                if warned:
                    return json_response({"ok": True, "notice": "Saved. These look like they contain identifying "
                                          "details: " + ", ".join(warned), "saved": len(saved)})
            elif action == "issue-code":
                code, _ = access.issue_code(store, key, pid)
                return json_response({"show": code, "note": "Shown only once. Give it to the patient now. "
                                      "For demo and study use only."})
            elif action == "revoke-code":
                access.revoke_code(store, pid)
            return ok()
        return run

    def plan_api(action: str) -> Callable[[Ctx], Response]:
        def run(ctx: Ctx) -> Response:
            pid = own_real_patient(ctx.store, ctx.request.path_params["patient_id"]).id
            plan = clinic_inbox.own_plan(ctx.store, pid, ctx.request.path_params["plan_id"])
            if action not in clinic_patients.plan_actions(plan):
                return json_response({"error": "This plan can't be changed that way now.",
                                      "archived": plan.read_only}, 409)
            body = _body(ctx)
            if action == "edit":
                ptplans.edit_plan(ctx.store, plan.id, title=_text(body, "title"), diagnosis=_text(body, "diagnosis") or "",
                                  diagnosis_visible=body.get("diagnosis_visible") is True)
            else:
                {"complete": ptplans.complete, "reopen": ptplans.reopen, "archive": ptplans.archive}[action](
                    ctx.store, plan.id)
            return ok()
        return run

    def visit_api(action: str) -> Callable[[Ctx], Response]:
        def run(ctx: Ctx) -> Response:
            pid = own_real_patient(ctx.store, ctx.request.path_params["patient_id"]).id
            a = clinic_inbox.own_appointment(ctx.store, pid, ctx.request.path_params["appointment_id"])
            body = _body(ctx)
            if action == "move":
                ptplans.move(ctx.store, a.id, f"{_text(body, 'date') or ''}T{_text(body, 'time') or ''}")
            elif action == "decline":
                ptplans.decline_request(ctx.store, a.id, _text(body, "note") or "")
            else:
                ptplans.cancel(ctx.store, a.id)
            return ok()
        return run

    # ------------------------------------------------------------------ notes and AI (slice 3b)

    def summary(ctx: Ctx) -> Response:
        """A weekly summary for the page to show. Nothing is saved or sent: Save is a separate request."""
        pid = own_real_patient(ctx.store, ctx.request.path_params["patient_id"]).id
        if not ai_config.available():
            raise NotYours()
        result = assistant.weekly_summary(ctx.store, pid, account_id=ctx.account.id)
        return json_response(assist_view.summary_json(result, pid))

    def add_note(ctx: Ctx) -> Response:
        pid = own_real_patient(ctx.store, ctx.request.path_params["patient_id"]).id
        body = _body(ctx)
        text = _text(body, "body") or ""
        if not text.strip():
            return json_response({"error": "Write the note first."}, 400)
        drafted = body.get("ai_drafted") is True
        assistant.save_note(ctx.store, pid, text, ai_drafted=drafted, account_id=ctx.account.id,
                            edited=drafted and assist_view.note_is_edited(text, _text(body, "original")))
        return ok()

    def ai_switch(ctx: Ctx) -> Response:
        pid = own_real_patient(ctx.store, ctx.request.path_params["patient_id"]).id
        if not ai_config.available():
            raise NotYours()
        body = _body(ctx)
        which = _text(body, "which")
        if which not in assistant.SWITCHES:
            return json_response({"error": "Choose summaries or the coach."}, 400)
        assistant.set_switch(ctx.store, pid, which, body.get("on") is True, account_id=ctx.account.id)
        return ok()

    def end_questionnaire(ctx: Ctx) -> Response:
        pid = own_real_patient(ctx.store, ctx.request.path_params["patient_id"]).id
        wanted = ctx.request.path_params["assignment_id"]
        if wanted not in {a.id for a in ctx.store.assignments(pid)}:
            raise NotYours()
        ctx.store.end_assignment(wanted)
        return ok()

    pat = "/api/patients/{patient_id}"
    clinic_route("/patients", patients_page, "therapist")
    clinic_route("/patients/new", register_page, "therapist")
    clinic_route("/patients/{patient_id}", patient_tab("overview"), "therapist")
    clinic_route("/patients/{patient_id}/exercises", patient_tab("exercises"), "therapist")
    clinic_route("/patients/{patient_id}/details", patient_tab("details"), "therapist")
    clinic_route("/patients/{patient_id}/notes", patient_tab("notes"), "therapist")
    clinic_route("/patients/{patient_id}/ai", patient_tab("ai"), "therapist")
    clinic_route(pat + "/summary", summary, "therapist", methods=("POST",), kind="api")
    clinic_route(pat + "/notes", add_note, "therapist", methods=("POST",), kind="api")
    clinic_route(pat + "/ai", ai_switch, "therapist", methods=("POST",), kind="api")
    clinic_route("/api/patients", register, "therapist", methods=("POST",), kind="api")
    for suffix, action in (("details", "details"), ("delete", "delete"), ("discharge", "discharge"),
                           ("reactivate", "reactivate"), ("plans", "open-plan"), ("visits", "add-visit"),
                           ("program", "program"), ("questionnaires", "questionnaire"), ("logging", "logging"),
                           ("access/issue", "issue-code"), ("access/revoke", "revoke-code")):
        clinic_route(f"{pat}/{suffix}", patient_api(action), "therapist", methods=("POST",), kind="api")
    for action in ("edit", "complete", "reopen", "archive"):
        clinic_route(pat + "/plans/{plan_id:int}/" + action, plan_api(action), "therapist", methods=("POST",),
                     kind="api")
    for action in ("move", "decline", "cancel"):
        clinic_route(pat + "/visits/{appointment_id:int}/" + action, visit_api(action), "therapist",
                     methods=("POST",), kind="api")
    clinic_route(pat + "/questionnaires/{assignment_id:int}/end", end_questionnaire, "therapist", methods=("POST",),
                 kind="api")

    # ------------------------------------------------------------------ Schedule and People (slice 4)

    def schedule_page(ctx: Ctx) -> Response:
        content = schedule_people_view.schedule(clinic_schedule.visits(ctx.store), str(ptplans.clinic_zone(ctx.store)))
        return html(schedule_people_view.page(ctx.account, ctx.classes, "schedule", "Schedule", content))

    def people_page(ctx: Ctx) -> Response:
        store, me = ctx.store, ctx.account
        content = schedule_people_view.people(
            me, clinic_people.staff(store, me), clinic_people.patient_accounts(store, me),
            clinic_people.invites(store, me), clinic_people.therapists(store), clinic_people.patient_ids(store, me),
            clock())
        return html(schedule_people_view.page(me, ctx.classes, "people", "People", content))

    def _int(value) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def people_invite(ctx: Ctx) -> Response:
        body = _body(ctx)
        role = _text(body, "role")
        token, invite = clinic_people.invite(
            ctx.store, ctx.account, role, _int(body.get("therapist_id")) if role == "patient" else None,
            (_text(body, "patient_id") or "").strip() if role == "patient" else None,
            body.get("make_admin") is True and role == "therapist", clock=clock)
        link = f"{portal_url.rstrip('/')}/invite/{token}"
        return json_response({"show": link, "note": "Copy this link now and give it to the person. It is shown only "
                              "once, works once, and lasts 7 days. Limber does not send it anywhere."}, 201)

    def people_revoke(ctx: Ctx) -> Response:
        if not clinic_people.revoke(ctx.store, ctx.account, ctx.request.path_params["invite_id"]):
            raise NotYours()
        return ok()

    def people_status(ctx: Ctx) -> Response:
        status = _text(_body(ctx), "status")
        clinic_people.set_status(ctx.store, ctx.account, ctx.request.path_params["account_id"], status or "")
        return ok()

    def people_reassign(ctx: Ctx) -> Response:
        body = _body(ctx)
        clinic_people.reassign(ctx.store, ctx.account, _text(body, "patient_id") or "", _int(body.get("therapist_id")))
        return ok()

    clinic_route("/schedule", schedule_page, "therapist")
    clinic_route("/people", people_page, "admin")
    clinic_route("/api/people/invite", people_invite, "admin", methods=("POST",), kind="api")
    clinic_route("/api/people/invites/{invite_id:int}/revoke", people_revoke, "admin", methods=("POST",), kind="api")
    clinic_route("/api/people/accounts/{account_id:int}/status", people_status, "admin", methods=("POST",), kind="api")
    clinic_route("/api/people/reassign", people_reassign, "admin", methods=("POST",), kind="api")

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
    parser.add_argument("--portal-url", default="http://localhost:8600",
                        help="Where the patient portal runs; invite links point there")
    args = parser.parse_args(argv)
    origins = [f"http://{h}:{args.port}" for h in {args.host, "127.0.0.1", "localhost"}] + list(args.public_origin)
    secure = any(o.startswith("https://") for o in args.public_origin)
    app = create_app(allowed_origins=origins, trust_proxy=args.trust_proxy, secure_cookie=secure,
                     portal_url=args.portal_url)
    if args.host not in ("127.0.0.1", "localhost", "::1") and not secure:
        print("WARNING: serving plain HTTP beyond this machine. Put the clinic app behind HTTPS.")
    print(f"Limber clinic app on http://{args.host}:{args.port}{PREFIX}/  (demo and study use only)")
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
