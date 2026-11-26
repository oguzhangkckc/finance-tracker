from collections.abc import Mapping
from dataclasses import dataclass, field

from finans.ports.access import AccessKeyError


@dataclass
class FakeAccessKeys:
    keys: list[Mapping[str, object]] = field(default_factory=list)
    down: bool = False
    calls: int = 0

    def fetch(self) -> tuple[Mapping[str, object], ...]:
        self.calls += 1
        if self.down:
            raise AccessKeyError("ConnectError")
        return tuple(self.keys)
