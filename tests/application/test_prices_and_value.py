from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.portfolio_view import portfolio_as_of
from finans.application.prices import set_manual_price
from finans.application.transactions import add_transaction, void_transaction
from finans.domain.models import DomainError, Instrument, InstrumentKind, Side, Transaction
from finans.ports.repositories import PriceWrite

D = Decimal
NOW = datetime(2026, 11, 24, tzinfo=UTC)
TTE = Instrument("TTE", InstrumentKind.TEFAS_YAT, "hisse")
ALTIN = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")


@pytest.fixture
def uow(migrated_db: Path) -> Iterator[SqliteUnitOfWork]:
    with SqliteUnitOfWork(migrated_db) as work:
        work.instruments.sync([TTE, ALTIN])
        yield work


def _price(uow: SqliteUnitOfWork, day: str, price: str) -> PriceWrite:
    return set_manual_price(uow, "ALTIN_GR", date.fromisoformat(day), D(price), now=NOW)


def _trade(uow: SqliteUnitOfWork, day: str, side: Side, units: str, price: str) -> int:
    tx = Transaction("ALTIN_GR", date.fromisoformat(day), side, D(units), D(price))
    return add_transaction(uow, tx, ref=None, note=None, now=NOW)


def test_manual_price_insert_unchanged_and_revision(uow: SqliteUnitOfWork) -> None:
    assert _price(uow, "2026-03-01", "3300") == PriceWrite("inserted")
    assert _price(uow, "2026-03-01", "3300.00") == PriceWrite("unchanged")
    assert _price(uow, "2026-03-01", "3310") == PriceWrite("revised", previous=D(3300))


def test_manual_price_is_only_for_manual_instruments(uow: SqliteUnitOfWork) -> None:
    with pytest.raises(DomainError, match=r"TTE.*elle girilemez"):
        set_manual_price(uow, "TTE", date(2026, 3, 1), D(10), now=NOW)
    with pytest.raises(DomainError, match="YOK tanımlı değil"):
        set_manual_price(uow, "YOK", date(2026, 3, 1), D(10), now=NOW)
    with pytest.raises(DomainError, match="fiyat"):
        _price(uow, "2026-03-01", "0")


def test_portfolio_as_of_any_date(uow: SqliteUnitOfWork) -> None:
    _trade(uow, "2026-01-05", Side.BUY, "10", "3000")
    _trade(uow, "2026-02-10", Side.SELL, "2", "3200")
    wrong = _trade(uow, "2026-02-11", Side.BUY, "100", "1")
    void_transaction(uow, wrong, reason="yanlış giriş", now=NOW)
    _price(uow, "2026-01-31", "3100")
    _price(uow, "2026-03-01", "3300")

    january = portfolio_as_of(uow, date(2026, 2, 1))
    (holding,) = january.valuation.holdings
    assert (holding.units, holding.value, holding.price and holding.price.price_date) == (
        D(10),
        D(31000),
        date(2026, 1, 31),
    )
    assert january.simple_return == D(31000) / D(30000) - 1
    assert january.realized_pnl == D(0)

    march = portfolio_as_of(uow, date(2026, 3, 10))
    assert march.valuation.total_value == D(8) * D(3300)
    assert march.realized_pnl == D(2) * D(3200) - D(6000)


def test_missing_prices_are_listed(uow: SqliteUnitOfWork) -> None:
    _trade(uow, "2026-01-05", Side.BUY, "10", "3000")
    view = portfolio_as_of(uow, date(2026, 1, 6))
    assert view.valuation.missing_prices == ("ALTIN_GR",)
    assert view.simple_return is None
