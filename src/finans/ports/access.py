from collections.abc import Mapping
from typing import Protocol


class AccessKeyError(Exception):
    """Cloudflare Access anahtarları alınamadı; ileti log'a yazılır (K-136)."""


class AccessKeySource(Protocol):
    def fetch(self) -> tuple[Mapping[str, object], ...]:
        """JWKS belgesindeki anahtarlar (`keys`); alınamazsa AccessKeyError."""
        ...
