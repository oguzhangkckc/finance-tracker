"""Kimlik, güvenlik başlıkları ve istek boyutu (K-101, K-102, K-123)."""

from email.errors import HeaderParseError
from email.header import decode_header, make_header
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOGIN_HEADER: Final = "tailscale-user-login"
NAME_HEADER: Final = "tailscale-user-name"
MAX_BODY_BYTES: Final = 16 * 1024
SECURITY_HEADERS: Final = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # no-referrer'da tarayıcı form POST'una "Origin: null" yazar ve köken denetimi hep reddeder;
    # same-origin dışarıya yine referrer göndermez.
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def display_name(raw: str | None) -> str | None:
    """Tailscale görünen adı RFC 2047 ile kodlanmış gönderir; çözülemezse ad gösterilmez."""
    if raw is None:
        return None
    try:
        text = str(make_header(decode_header(raw))).strip()
    except (HeaderParseError, LookupError, UnicodeError, ValueError):
        return None
    return text or None


def same_origin(headers: Headers, origin: str) -> bool:
    """POST yalnızca bu kökenden: Origin ve Fetch Metadata birlikte (K-105, K-122)."""
    return headers.getlist("origin") == [origin] and headers.getlist("sec-fetch-site") == [
        "same-origin"
    ]


class IdentityMiddleware:
    """Yalnızca `Tailscale-User-Login` denetlenir; görünen ad kimlik yerine geçmez (K-102)."""

    def __init__(self, app: ASGIApp, *, allowed_login: str) -> None:
        self._app = app
        self._allowed = allowed_login

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        logins = headers.getlist(LOGIN_HEADER)
        if len(logins) != 1 or logins[0] != self._allowed:
            await PlainTextResponse("Erişim yok.", status_code=403)(scope, receive, send)
            return
        scope.setdefault("state", {})["display_name"] = display_name(headers.get(NAME_HEADER))
        await self._app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
            await send(message)

        await self._app(scope, receive, with_headers)


class BodyLimitMiddleware:
    """GET ve HEAD dışındaki isteklerde Content-Length zorunlu ve en fazla 16 KB."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD"}:
            await self._app(scope, receive, send)
            return
        length = Headers(scope=scope).get("content-length")
        if length is None or not length.isdigit():
            await PlainTextResponse("Uzunluk belirtilmeli.", status_code=411)(scope, receive, send)
            return
        if int(length) > MAX_BODY_BYTES:
            await PlainTextResponse("İstek çok büyük.", status_code=413)(scope, receive, send)
            return
        await self._app(scope, receive, send)
