import asyncio
from collections.abc import AsyncIterator, Sequence

import httpx
from starlette.types import ASGIApp

Headers = dict[str, str] | Sequence[tuple[str, str]]
Body = bytes | AsyncIterator[bytes] | None


class WebClient:
    """Starlette'in test istemcisi httpx2 istiyor; mevcut httpx'in ASGI taşıyıcısı yeterli."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    def request(
        self, method: str, path: str, headers: Headers | None = None, content: Body = None
    ) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                return await c.request(method, path, headers=headers, content=content)

        return asyncio.run(send())

    def get(self, path: str, headers: Headers | None = None) -> httpx.Response:
        return self.request("GET", path, headers)

    def head(self, path: str, headers: Headers | None = None) -> httpx.Response:
        return self.request("HEAD", path, headers)

    def post(
        self, path: str, headers: Headers | None = None, content: Body = None
    ) -> httpx.Response:
        return self.request("POST", path, headers, content)
