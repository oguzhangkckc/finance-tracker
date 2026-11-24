from contextlib import AbstractContextManager
from typing import Protocol


class JobLock(Protocol):
    def hold(self, job: str) -> AbstractContextManager[bool]:
        """Kilit alınamazsa False verir; ikinci örnek beklemeden çıkar (K-12)."""
        ...


class HealthPing(Protocol):
    def ping(self, check: str, *, ok: bool) -> None:
        """Dead man's switch (K-84); tanımsız kontrol sessizce atlanır."""
        ...
