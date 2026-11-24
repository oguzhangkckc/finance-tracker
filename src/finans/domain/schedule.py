"""Zamanlanmış işlerin planı ve mantıksal tarihi (K-80, K-86).

systemd birimleri bu saatlere uyar; tests/deploy bunu denetler.
"""

from calendar import monthrange
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Final

from finans.domain.models import DomainError
from finans.domain.numeric import in_domain_context

JOBS: Final = ("sync-prices", "sync-cpi", "weekly-report", "monthly-report", "payday", "backup")
# K-122: hafta içi iki çalışma; mantıksal gün ilkiyle başlar, ikincisi aynı günü yeniden dener.
SYNC_PRICES_TIMES: Final = (time(12, 0), time(21, 30))
SYNC_CPI_AT: Final = time(10, 30)
SYNC_CPI_DAYS: Final = (3, 4, 5)
WEEKLY_REPORT_AT: Final = time(20, 0)
MONTHLY_REPORT_AT: Final = time(11, 0)
MONTHLY_REPORT_DAYS: Final = range(5, 11)
PAYDAY_AT: Final = time(9, 0)
BACKUP_AT: Final = time(3, 0)
_SATURDAY: Final = 5
_SUNDAY: Final = 6


@in_domain_context
def payday_on(year: int, month: int, payday: int) -> date:
    if not 1 <= payday <= 31:
        raise DomainError(f"Maaş günü 1 ile 31 arasında olmalı: {payday}")
    return date(year, month, min(payday, monthrange(year, month)[1]))


@in_domain_context
def logical_date(job: str, now: datetime, *, payday: int | None = None) -> date:
    """`now` İstanbul yerel saatidir; sonuç işin `now`dan önceki son planlı çalışmasının günüdür."""
    if job not in JOBS:
        raise DomainError(f"tanınmayan iş: {job}; {', '.join(JOBS)} olmalı")
    if job == "payday" and payday is None:
        raise DomainError("payday işi için [contribution] payday tanımlı olmalı")
    slot = next(at for at in _slots(job, now, payday or 0) if at <= now)
    if job == "sync-cpi":
        return (slot.date().replace(day=1) - timedelta(days=1)).replace(day=1)
    if job == "monthly-report":
        return slot.date().replace(day=1) - timedelta(days=1)
    return slot.date()


def _slots(job: str, now: datetime, payday: int) -> Iterator[datetime]:
    day = now.date()
    while True:
        at = _slot_time(job, day, payday)
        if at is not None:
            yield datetime.combine(day, at, tzinfo=now.tzinfo)
        day -= timedelta(days=1)


def _slot_time(job: str, day: date, payday: int) -> time | None:
    match job:
        case "sync-prices":
            return SYNC_PRICES_TIMES[0] if day.weekday() < _SATURDAY else None
        case "sync-cpi":
            return SYNC_CPI_AT if day.day in SYNC_CPI_DAYS else None
        case "weekly-report":
            return WEEKLY_REPORT_AT if day.weekday() == _SUNDAY else None
        case "monthly-report":
            return MONTHLY_REPORT_AT if day.day in MONTHLY_REPORT_DAYS else None
        case "payday":
            return PAYDAY_AT if day == payday_on(day.year, day.month, payday) else None
        case _:
            return BACKUP_AT
