"""API testleri için istemci: httpx'in ASGI taşıyıcısı, Access jetonu yerel anahtarla imzalı."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Final

import httpx
from fastapi import FastAPI

from tests.fakes.clock import FixedClock
from tests.support.access import ORIGIN, access_token

ACCESS_HEADER: Final = "Cf-Access-Jwt-Assertion"
SAME_ORIGIN: Final = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


class ApiClient:
    """Varsayılan olarak jetonu ve yazmada aynı köken başlıklarını ekler; `drop` bunları çıkarır.
    `startup` açılış adımını (anahtarların önceden çekilmesi) da çalıştırır."""

    def __init__(
        self,
        app: FastAPI,
        clock: FixedClock,
        *,
        signed: bool = True,
        startup: bool = False,
        raise_errors: bool = True,
    ) -> None:
        self._app = app
        self._clock = clock
        self._signed = signed
        self._startup = startup
        self._raise_errors = raise_errors

    def request(
        self,
        method: str,
        path: str,
        *,
        json: object = None,
        content: bytes | AsyncIterator[bytes] | None = None,
        headers: Mapping[str, str] | None = None,
        drop: tuple[str, ...] = (),
    ) -> httpx.Response:
        merged: dict[str, str] = {}
        if self._signed:
            merged[ACCESS_HEADER] = access_token(self._clock.now())
        if method not in SAFE_METHODS:
            merged.update(SAME_ORIGIN)
        merged.update(headers or {})
        for name in drop:
            merged.pop(name, None)

        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app, raise_app_exceptions=self._raise_errors)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                return await c.request(method, path, json=json, content=content, headers=merged)

        async def send_after_startup() -> httpx.Response:
            async with self._app.router.lifespan_context(self._app):
                return await send()

        return asyncio.run(send_after_startup() if self._startup else send())

    def get(self, path: str, *, headers: Mapping[str, str] | None = None) -> httpx.Response:
        return self.request("GET", path, headers=headers)

    def post(
        self,
        path: str,
        *,
        json: object = None,
        headers: Mapping[str, str] | None = None,
        drop: tuple[str, ...] = (),
    ) -> httpx.Response:
        return self.request("POST", path, json=json, headers=headers, drop=drop)
