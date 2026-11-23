from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Europe/Istanbul")


class Clock(Protocol):
    def now(self) -> datetime:
        """Saat dilimi bilgili, UTC."""
        ...

    def today(self) -> date:
        """Europe/Istanbul takvim günü."""
        ...
