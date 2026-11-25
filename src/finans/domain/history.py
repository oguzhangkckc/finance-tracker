"""Değer geçmişi grafiğinin katkı çizgileri (K-129). Net katkı alışların tutarı ve komisyonu eksi
satışlardan kalan tutardır, yani nakit akışlarının eksi toplamı. Enflasyona göre güncellenmiş katkı
her akışı K-15 referans ay kuralıyla (`deflator`) o günün TÜFE'sine taşır."""

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal

from finans.domain.inflation import CpiSeries, deflator
from finans.domain.models import ZERO, CashFlow, YearMonth
from finans.domain.numeric import in_domain_context

_WEEK = timedelta(days=7)


@in_domain_context
def net_contribution(flows: Iterable[CashFlow], *, on: date) -> Decimal:
    return -sum((flow.amount for flow in flows if flow.on <= on), ZERO)


@in_domain_context
def inflation_adjusted_contribution(
    flows: Iterable[CashFlow], series: CpiSeries, *, on: date
) -> Decimal:
    return -sum(
        (
            flow.amount * deflator(series, flow_date=flow.on, on=on)
            for flow in flows
            if flow.on <= on
        ),
        ZERO,
    )


@in_domain_context
def cpi_is_estimated(series: CpiSeries, *, on: date) -> bool:
    """O günün referans ayı henüz açıklanmadıysa K-15 son açıklanan dönemi kullanır."""
    return YearMonth.of(on).previous() > series.latest()


@in_domain_context
def weekly_days(first: date, last: date) -> list[date]:
    """Son günden geriye yedişer gün; grafik her zaman bugünü gösterir."""
    days: list[date] = []
    day = last
    while day >= first:
        days.append(day)
        day -= _WEEK
    return days[::-1]


@in_domain_context
def monthly_net_contributions(
    flows: Iterable[CashFlow], months: Sequence[YearMonth]
) -> dict[YearMonth, Decimal]:
    totals = dict.fromkeys(months, ZERO)
    for flow in flows:
        month = YearMonth.of(flow.on)
        if month in totals:
            totals[month] -= flow.amount
    return totals
