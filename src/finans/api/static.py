"""Derlenmiş arayüzün sunulması (K-139): API'de karşılığı olmayan her adres buraya düşer.

`assets/` altındaki özetli dosyalar bir yıl önbellekte kalır; diğer dosyalar ve `index.html` her
seferinde yeniden doğrulanır. Dosyaya karşılık gelmeyen adres SPA'nın `index.html`'idir, sayfayı
istemci seçer. Kimlik ara katmanda denetlendiği için buraya yalnız doğrulanmış istek gelir (K-136).
"""

from pathlib import Path
from typing import Final

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from finans.api.errors import ApiError

PAGE_POLICY: Final = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
)
IMMUTABLE: Final = "public, max-age=31536000, immutable"
REVALIDATE: Final = "no-cache"
ASSETS: Final = "assets"
INDEX: Final = "index.html"
NOT_BUILT: Final = "Arayüz sunucuda yok: derlenmiş dosyalar bulunamadı."
READ_METHODS: Final = ("GET", "HEAD")


class StaticSite:
    """Yönlendiricinin varsayılan uygulaması; `/api` altı ve HTTP dışı eski varsayılana gider."""

    def __init__(self, root: Path, fallback: ASGIApp) -> None:
        self._root = root
        self._fallback = fallback

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] != "http" or path == "/api" or path.startswith("/api/"):
            await self._fallback(scope, receive, send)
        elif scope["method"] not in READ_METHODS:
            raise HTTPException(405, headers={"Allow": ", ".join(READ_METHODS)})
        else:
            response = await run_in_threadpool(self._response, path.removeprefix("/"))
            await response(scope, receive, send)

    def _response(self, relative: str) -> Response:
        # Deploy `dist`'i yeniden adlandırarak değiştirir (K-140); kök her istekte çözülür.
        root = self._root.resolve()
        index = root / INDEX
        if not index.is_file():
            raise ApiError(503, NOT_BUILT)
        target = _inside(root, relative)
        under_assets = target.relative_to(root).parts[:1] == (ASSETS,)
        if under_assets:
            if not target.is_file():
                raise HTTPException(404)
            return FileResponse(target, headers={"Cache-Control": IMMUTABLE})
        if target.is_file() and target != index:
            return FileResponse(target, headers={"Cache-Control": REVALIDATE})
        return FileResponse(
            index, headers={"Cache-Control": REVALIDATE, "Content-Security-Policy": PAGE_POLICY}
        )


def _inside(root: Path, relative: str) -> Path:
    """`..`, mutlak yol ya da dizinin dışına giden bağlantı 404'tür."""
    try:
        target = (root / relative).resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(404) from exc
    if not target.is_relative_to(root):
        raise HTTPException(404)
    return target
