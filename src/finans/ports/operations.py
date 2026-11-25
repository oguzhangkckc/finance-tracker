from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol


class JobLock(Protocol):
    def hold(self, job: str) -> AbstractContextManager[bool]:
        """Kilit alınamazsa False verir; ikinci örnek beklemeden çıkar (K-12)."""
        ...


class HealthPing(Protocol):
    def ping(self, check: str, *, ok: bool) -> None:
        """Dead man's switch (K-84); tanımsız kontrol sessizce atlanır."""
        ...


class RefreshRequests(Protocol):
    """Elle fiyat güncellemesi isteği; web süreci yalnızca dosya bırakır (K-123)."""

    def accepted(self) -> list[datetime]: ...

    def request(self, now: datetime) -> None: ...
