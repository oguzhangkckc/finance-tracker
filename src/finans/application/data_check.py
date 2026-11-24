from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

from finans.application.price_sync import TEFAS_KINDS
from finans.domain.models import Instrument, PricePoint, Transaction
from finans.domain.portfolio import QualityThresholds
from finans.domain.positions import build_positions
from finans.domain.quality import DataIssue, check_prices, check_trade_prices, trading_days
from finans.ports.unit_of_work import UnitOfWork

DEFAULT_WINDOW = timedelta(days=30)


def check_data(
    uow: UnitOfWork, *, quality: QualityThresholds, today: date, since: date
) -> list[DataIssue]:
    """`today` gününe kadarki fiyatları ve işlemleri denetler; geçmiş tarihli bir rapor kendi
    gününden sonraki işlemleri görmez."""
    history = price_series(uow, today)
    issues = check_prices(
        tracked_instruments(uow, as_of=today), history, today=today, since=since, thresholds=quality
    )
    trades = [(f"#{s.id}", s.transaction) for s in uow.transactions.list(until=today)]
    issues.extend(_trade_issues(uow, trades, history))
    return issues


def tracked_instruments(uow: UnitOfWork, *, as_of: date = date.max) -> list[Instrument]:
    """Aktif varlıklar ile pasif olup `as_of` gününde hâlâ pay tutulanlar."""
    book = build_positions([s.transaction for s in uow.transactions.list()], as_of=as_of)
    return [
        item.instrument
        for item in uow.instruments.list(include_inactive=True)
        if item.active or book.units_of(item.instrument.code) > 0
    ]


def trade_price_issues(
    uow: UnitOfWork, trades: Sequence[tuple[str, Transaction]], *, today: date
) -> list[DataIssue]:
    """Yeni girilen işlemler için K-64 kontrolü; girilen basamak sayısı korunur."""
    return _trade_issues(uow, trades, price_series(uow, today))


def _trade_issues(
    uow: UnitOfWork,
    trades: Sequence[tuple[str, Transaction]],
    history: dict[str, list[PricePoint]],
) -> list[DataIssue]:
    instruments: dict[str, Instrument] = {
        item.instrument.code: item.instrument
        for item in uow.instruments.list(include_inactive=True)
    }
    days = trading_days(
        point
        for code, series in history.items()
        if code in instruments and instruments[code].kind in TEFAS_KINDS
        for point in series
    )
    return check_trade_prices(trades, instruments, history, days)


def price_series(uow: UnitOfWork, today: date) -> dict[str, list[PricePoint]]:
    history: dict[str, list[PricePoint]] = defaultdict(list)
    for point in uow.prices.history(until=today):
        history[point.instrument].append(point)
    return dict(history)
