from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from finans.domain.models import DomainError, Instrument, InstrumentKind, PricePoint
from finans.domain.positions import build_positions
from finans.domain.quality import price_matches
from finans.ports.repositories import StoredInstrument, StoredTransaction
from finans.ports.sources import FetchResult, PriceSource, SourceBlocked, SourceError
from finans.ports.unit_of_work import UnitOfWork

TEFAS_KINDS = frozenset(
    {InstrumentKind.TEFAS_YAT, InstrumentKind.TEFAS_EMK, InstrumentKind.TEFAS_BYF}
)
# İşlem gününün çevresi de gelsin; K-64'ün tarih önerisi ±5 işlem gününe bakar.
BACKFILL_MARGIN = timedelta(days=7)
# Son fiyatın biraz gerisinden başlanır; geç gelen düzeltmeler revizyon olarak yakalanır.
REVISION_OVERLAP = timedelta(days=7)
DEFAULT_LOOKBACK = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class PriceRevision:
    day: date
    old: Decimal
    new: Decimal


@dataclass(frozen=True, slots=True)
class ManualReplacement:
    """Elle girilmiş fiyatın yerini alan TEFAS fiyatı; uyuşma K-64 kuralıyla (K-63)."""

    day: date
    manual: Decimal
    tefas: Decimal
    matches: bool


@dataclass(frozen=True, slots=True)
class FundSync:
    code: str
    start: date
    end: date
    received: int = 0
    inserted: int = 0
    unchanged: int = 0
    revised: tuple[PriceRevision, ...] = ()
    replaced: tuple[ManualReplacement, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PriceSyncReport:
    funds: tuple[FundSync, ...]
    stopped: str | None = None
    skipped: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.stopped is None and all(fund.error is None for fund in self.funds)


def sync_prices(
    source: PriceSource,
    open_uow: Callable[[], UnitOfWork],
    *,
    end: date,
    now: datetime,
    codes: Sequence[str] | None = None,
    start: date | None = None,
    backfill: bool = False,
) -> PriceSyncReport:
    with open_uow() as uow:
        plan = _plan(uow, codes, start, end, backfill)
    funds: list[FundSync] = []
    for index, (inst, first) in enumerate(plan):
        # Ağ isteği yazma kilidi alınmadan yapılır; yavaş bir yanıt veritabanını kilitli tutmasın.
        try:
            result = source.fetch(inst, first, end)
        except SourceBlocked as exc:
            funds.append(FundSync(inst.code, first, end, error=str(exc)))
            skipped = tuple(later.code for later, _ in plan[index + 1 :])
            return PriceSyncReport(tuple(funds), stopped=str(exc), skipped=skipped)
        except SourceError as exc:
            funds.append(FundSync(inst.code, first, end, error=str(exc)))
            continue
        with open_uow() as uow:
            funds.append(_store(uow, inst.code, first, end, result, now))
    return PriceSyncReport(tuple(funds))


def _plan(
    uow: UnitOfWork,
    codes: Sequence[str] | None,
    start: date | None,
    end: date,
    backfill: bool,
) -> list[tuple[Instrument, date]]:
    stored = {item.instrument.code: item for item in uow.instruments.list(include_inactive=True)}
    transactions = uow.transactions.list()
    if codes is not None:
        selected = [_requested(stored.get(code), code) for code in dict.fromkeys(codes)]
    else:
        book = build_positions([s.transaction for s in transactions], as_of=date.max)
        selected = [
            item.instrument
            for code, item in sorted(stored.items())
            if item.instrument.kind in TEFAS_KINDS and (item.active or book.units_of(code) > 0)
        ]
    plan = []
    for inst in selected:
        first = _start(uow, inst.code, transactions, start, end, backfill)
        if first <= end:
            plan.append((inst, first))
    return plan


def _requested(item: StoredInstrument | None, code: str) -> Instrument:
    if item is None:
        raise DomainError(
            f"{code} tanımlı değil; portfolio.toml'a ekleyip `ft config apply` çalıştır."
        )
    if item.instrument.kind not in TEFAS_KINDS:
        raise DomainError(f"{code} bir TEFAS fonu değil; fiyatı `ft price set` ile girilir.")
    return item.instrument


def _start(
    uow: UnitOfWork,
    code: str,
    transactions: Sequence[StoredTransaction],
    start: date | None,
    end: date,
    backfill: bool,
) -> date:
    if start is not None:
        return start
    if not backfill:
        latest = uow.prices.latest(code)
        if latest is not None:
            return latest.price_date - REVISION_OVERLAP
    trades = [s.transaction.trade_date for s in transactions if s.transaction.instrument == code]
    if trades:
        return min(trades) - BACKFILL_MARGIN
    return end - DEFAULT_LOOKBACK


def _store(
    uow: UnitOfWork,
    code: str,
    start: date,
    end: date,
    result: FetchResult[PricePoint],
    now: datetime,
) -> FundSync:
    for payload in result.raw:
        uow.raw_payloads.add(payload)
    inserted = unchanged = 0
    revised: list[PriceRevision] = []
    replaced: list[ManualReplacement] = []
    for point in result.points:
        write = uow.prices.upsert(point, fetched_at=now)
        if write.status == "inserted":
            inserted += 1
        elif write.status == "unchanged":
            unchanged += 1
        elif write.previous is not None and write.previous_source == "manual":
            matches = price_matches(write.previous, point.price)
            replaced.append(
                ManualReplacement(point.price_date, write.previous, point.price, matches)
            )
        elif write.previous is not None:
            revised.append(PriceRevision(point.price_date, write.previous, point.price))
    return FundSync(
        code,
        start,
        end,
        received=len(result.points),
        inserted=inserted,
        unchanged=unchanged,
        revised=tuple(revised),
        replaced=tuple(replaced),
    )
