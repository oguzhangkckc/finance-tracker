from datetime import date
from decimal import Decimal

import pytest

from finans.domain.models import (
    CashFlow,
    CpiPoint,
    DomainError,
    Instrument,
    InstrumentKind,
    PricePoint,
    Side,
    Transaction,
    YearMonth,
)


def _tx(
    side: Side = Side.BUY,
    units: str = "10",
    unit_price: str = "100",
    fee: str = "5",
) -> Transaction:
    return Transaction(
        instrument="AAA",
        trade_date=date(2026, 3, 2),
        side=side,
        units=Decimal(units),
        unit_price=Decimal(unit_price),
        fee=Decimal(fee),
    )


class TestYearMonth:
    def test_of_date(self) -> None:
        assert YearMonth.of(date(2026, 1, 15)) == YearMonth(2026, 1)

    def test_previous_crosses_year_boundary(self) -> None:
        assert YearMonth(2026, 1).previous() == YearMonth(2025, 12)

    @pytest.mark.parametrize(
        ("months", "expected"),
        [
            (0, YearMonth(2025, 12)),
            (1, YearMonth(2026, 1)),
            (13, YearMonth(2027, 1)),
            (-12, YearMonth(2024, 12)),
            (-23, YearMonth(2024, 1)),
        ],
    )
    def test_shift(self, months: int, expected: YearMonth) -> None:
        assert YearMonth(2025, 12).shift(months) == expected

    def test_text_round_trip(self) -> None:
        assert str(YearMonth(2025, 3)) == "2025-03"
        assert YearMonth.parse("2025-03") == YearMonth(2025, 3)

    def test_ordering(self) -> None:
        assert YearMonth(2025, 12) < YearMonth(2026, 1) < YearMonth(2026, 2)

    @pytest.mark.parametrize("month", [0, 13])
    def test_invalid_month_is_rejected(self, month: int) -> None:
        with pytest.raises(DomainError, match="ay"):
            YearMonth(2025, month)

    @pytest.mark.parametrize("text", ["2025-3", "2025/03", "25-03", "2025-13"])
    def test_invalid_text_is_rejected(self, text: str) -> None:
        with pytest.raises(DomainError):
            YearMonth.parse(text)


class TestTransaction:
    def test_buy_cash_flow_is_negative_and_includes_fee(self) -> None:
        assert _tx(Side.BUY).cash_flow() == CashFlow(date(2026, 3, 2), Decimal("-1005"))

    def test_sell_cash_flow_is_positive_net_of_fee(self) -> None:
        assert _tx(Side.SELL).cash_flow() == CashFlow(date(2026, 3, 2), Decimal("995"))

    @pytest.mark.parametrize(
        ("field", "kwargs"),
        [
            ("units", {"units": "0"}),
            ("units", {"units": "-1"}),
            ("unit_price", {"unit_price": "0"}),
            ("fee", {"fee": "-0.01"}),
            ("units", {"units": "NaN"}),
            ("unit_price", {"unit_price": "Infinity"}),
        ],
    )
    def test_invalid_amounts_are_rejected(self, field: str, kwargs: dict[str, str]) -> None:
        with pytest.raises(DomainError, match=field):
            _tx(**kwargs)  # type: ignore[arg-type]

    def test_non_decimal_amount_is_rejected(self) -> None:
        with pytest.raises(DomainError, match="Decimal"):
            Transaction("AAA", date(2026, 3, 2), Side.BUY, 10, Decimal(1))  # type: ignore[arg-type]


def test_instrument_requires_code() -> None:
    with pytest.raises(DomainError, match="kod"):
        Instrument(code=" ", kind=InstrumentKind.TEFAS_YAT, asset_class="hisse")


def test_price_must_be_positive() -> None:
    with pytest.raises(DomainError, match="fiyat"):
        PricePoint("AAA", date(2026, 3, 2), Decimal(0), source="tefas")


def test_cpi_index_must_be_positive() -> None:
    with pytest.raises(DomainError, match="endeks"):
        CpiPoint(YearMonth(2025, 12), Decimal("-1"))
