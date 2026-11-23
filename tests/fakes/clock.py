from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from finans.ports.clock import BUSINESS_TZ


@dataclass
class FixedClock:
    current: datetime

    def __post_init__(self) -> None:
        if self.current.tzinfo is None:
            raise ValueError("FixedClock saat dilimi bilgili bir datetime ister")

    def now(self) -> datetime:
        return self.current.astimezone(UTC)

    def today(self) -> date:
        return self.current.astimezone(BUSINESS_TZ).date()

    def advance(self, delta: timedelta) -> None:
        self.current += delta
