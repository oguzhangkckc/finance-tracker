from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from finans.ports.sources import SourceError


@dataclass
class FakeLock:
    busy: bool = False

    @contextmanager
    def hold(self, job: str) -> Iterator[bool]:
        yield not self.busy


@dataclass
class FakePing:
    fail: bool = False
    pings: list[tuple[str, bool]] = field(default_factory=list)

    def ping(self, check: str, *, ok: bool) -> None:
        if self.fail:
            raise SourceError("https://hc-ping.example/***: bağlantı hatası")
        self.pings.append((check, ok))
