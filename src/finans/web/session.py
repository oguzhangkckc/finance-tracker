"""Oturum çerezi ve CSRF belirteci; ikisini de oturum anahtarı imzalar (K-105, K-122, K-123)."""

import hmac
import secrets
from hashlib import sha256
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SESSION_COOKIE: Final = "__Host-oturum"
CSRF_FIELD: Final = "belirtec"
_COOKIE_ATTRIBUTES: Final = "Path=/; Secure; HttpOnly; SameSite=Strict"


def _sign(key: bytes, purpose: str, value: str) -> str:
    return hmac.new(key, f"{purpose}:{value}".encode(), sha256).hexdigest()


def _matches(expected: str, given: str) -> bool:
    # compare_digest ASCII dışı str'de TypeError verir; formdan her şey gelebilir.
    return hmac.compare_digest(expected.encode(), given.encode())


def csrf_token(key: bytes, session: str) -> str:
    return _sign(key, "csrf", session)


def valid_csrf(key: bytes, session: str, token: str) -> bool:
    return _matches(csrf_token(key, session), token)


def _session(key: bytes, raw: str | None) -> str | None:
    session, _, signature = (raw or "").partition(".")
    if session and _matches(_sign(key, "oturum", session), signature):
        return session
    return None


class SessionMiddleware:
    """İmzası geçerli çerez yoksa yeni oturum açar; belirteç oturuma bağlıdır."""

    def __init__(self, app: ASGIApp, *, key: bytes) -> None:
        self._app = app
        self._key = key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        # HTTP/2'de çerezler ayrı başlıklarda gelebilir.
        cookies = cookie_parser("; ".join(Headers(scope=scope).getlist("cookie")))
        state = scope.setdefault("state", {})
        session = _session(self._key, cookies.get(SESSION_COOKIE))
        if session is not None:
            state["session"] = session
            await self._app(scope, receive, send)
            return
        state["session"] = fresh = secrets.token_urlsafe(32)
        value = f"{fresh}.{_sign(self._key, 'oturum', fresh)}"
        cookie = f"{SESSION_COOKIE}={value}; {_COOKIE_ATTRIBUTES}"

        async def with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("set-cookie", cookie)
            await send(message)

        await self._app(scope, receive, with_cookie)
