from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finans.domain.models import DomainError, InstrumentKind
from finans.domain.orders import (
    AmountSplit,
    payday_price_day,
    payday_window_end,
    units_for_amount,
)

D = Decimal
YAT = InstrumentKind.TEFAS_YAT


def test_units_are_whole_and_the_leftover_is_kept_out() -> None:
    assert units_for_amount(D(5000), D("1.234567"), YAT) == AmountSplit(
        units=D(4050), spent=D("4999.99635"), leftover=D("0.00365")
    )


def test_exact_division_leaves_nothing_over() -> None:
    assert units_for_amount(D(5000), D("1.25"), InstrumentKind.TEFAS_BYF) == AmountSplit(
        units=D(4000), spent=D("5000.00"), leftover=D("0.00")
    )


def test_a_quotient_rounded_up_at_28_digits_never_buys_more_than_the_amount() -> None:
    amount = D("2." + "9" * 30)

    split = units_for_amount(amount, D(1), YAT)

    assert split.units == D(2)
    assert split.spent <= amount


def test_amount_below_one_unit_is_rejected() -> None:
    with pytest.raises(DomainError, match="en az bir pay"):
        units_for_amount(D(1), D("1.5"), YAT)


@pytest.mark.parametrize("kind", [InstrumentKind.TEFAS_EMK, InstrumentKind.MANUAL])
def test_amount_entry_is_not_offered_for_pension_and_manual_assets(kind: InstrumentKind) -> None:
    with pytest.raises(DomainError, match="desteklenmiyor"):
        units_for_amount(D(5000), D(10), kind)


@pytest.mark.parametrize(("amount", "price"), [(D(0), D(1)), (D(-5), D(1)), (D(5), D(0))])
def test_amount_and_price_must_be_positive(amount: Decimal, price: Decimal) -> None:
    with pytest.raises(DomainError, match="sıfırdan büyük"):
        units_for_amount(amount, price, YAT)


@given(
    st.decimals(min_value=D(1), max_value=D("1e7"), places=2),
    st.decimals(min_value=D("0.000001"), max_value=D(1000), places=6),
)
def test_spending_never_exceeds_the_amount_and_the_leftover_buys_no_more(
    amount: Decimal, price: Decimal
) -> None:
    if amount < price:
        return
    split = units_for_amount(amount, price, YAT)
    assert split.units == split.units.to_integral_value()
    assert split.spent + split.leftover == amount
    assert D(0) <= split.leftover < price


def test_payday_price_is_the_first_priced_day_after_payday() -> None:
    days = [date(2026, 5, 15), date(2026, 5, 18), date(2026, 5, 19)]
    assert payday_price_day(date(2026, 5, 15), days) == date(2026, 5, 18)


def test_long_holidays_are_covered_by_a_ten_day_window() -> None:
    assert payday_window_end(date(2026, 5, 25)) == date(2026, 6, 4)
    assert payday_price_day(date(2026, 5, 25), [date(2026, 6, 4)]) == date(2026, 6, 4)
    assert payday_price_day(date(2026, 5, 25), [date(2026, 6, 5)]) is None
    assert payday_price_day(date(2026, 5, 25), []) is None
