"""Elle fiyat güncellemesinin seyreklik kuralı; yalnızca burada değişir (K-122, K-123)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final

from finans.domain.numeric import in_domain_context

REFRESH_COOLDOWN: Final = timedelta(hours=1)
DAILY_REFRESH_LIMIT: Final = 6
_SATURDAY: Final = 5


@dataclass(frozen=True, slots=True)
class RefreshDecision:
    allowed: bool
    reason: str | None = None
    earliest: datetime | None = None


@in_domain_context
def refresh_decision(
    now: datetime, *, accepted: Sequence[datetime], last_sync: datetime | None
) -> RefreshDecision:
    """`now` İstanbul yerel saatidir; gün sınırı ve hafta sonu ona göre belirlenir."""
    if now.weekday() >= _SATURDAY:
        return RefreshDecision(False, "hafta sonu fiyat yayımlanmaz", _next_weekday_start(now))
    today = [moment for moment in accepted if moment.astimezone(now.tzinfo).date() == now.date()]
    if len(today) >= DAILY_REFRESH_LIMIT:
        reason = f"bugünkü {DAILY_REFRESH_LIMIT} elle güncelleme kullanıldı"
        return RefreshDecision(False, reason, _next_weekday_start(now))
    latest = max([*accepted, *([last_sync] if last_sync is not None else [])], default=None)
    if latest is not None and now - latest < REFRESH_COOLDOWN:
        reason = "son güncellemeden bu yana 1 saat geçmedi"
        return RefreshDecision(False, reason, (latest + REFRESH_COOLDOWN).astimezone(now.tzinfo))
    return RefreshDecision(True)


def _next_weekday_start(now: datetime) -> datetime:
    day: date = now.date() + timedelta(days=1)
    while day.weekday() >= _SATURDAY:
        day += timedelta(days=1)
    return datetime.combine(day, time(0), tzinfo=now.tzinfo)
