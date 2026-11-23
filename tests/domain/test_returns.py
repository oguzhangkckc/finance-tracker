from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finans.domain.inflation import CpiSeries, fisher_real
from finans.domain.models import (
    CashFlow,
    CpiPoint,
    DomainError,
    PricePoint,
    Side,
    Transaction,
    YearMonth,
)
from finans.domain.positions import Lot
from finans.domain.returns import (
    LOWER_BOUND,
    UPPER_BOUND,
    PeriodReturn,
    fund_twr,
    lot_real_return,
    money_weighted_return,
    net_present_value,
    portfolio_cash_flows,
    real_cash_flows,
    simple_return,
    solve_irr,
)
from tests.support.decimals import is_close

D = Decimal


def _flows(*pairs: tuple[str, str]) -> list[CashFlow]:
    return [CashFlow(date.fromisoformat(day), D(amount)) for day, amount in pairs]


# XIRR referansları: kullanıcının Excel XIRR formülüyle (gün/365) ürettiği vakalar.
# Değerler dış incelemede mpmath ile 50 basamak hesaplandı; Excel doğrulaması kullanıcıda.
V1 = _flows(("2025-01-02", "-10000"), ("2026-01-02", "13000"))
V2 = _flows(*[(f"2025-{month:02d}-05", "-1000") for month in range(1, 13)], ("2026-01-05", "13500"))
V3 = _flows(
    ("2024-03-15", "-50000"),
    ("2024-09-10", "20000"),
    ("2025-02-03", "-15000"),
    ("2026-01-15", "62000"),
)
V4 = _flows(("2024-06-03", "-20000"), ("2025-01-02", "-10000"), ("2026-01-02", "24000"))
V5 = _flows(("2023-12-15", "-10000"), ("2024-02-29", "-5000"), ("2025-03-03", "18500"))
V6 = _flows(("2024-01-10", "-100000"), ("2026-01-10", "250000"))
V7 = _flows(("2025-06-02", "-10000"), ("2025-09-01", "-5000"), ("2025-12-01", "15900"))
V8 = _flows(("2025-01-01", "-100"), ("2026-01-01", "230"), ("2027-01-01", "-132"))

V7_XIRR = D("0.150165114319938203")
V7_PERIOD_RETURN = D("0.0722519933908779519")
V8_ROOTS = (D("0.1"), D("0.2"))


@pytest.mark.parametrize(
    ("flows", "expected"),
    [
        (V1, "0.3"),
        (V2, "0.237537840352023988"),
        (V3, "0.198190723306479927"),
        (V4, "-0.149016276081497630"),
        (V5, "0.200451794484474938"),
        (V6, "0.580148181009551500"),
    ],
    ids=["V1", "V2", "V3", "V4", "V5", "V6"],
)
def test_annual_money_weighted_return_matches_excel(flows: list[CashFlow], expected: str) -> None:
    result = money_weighted_return(flows)
    assert result is not None
    assert result.annualized
    assert is_close(result.rate, D(expected)), result.rate


def test_v7_annual_xirr_matches_excel() -> None:
    rate = solve_irr(V7, day_count=365, guess=D("0.1"))
    assert rate is not None
    assert is_close(rate, V7_XIRR), rate


def test_v7_period_return_is_the_same_both_ways() -> None:
    period = money_weighted_return(V7)
    assert period is not None
    assert (period.annualized, period.days) == (False, 182)

    annual = solve_irr(V7, day_count=365, guess=D("0.1"))
    assert annual is not None
    via_annual = (1 + annual) ** (D(182) / D(365)) - 1

    assert is_close(period.rate, via_annual), (period.rate, via_annual)
    assert is_close(period.rate, V7_PERIOD_RETURN), period.rate


def test_v8_root_choice_is_deterministic_and_a_real_root() -> None:
    first = money_weighted_return(V8)
    assert first is not None
    assert any(is_close(first.rate, root) for root in V8_ROOTS), first.rate
    assert money_weighted_return(V8) == first
    assert money_weighted_return(list(reversed(V8))) == first


def test_exactly_one_year_is_annualized() -> None:
    result = money_weighted_return(V1)
    assert result is not None
    assert result == PeriodReturn(rate=result.rate, annualized=True, days=365)


def test_shorter_than_a_year_is_a_period_return() -> None:
    result = money_weighted_return(_flows(("2025-01-02", "-100"), ("2026-01-01", "110")))
    assert result is not None
    assert (result.annualized, result.days) == (False, 364)
    assert is_close(result.rate, D("0.1"))


@pytest.mark.parametrize(
    "flows",
    [
        [],
        _flows(("2026-01-02", "-100"), ("2026-01-02", "100")),
        _flows(("2025-01-02", "-100"), ("2026-01-02", "-50")),
        _flows(("2025-01-02", "100"), ("2026-01-02", "50")),
    ],
    ids=["bos", "sifir-gun", "hep-negatif", "hep-pozitif"],
)
def test_not_computable(flows: list[CashFlow]) -> None:
    assert money_weighted_return(flows) is None


