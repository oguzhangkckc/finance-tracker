"""İstek sırası: güvenlik başlıkları → Access kimliği → gövde sınırı → CSRF → uç (K-136, K-137).

Kimlik yönlendirmeden önce denetlenir: kimliksiz istek hangi adres olursa olsun 403 alır."""

import logging
from typing import Final

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from finans.api.auth import AccessDenied, AccessVerifier
from finans.api.encoding import error_response

SECURITY_HEADERS: Final = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
HEALTH_PATH: Final = "/api/saglik"
ACCESS_HEADER: Final = "cf-access-jwt-assertion"
MAX_BODY_BYTES: Final = 16 * 1024
DENIED: Final = "Erişim reddedildi."
_LOG = logging.getLogger("finans.api")


class SecurityHeaders:
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


class RequireAccess:
    """`Cf-Access-Jwt-Assertion` doğrulanır; anahtar yenilemesi beklemesin diye iş parçacığında."""

    def __init__(self, app: ASGIApp, verifier: AccessVerifier) -> None:
        self._app = app
        self._verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == HEALTH_PATH:
            await self._app(scope, receive, send)
            return
        token = Headers(scope=scope).get(ACCESS_HEADER)
        try:
            email = await run_in_threadpool(self._verifier.verify, token)
        except AccessDenied as denied:
            _LOG.warning("Erişim reddedildi: %s %s: %s", scope["method"], scope["path"], denied)
            await error_response(403, DENIED)(scope, receive, send)
            return
        scope.setdefault("state", {})["email"] = email
        await self._app(scope, receive, send)


class BodyLimit:
    """Yazma isteğinde Content-Length zorunlu ve en çok 16 KiB."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self._app(scope, receive, send)
            return
        length = Headers(scope=scope).get("content-length", "")
        if not length.isascii() or not length.isdigit():
            await error_response(411, "İstekte uzunluk belirtilmeli.")(scope, receive, send)
            return
        if int(length) > MAX_BODY_BYTES:
            await error_response(413, "İstek çok büyük.")(scope, receive, send)
            return
        await self._app(scope, receive, send)


class RequireSameOrigin:
    """CSRF (K-137): yazma yalnız JSON gövdeyle, bu kökenden ve aynı siteden. CORS başlığı hiçbir
    yanıtta verilmez; başka siteden `fetch` ön kontrole, form ise JSON kuralına takılır."""

    def __init__(self, app: ASGIApp, origin: str) -> None:
        self._app = app
        self._origin = origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        media = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media != "application/json":
            await error_response(415, "Yalnız application/json kabul edilir.")(scope, receive, send)
            return
        if headers.get("origin") != self._origin:
            reason = "köken farklı"
        elif headers.get("sec-fetch-site") != "same-origin":
            reason = "Sec-Fetch-Site same-origin değil"
        else:
            await self._app(scope, receive, send)
            return
        _LOG.warning("Yazma reddedildi: %s %s: %s", scope["method"], scope["path"], reason)
        await error_response(403, DENIED)(scope, receive, send)
