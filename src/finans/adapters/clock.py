import time
from datetime import UTC, date, datetime

from finans.ports.clock import BUSINESS_TZ


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return datetime.now(BUSINESS_TZ).date()

    def sleep(self, seconds: int) -> None:
        time.sleep(seconds)
