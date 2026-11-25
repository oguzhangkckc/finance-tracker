"""Değer geçmişi grafiğinin katkı çizgileri (K-129): net katkı ve enflasyona göre güncellenmiş
katkı. Referans değerler elle, 28 basamakla hesaplandı."""

from datetime import date
from decimal import Decimal

import pytest

from finans.domain.history import (
    cpi_is_estimated,
    inflation_adjusted_contribution,
    monthly_net_contributions,
    net_contribution,
    weekly_days,
)
from finans.domain.inflation import CpiSeries
from finans.domain.models import CashFlow, CpiPoint, DomainError, YearMonth

D = Decimal
SERIES = CpiSeries(
    [
        CpiPoint(YearMonth(2026, 9), D(100)),
        CpiPoint(YearMonth(2026, 10), D(102)),
        CpiPoint(YearMonth(2026, 11), D(103)),
    ]
)
# Alış 1000 TL (komisyon dahil), satıştan kalan 200 TL (komisyon düşülmüş), alış 500 TL.
FLOWS = [
    CashFlow(date(2026, 10, 15), D(-1000)),
    CashFlow(date(2026, 11, 10), D(200)),
    CashFlow(date(2026, 11, 20), D(-500)),
]


@pytest.mark.parametrize(
    ("on", "expected"),
    [(date(2026, 10, 1), D(0)), (date(2026, 11, 15), D(800)), (date(2026, 11, 30), D(1300))],
)
def test_net_contribution_is_buys_and_fees_minus_what_sales_returned(
    on: date, expected: Decimal
) -> None:
    assert net_contribution(FLOWS, on=on) == expected


def test_each_contribution_is_carried_to_the_week_by_the_k15_reference_month() -> None:
    # 7 Aralık'ın referans ayı Kasım (103). 15 Ekim'in Eylül (100), 10 ve 20 Kasım'ın Ekim (102):
    # 1000 × 103/100 - 200 × 103/102 = 828,0392156862745098039215686
    # 500 × 103/102 eklenince 1332,941176470588235294117647
    assert inflation_adjusted_contribution(FLOWS[:2], SERIES, on=date(2026, 12, 7)) == D(
        "828.0392156862745098039215686"
    )
    assert inflation_adjusted_contribution(FLOWS, SERIES, on=date(2026, 12, 7)) == D(
        "1332.941176470588235294117647"
    )


def test_only_contributions_up_to_the_day_count() -> None:
    # 15 Kasım'ın referans ayı Ekim (102): 1000 × 102/100 - 200 × 102/102 = 820
    assert inflation_adjusted_contribution(FLOWS, SERIES, on=date(2026, 11, 15)) == D(820)


def test_a_week_whose_cpi_is_not_out_yet_uses_the_last_one_and_is_marked() -> None:
    later = date(2027, 1, 20)

    assert cpi_is_estimated(SERIES, on=later)
    assert not cpi_is_estimated(SERIES, on=date(2026, 12, 7))
    assert inflation_adjusted_contribution(FLOWS, SERIES, on=later) == D(
        "1332.941176470588235294117647"
    )


def test_a_contribution_before_the_series_cannot_be_carried() -> None:
    early = [CashFlow(date(2026, 8, 1), D(-100))]

    with pytest.raises(DomainError, match="serinin başlangıcından"):
        inflation_adjusted_contribution(early, SERIES, on=date(2026, 12, 7))


@pytest.mark.parametrize(
    ("first", "last", "expected"),
    [
        (
            date(2026, 11, 2),
            date(2026, 11, 25),
            [date(2026, 11, 4), date(2026, 11, 11), date(2026, 11, 18), date(2026, 11, 25)],
        ),
        (date(2026, 11, 25), date(2026, 11, 25), [date(2026, 11, 25)]),
        (date(2026, 11, 26), date(2026, 11, 25), []),
    ],
)
def test_weekly_points_end_on_the_last_day(first: date, last: date, expected: list[date]) -> None:
    assert weekly_days(first, last) == expected


def test_monthly_net_contribution_counts_every_requested_month() -> None:
    months = [YearMonth(2026, 9), YearMonth(2026, 10), YearMonth(2026, 11)]

    assert monthly_net_contributions(FLOWS, months) == {
        YearMonth(2026, 9): D(0),
        YearMonth(2026, 10): D(1000),
        YearMonth(2026, 11): D(300),
    }
