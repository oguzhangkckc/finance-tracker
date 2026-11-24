from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


class BackupError(Exception):
    """Yedek alınamadı; mesajda sır yoktur."""


class DatabaseCopier(Protocol):
    def copy_to(self, target: Path) -> None:
        """Tutarlı, tek dosyalık kopya (backup API); dosya 600 izinle oluşur."""
        ...

    def integrity_check(self, path: Path) -> str:
        """`PRAGMA integrity_check` sonucu; sağlam kopyada "ok"."""
        ...


class Encryptor(Protocol):
    def encrypt(self, source: Path, target: Path, recipients: Sequence[str]) -> None:
        """Yalnızca açık anahtarlarla şifreler; sunucu sonucu çözemez (K-82)."""
        ...
