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
    """Takip edilen varlıkların fiyat verisini ve kayıtlı işlemlerin fiyatını denetler."""
    stored = uow.instruments.list(include_inactive=True)
    transactions = uow.transactions.list()
    book = build_positions([s.transaction for s in transactions], as_of=date.max)
    tracked = [
        item.instrument for item in stored if item.active or book.units_of(item.instrument.code) > 0
    ]
    history = _history(uow, today)
    issues = check_prices(tracked, history, today=today, since=since, thresholds=quality)
    trades = [(f"#{s.id}", s.transaction) for s in transactions]
    issues.extend(_trade_issues(uow, trades, history))
    return issues


def trade_price_issues(
    uow: UnitOfWork, trades: Sequence[tuple[str, Transaction]], *, today: date
) -> list[DataIssue]:
    """Yeni girilen işlemler için K-64 kontrolü; girilen basamak sayısı korunur."""
    return _trade_issues(uow, trades, _history(uow, today))


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


def _history(uow: UnitOfWork, today: date) -> dict[str, list[PricePoint]]:
    history: dict[str, list[PricePoint]] = defaultdict(list)
    for point in uow.prices.history(until=today):
        history[point.instrument].append(point)
    return dict(history)
