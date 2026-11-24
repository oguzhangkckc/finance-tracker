from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from finans.ports.clock import BUSINESS_TZ


@dataclass
class FixedClock:
    current: datetime
    slept: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.current.tzinfo is None:
            raise ValueError("FixedClock saat dilimi bilgili bir datetime ister")

    def now(self) -> datetime:
        return self.current.astimezone(UTC)

    def today(self) -> date:
        return self.current.astimezone(BUSINESS_TZ).date()

    def advance(self, delta: timedelta) -> None:
        self.current += delta

    def sleep(self, seconds: int) -> None:
        self.slept.append(seconds)
        self.current += timedelta(seconds=seconds)
