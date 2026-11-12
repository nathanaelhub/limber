"""
Web helpers shared by the patient portal and the clinic app (feature 019, T003).

Both apps are separate Starlette apps with their own routes, cookie and static folder (constitution 1.5.1); what
they share is how a response is made safe: the content security policy, the security headers, JSON answers, and
the check that a write came from the app's own page. Nothing here imports anything heavy.
"""

from __future__ import annotations

from typing import Iterable, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse

CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data: blob:; media-src 'self' blob:; worker-src 'self' blob:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

MEDIA_TYPES = {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm", "m4a": "audio/mp4",
               "ogg": "audio/ogg", "mp3": "audio/mpeg", "wav": "audio/wav"}


def media_mime(m) -> str:
    """The type a clip or voice note is served with; every format the media probe accepts has one."""
    return MEDIA_TYPES.get(m.ext, "application/octet-stream")


def build_csp(bucket: Optional[str]) -> str:
    """The policy, with the private file bucket allowed for images, media and uploads when there is one."""
    if not bucket:
        return CSP
    return (CSP.replace("connect-src 'self'", f"connect-src 'self' {bucket}")
               .replace("img-src 'self' data: blob:", f"img-src 'self' data: blob: {bucket}")
               .replace("media-src 'self' blob:", f"media-src 'self' blob: {bucket}"))


def csp() -> str:
    """The policy for this installation. On the hosted demo, media are fetched from (and sent to) the private R2
    bucket through signed links (feature 020)."""
    from src.media import files as media_files
    return build_csp(media_files.r2_origin())


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

    def __init__(self, app, hsts: bool = False, csp: Optional[str] = None):
        self.app = app
        self.headers = dict(SECURITY_HEADERS, **{"content-security-policy": csp or globals()["csp"]()})
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


def json_response(data, status: int = 200, headers: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store", **(headers or {})})


def bad(err: Exception) -> JSONResponse:
    """A refused write: 409 when the plan of care is archived (feature 017), 404 for a missing plan, else 400."""
    from src.ptlog.models import PlanArchived, PlanNotFound
    if isinstance(err, PlanArchived):
        return json_response({"error": str(err), "archived": True}, 409)
    if isinstance(err, PlanNotFound):
        return json_response({"error": str(err)}, 404)
    return json_response({"error": str(err)}, 400)


def check_post(request: Request, origins: Iterable[str], content_type: str = "application/json",
               page_name: str = "Limber") -> Optional[JSONResponse]:
    """Refuse a write that did not come from this app's own page (403) or is not the expected type (415)."""
    if (request.headers.get("origin") or "").rstrip("/") not in origins:
        return json_response({"error": f"This request did not come from the {page_name} page."}, 403)
    if not request.headers.get("content-type", "").lower().startswith(content_type):
        return json_response({"error": f"Send {content_type}."}, 415)
    return None


def client_address(request: Request, trust_proxy: bool) -> str:
    """The caller's address; behind the hosting proxy, the first forwarded address."""
    address = request.client.host if request.client else "unknown"
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        address = forwarded.split(",")[0].strip() or address
    return address
