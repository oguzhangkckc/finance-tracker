from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from finans.domain.models import YearMonth
from finans.ports.sources import CpiSource
from finans.ports.unit_of_work import UnitOfWork

# 2025=100 serisi bu aydan başlıyor; tam geçmiş tek istekte gelir (K-43, K-61).
CPI_HISTORY_START = YearMonth(2005, 1)


@dataclass(frozen=True, slots=True)
class CpiRevision:
    period: YearMonth
    old: Decimal
    new: Decimal


@dataclass(frozen=True, slots=True)
class CpiSyncReport:
    series: str
    received: int
    inserted: int
    unchanged: int
    revised: tuple[CpiRevision, ...]
    latest: YearMonth | None


def sync_cpi(
    source: CpiSource,
    open_uow: Callable[[], UnitOfWork],
    *,
    series: str,
    base: str,
    start: YearMonth,
    end: YearMonth,
    now: datetime,
) -> CpiSyncReport:
    # Ağ isteği yazma kilidi alınmadan yapılır; yavaş bir yanıt veritabanını kilitli tutmasın.
    result = source.fetch(series, start, end)
    inserted = unchanged = 0
    revised: list[CpiRevision] = []
    with open_uow() as uow:
        for payload in result.raw:
            uow.raw_payloads.add(payload)
        for point in result.points:
            write = uow.cpi.upsert(series, point, base=base, fetched_at=now)
            if write.status == "inserted":
                inserted += 1
            elif write.status == "unchanged":
                unchanged += 1
            elif write.previous is not None:
                revised.append(CpiRevision(point.period, write.previous, point.index))
        latest = uow.cpi.latest(series)
    return CpiSyncReport(
        series=series,
        received=len(result.points),
        inserted=inserted,
        unchanged=unchanged,
        revised=tuple(revised),
        latest=None if latest is None else latest.period,
    )