def test_portfolio_cash_flows_follow_the_sign_rule() -> None:
    transactions = [
        Transaction("AAA", date(2025, 1, 2), Side.BUY, D(100), D(100), D(5)),
        Transaction("AAA", date(2025, 6, 2), Side.SELL, D(20), D(120), D(1)),
        Transaction("AAA", date(2026, 2, 1), Side.BUY, D(1), D(1)),
    ]
    flows = portfolio_cash_flows(transactions, terminal_value=D(11000), on=date(2026, 1, 2))
    assert flows == _flows(
        ("2025-01-02", "-10005"), ("2025-06-02", "2399"), ("2026-01-02", "11000")
    )


CPI_100_TO_120 = CpiSeries(
    [CpiPoint(YearMonth(2024, 12), D(100)), CpiPoint(YearMonth(2025, 12), D(120))]
)


def test_real_xirr_equals_fisher_and_lot_real_return_for_two_flows_over_one_year() -> None:
    on = date(2026, 1, 2)
    nominal = money_weighted_return(V1)
    real_flows = real_cash_flows(V1, CPI_100_TO_120, on=on)
    real = money_weighted_return(real_flows)
    assert nominal is not None
    assert real is not None

    assert real_flows[-1] == V1[-1]
    assert is_close(real.rate, D("1.30") / D("1.20") - 1)
    assert is_close(real.rate, fisher_real(nominal.rate, D("0.20")))

    lot = Lot("AAA", date(2025, 1, 2), D(100), D(100), D(10000))
    assert is_close(lot_real_return(lot, D(13000), CPI_100_TO_120, on=on), real.rate)


def test_new_lot_real_return_equals_nominal() -> None:
    lot = Lot("AAA", date(2026, 1, 5), D(10), D(10), D(1000))
    assert lot_real_return(lot, D(1100), CPI_100_TO_120, on=date(2026, 1, 20)) == D("0.1")


def test_partially_sold_lot_uses_remaining_units_and_cost() -> None:
    lot = Lot("AAA", date(2025, 1, 2), D(100), D(60), D(6000))
    value = D(60) * D(130)
    assert is_close(
        lot_real_return(lot, value, CPI_100_TO_120, on=date(2026, 1, 2)), D("1.30") / D("1.20") - 1
    )


def test_simple_return() -> None:
    assert simple_return(D(1300), D(1000)) == D("0.3")
    assert simple_return(D(0), D(0)) is None


def test_fund_twr_is_the_price_ratio() -> None:
    start = PricePoint("AAA", date(2025, 1, 2), D(10), source="tefas")
    end = PricePoint("AAA", date(2025, 7, 1), D("12.5"), source="tefas")
    assert fund_twr(start, end) == D("0.25")
    with pytest.raises(DomainError):
        fund_twr(end, start)


@st.composite
def single_sign_change_flows(draw: st.DrawFn) -> list[CashFlow]:
    start = date(2024, 1, 1)
    offsets = sorted(draw(st.lists(st.integers(0, 900), min_size=1, max_size=8)))
    amounts = [-draw(st.decimals(min_value=D(1), max_value=D("1e6"), places=2)) for _ in offsets]
    end = offsets[-1] + draw(st.integers(min_value=30, max_value=900))
    multiple = draw(st.decimals(min_value=D("0.5"), max_value=D(3), places=3))
    terminal = -sum(amounts, D(0)) * multiple
    return [
        *(CashFlow(start + timedelta(days=o), a) for o, a in zip(offsets, amounts, strict=True)),
        CashFlow(start + timedelta(days=end), terminal),
    ]


@given(single_sign_change_flows())
def test_rate_is_within_a_billionth_of_a_root_and_none_only_outside_the_range(
    flows: list[CashFlow],
) -> None:
    days = (flows[-1].on - flows[0].on).days
    day_count = 365 if days >= 365 else days

    def npv(rate: Decimal) -> Decimal:
        return net_present_value(flows, rate, day_count=day_count)

    root_in_range = (npv(LOWER_BOUND) > 0) != (npv(UPPER_BOUND) > 0)
    result = money_weighted_return(flows)
    if not root_in_range:
        assert result is None
        return
    assert result is not None
    step = D("1e-9")
    assert npv(result.rate) == 0 or (npv(result.rate - step) > 0) != (npv(result.rate + step) > 0)


def test_bisection_fallback_finds_the_root_after_a_bad_guess() -> None:
    rate = solve_irr(V1, day_count=365, guess=D("9.9"))
    assert rate is not None
    assert is_close(rate, D("0.3"))


def test_bisection_fallback_gives_up_when_both_ends_have_the_same_sign() -> None:
    assert solve_irr(V8, day_count=365, guess=D("9.9")) is None
