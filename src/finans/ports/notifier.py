from typing import Protocol


class NotifyError(Exception):
    """Mesaj gönderilemedi; metin sırlardan arındırılmıştır."""


class Notifier(Protocol):
    def send(self, text: str, *, silent: bool) -> None:
        """`silent` sessiz saatlerde bildirimsiz gönderim içindir (K-13)."""
        ...
