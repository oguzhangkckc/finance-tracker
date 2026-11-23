from datetime import date
from decimal import Decimal

import pytest

from finans.domain.models import DomainError, PricePoint, Side, Transaction
from finans.domain.positions import build_positions
from finans.domain.valuation import Holding, PriceHistory, value_book

D = Decimal
FRIDAY = date(2026, 1, 2)
MONDAY = date(2026, 1, 5)
P_FRIDAY = PricePoint("AAA", FRIDAY, D("10"), source="tefas")
P_MONDAY = PricePoint("AAA", MONDAY, D("11"), source="tefas")


@pytest.fixture
def prices() -> PriceHistory:
    return PriceHistory([P_MONDAY, P_FRIDAY])


def test_as_of_uses_last_price_on_or_before_the_date(prices: PriceHistory) -> None:
    assert prices.as_of("AAA", date(2026, 1, 4)) == P_FRIDAY
    assert prices.as_of("AAA", MONDAY) == P_MONDAY
    assert prices.as_of("AAA", date(2026, 1, 1)) is None
    assert prices.as_of("ZZZ", MONDAY) is None


def test_two_prices_for_the_same_day_are_rejected() -> None:
    with pytest.raises(DomainError, match="AAA"):
        PriceHistory([P_FRIDAY, PricePoint("AAA", FRIDAY, D("12"), source="manual")])


def test_valuation_reports_value_price_date_and_missing_prices(prices: PriceHistory) -> None:
    book = build_positions(
        [
            Transaction("AAA", FRIDAY, Side.BUY, D(10), D(9)),
            Transaction("BBB", FRIDAY, Side.BUY, D(5), D(20)),
        ],
        as_of=date(2026, 1, 4),
    )
    valuation = value_book(book, prices, date(2026, 1, 4))

    assert valuation.holdings == (
        Holding("AAA", units=D(10), cost=D(90), price=P_FRIDAY, value=D(100)),
        Holding("BBB", units=D(5), cost=D(100), price=None, value=None),
    )
    assert valuation.total_value == D(100)
    assert valuation.priced_cost == D(90)
    assert valuation.missing_prices == ("BBB",)


def test_fully_sold_instrument_is_not_listed(prices: PriceHistory) -> None:
    book = build_positions(
        [
            Transaction("AAA", FRIDAY, Side.BUY, D(10), D(9)),
            Transaction("AAA", MONDAY, Side.SELL, D(10), D(11)),
        ],
        as_of=MONDAY,
    )
    valuation = value_book(book, prices, MONDAY)
    assert valuation.holdings == ()
    assert valuation.total_value == D(0)
