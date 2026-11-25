"""Zamanlanmış işlerin planı ve mantıksal tarihi (K-80, K-86).

systemd birimleri bu saatlere uyar; tests/deploy bunu denetler.
"""

from calendar import monthrange
from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta
from typing import Final

from finans.domain.models import DomainError, YearMonth
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
_SEARCH_DAYS: Final = 400
_SUNDAY: Final = 6


@in_domain_context
def payday_on(year: int, month: int, payday: int) -> date:
    if not 1 <= payday <= 31:
        raise DomainError(f"Maaş günü 1 ile 31 arasında olmalı: {payday}")
    return date(year, month, min(payday, monthrange(year, month)[1]))


@in_domain_context
def logical_date(
    job: str, now: datetime, *, payday: int | Callable[[YearMonth], int | None] | None = None
) -> date:
    """`now` İstanbul yerel saatidir; sonuç işin `now`dan önceki son planlı çalışmasının günüdür.
    `payday` aya göre de verilebilir: yürürlük tarihli ayarda her ayın kendi maaş günü (K-127)."""
    if job not in JOBS:
        raise DomainError(f"tanınmayan iş: {job}; {', '.join(JOBS)} olmalı")
    if job == "payday" and payday is None:
        raise DomainError("payday işi için [contribution] payday tanımlı olmalı")
    schedule = payday if callable(payday) else (lambda _month: payday or 0)
    slot = next((at for at in _slots(job, now, schedule) if at <= now), None)
    if slot is None:
        raise DomainError("payday işi için son bir yılda tanımlı bir maaş günü (payday) yok")
    if job == "sync-cpi":
        return (slot.date().replace(day=1) - timedelta(days=1)).replace(day=1)
    if job == "monthly-report":
        return slot.date().replace(day=1) - timedelta(days=1)
    return slot.date()


def _slots(
    job: str, now: datetime, payday: Callable[[YearMonth], int | None]
) -> Iterator[datetime]:
    # Bir yıldan eskiye bakılmaz: hiçbir ayda maaş günü yoksa arama sonsuza gitmesin.
    day = now.date()
    for _ in range(_SEARCH_DAYS):
        at = _slot_time(job, day, payday)
        if at is not None:
            yield datetime.combine(day, at, tzinfo=now.tzinfo)
        day -= timedelta(days=1)


def _slot_time(job: str, day: date, payday: Callable[[YearMonth], int | None]) -> time | None:
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
            month_payday = payday(YearMonth(day.year, day.month))
            if month_payday is None:
                return None
            return PAYDAY_AT if day == payday_on(day.year, day.month, month_payday) else None
        case _:
            return BACKUP_AT
