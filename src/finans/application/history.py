"""Değer geçmişi ve aylık katkı (K-129). Her istekte hesaplanır, önbellek yoktur; eksik fiyat ya
da TÜFE yanlış bir çizgi değil boşluk olarak döner."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finans.application.settings import planned_contributions
from finans.domain.history import (
    cpi_is_estimated,
    inflation_adjusted_contribution,
    monthly_net_contributions,
    net_contribution,
    weekly_days,
)
from finans.domain.inflation import CpiSeries, reference_period
from finans.domain.models import DomainError, YearMonth
from finans.domain.portfolio import PortfolioConfig
from finans.domain.positions import build_positions
from finans.domain.valuation import PriceHistory, value_book
from finans.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ValuePoint:
    day: date
    value: Decimal | None
    invested: Decimal
    adjusted: Decimal | None
    cpi_period: YearMonth | None
    estimated: bool


@dataclass(frozen=True, slots=True)
class MonthContribution:
    month: YearMonth
    invested: Decimal
    planned: Decimal | None


def _series(uow: UnitOfWork, name: str) -> CpiSeries | None:
    points = uow.cpi.points(name)
    return CpiSeries(points) if points else None


def value_history(uow: UnitOfWork, *, end: date, cpi_series: str) -> list[ValuePoint]:
    transactions = [stored.transaction for stored in uow.transactions.list(until=end)]
    if not transactions:
        return []
    prices = PriceHistory(uow.prices.history(until=end))
    series = _series(uow, cpi_series)
    flows = [tx.cash_flow() for tx in transactions]
    points = []
    for day in weekly_days(min(tx.trade_date for tx in transactions), end):
        valuation = value_book(build_positions(transactions, as_of=day), prices, day)
        adjusted, period, estimated = None, None, False
        if series is not None:
            try:
                adjusted = inflation_adjusted_contribution(flows, series, on=day)
                period = reference_period(day, series)
                estimated = cpi_is_estimated(series, on=day)
            except DomainError:
                adjusted, period = None, None
        points.append(
            ValuePoint(
                day,
                None if valuation.missing_prices else valuation.total_value,
                net_contribution(flows, on=day),
                adjusted,
                period,
                estimated,
            )
        )
    return points


def monthly_contributions(
    uow: UnitOfWork, toml: PortfolioConfig, *, end: date, months: int
) -> list[MonthContribution]:
    """Planlanan katkı her ayın maaş gününde yürürlükte olan ayardan (K-127)."""
    last = YearMonth.of(end)
    periods = [last.shift(offset) for offset in range(1 - months, 1)]
    flows = [stored.transaction.cash_flow() for stored in uow.transactions.list(until=end)]
    totals = monthly_net_contributions(flows, periods)
    planned = planned_contributions(uow, toml, periods)
    return [MonthContribution(period, totals[period], planned[period]) for period in periods]
