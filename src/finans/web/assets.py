"""Statik dosyalar içerik özetli adla ve bir yıl önbellekle sunulur (K-128)."""

import hashlib
from pathlib import Path
from typing import Final

from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response

IMMUTABLE: Final = "public, max-age=31536000, immutable"
_DIGEST_LENGTH: Final = 12


class Assets:
    """Özet açılışta bir kez hesaplanır; dosya değişince adı da değişir, eski ad 404 döner."""

    def __init__(self, directory: Path) -> None:
        self._files: dict[str, Path] = {}
        self._urls: dict[str, str] = {}
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            name = path.relative_to(directory).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:_DIGEST_LENGTH]
            stem, dot, suffix = name.rpartition(".")
            served = f"{stem}.{digest}.{suffix}" if dot else f"{name}.{digest}"
            self._files[served] = path
            self._urls[name] = f"/static/{served}"

    def url(self, name: str) -> str:
        return self._urls[name]

    def serve(self, request: Request) -> Response:
        path = self._files.get(request.path_params["served"])
        if path is None:
            return PlainTextResponse("Bulunamadı.", status_code=404)
        return FileResponse(path, headers={"Cache-Control": IMMUTABLE})
