from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.paper import NoPriceError, PaperTrade, paper_buy, paper_sell
from finans.domain.models import DomainError, Instrument, InstrumentKind, PricePoint

D = Decimal
NOW = datetime(2026, 6, 20, 9, 0, tzinfo=UTC)
XHT = Instrument("XHT", InstrumentKind.TEFAS_YAT, "hisse")
XBE = Instrument("XBE", InstrumentKind.TEFAS_EMK, "hisse")


@pytest.fixture
def uow(migrated_db: Path) -> Iterator[SqliteUnitOfWork]:
    with SqliteUnitOfWork(migrated_db) as work:
        work.instruments.sync([XHT, XBE])
        for day, price in ((date(2026, 6, 12), "1.230000"), (date(2026, 6, 15), "1.234567")):
            work.prices.upsert(PricePoint("XHT", day, D(price), "tefas"), fetched_at=NOW)
        work.prices.upsert(PricePoint("XBE", date(2026, 6, 15), D(2), "tefas"), fetched_at=NOW)
        yield work


def test_buy_uses_the_stored_price_of_that_day_and_keeps_the_leftover_out(
    uow: SqliteUnitOfWork,
) -> None:
    trade = paper_buy(uow, code="XHT", amount=D(5000), day=date(2026, 6, 15), fee=D(0), now=NOW)

    assert trade == PaperTrade(
        1, "XHT", date(2026, 6, 15), D(4050), D("1.234567"), D("4999.99635"), D("0.00365")
    )
    [stored] = uow.transactions.list()
    assert stored.transaction.unit_price == D("1.234567")
    assert stored.transaction.unit_price.as_tuple().exponent == -6
    assert stored.transaction.units == D(4050)


def test_a_day_without_a_price_is_refused_and_the_nearest_days_are_named(
    uow: SqliteUnitOfWork,
) -> None:
    with pytest.raises(NoPriceError) as caught:
        paper_buy(uow, code="XHT", amount=D(5000), day=date(2026, 6, 13), fee=D(0), now=NOW)

    assert str(caught.value) == (
        "XHT için 2026-06-13 tarihli fiyat yok; fiyat uydurulmaz, gün kaydırılmaz. "
        "En yakın fiyatlı günler: önce 2026-06-12, sonra 2026-06-15."
    )
    assert uow.transactions.list() == []


def test_amount_entry_is_refused_for_pension_funds(uow: SqliteUnitOfWork) -> None:
    with pytest.raises(DomainError, match="desteklenmiyor"):
        paper_buy(uow, code="XBE", amount=D(5000), day=date(2026, 6, 15), fee=D(0), now=NOW)


def test_unknown_code_is_refused(uow: SqliteUnitOfWork) -> None:
    with pytest.raises(DomainError, match="XZZ tanımlı değil"):
        paper_buy(uow, code="XZZ", amount=D(5000), day=date(2026, 6, 15), fee=D(0), now=NOW)


def test_sell_uses_the_stored_price_and_oversell_is_still_refused(uow: SqliteUnitOfWork) -> None:
    paper_buy(uow, code="XHT", amount=D(1000), day=date(2026, 6, 12), fee=D(0), now=NOW)

    sold = paper_sell(uow, code="XHT", units=D(100), day=date(2026, 6, 15), now=NOW)

    assert (sold.units, sold.price, sold.spent) == (D(100), D("1.234567"), D("123.4567"))
    with pytest.raises(DomainError):
        paper_sell(uow, code="XHT", units=D(10000), day=date(2026, 6, 15), now=NOW)
