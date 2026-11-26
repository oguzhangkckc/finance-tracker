"""Cloudflare Access'in imza anahtarları (JWKS); yalnız takımın kendi adresinden (K-136)."""

import json
from collections.abc import Mapping
from typing import Final

import httpx

from finans.adapters._http import USER_AGENT
from finans.ports.access import AccessKeyError

TIMEOUT_SECONDS: Final = 5
MAX_BYTES: Final = 64 * 1024


class CloudflareAccessKeys:
    def __init__(self, team_domain: str) -> None:
        self.url = f"https://{team_domain}/cdn-cgi/access/certs"

    def fetch(self) -> tuple[Mapping[str, object], ...]:
        # Yönlendirme izlenmez: anahtarlar başka bir adresten gelirse kimliği o adres belirlerdi.
        try:
            with (
                httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client,
                client.stream(
                    "GET",
                    self.url,
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                ) as response,
            ):
                if response.status_code != httpx.codes.OK:
                    raise AccessKeyError(f"HTTP {response.status_code}")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise AccessKeyError(f"yanıt {MAX_BYTES} baytı aşıyor")
        except httpx.HTTPError as error:
            raise AccessKeyError(type(error).__name__) from None
        return _keys(bytes(body))


def _keys(body: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        document = json.loads(body)
    except ValueError:
        raise AccessKeyError("yanıt JSON değil") from None
    keys = document.get("keys") if isinstance(document, dict) else None
    if not isinstance(keys, list) or not all(isinstance(key, dict) for key in keys):
        raise AccessKeyError("yanıtta anahtar listesi yok")
    return tuple(keys)
