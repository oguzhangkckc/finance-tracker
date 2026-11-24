from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, Literal

from finans.domain.inflation import CpiSeries, deflator
from finans.domain.models import ZERO, CashFlow, DomainError, PricePoint, Transaction
from finans.domain.numeric import in_domain_context
from finans.domain.positions import Lot

YEAR_DAYS: Final = 365
LOWER_BOUND: Final = Decimal("-0.99")
UPPER_BOUND: Final = Decimal(10)
TOLERANCE: Final = Decimal("1e-10")
MAX_NEWTON_STEPS: Final = 100


@dataclass(frozen=True, slots=True)
class PeriodReturn:
    rate: Decimal
    annualized: bool
    days: int


@dataclass(frozen=True, slots=True)
class Unavailable:
    """K-44: "undefined" akış yok, işaret değişmiyor ya da D = 0; "out_of_range" kök yok."""

    reason: Literal["out_of_range", "undefined"]


@in_domain_context
def simple_return(value: Decimal, cost: Decimal) -> Decimal | None:
    if cost == ZERO:
        return None
    return value / cost - 1


@in_domain_context
def fund_twr(start: PricePoint, end: PricePoint) -> Decimal:
    if start.instrument != end.instrument:
        raise DomainError(f"TWR tek fon için hesaplanır: {start.instrument} ≠ {end.instrument}")
    if end.price_date < start.price_date:
        raise DomainError(f"Dönem sonu ({end.price_date}) başından ({start.price_date}) önce")
    return end.price / start.price - 1


@in_domain_context
def portfolio_cash_flows(
    transactions: Iterable[Transaction], *, terminal_value: Decimal, on: date
) -> list[CashFlow]:
    if terminal_value < ZERO:
        raise DomainError(f"Değerleme tutarı negatif olamaz: {terminal_value}")
    flows = [tx.cash_flow() for tx in transactions if tx.trade_date <= on]
    flows.append(CashFlow(on, terminal_value))
    return sorted(flows, key=lambda flow: flow.on)


@in_domain_context
def real_cash_flows(flows: Iterable[CashFlow], series: CpiSeries, *, on: date) -> list[CashFlow]:
    return [
        CashFlow(flow.on, flow.amount * deflator(series, flow_date=flow.on, on=on))
        for flow in flows
    ]


@in_domain_context
def lot_real_return(lot: Lot, value: Decimal, series: CpiSeries, *, on: date) -> Decimal:
    if lot.cost <= ZERO:
        raise DomainError(f"{lot.instrument} lotunun maliyeti sıfır; reel getiri hesaplanamaz")
    return (value / lot.cost) / deflator(series, flow_date=lot.acquired, on=on) - 1


@in_domain_context
def net_present_value(flows: Sequence[CashFlow], rate: Decimal, *, day_count: int) -> Decimal:
    start = min(flow.on for flow in flows)
    return sum(
        (flow.amount / (1 + rate) ** _exponent(flow, start, day_count) for flow in flows), ZERO
    )


@in_domain_context
def money_weighted_return(flows: Sequence[CashFlow]) -> PeriodReturn | Unavailable:
    if not flows or not _has_sign_change(flows):
        return Unavailable("undefined")
    days = (max(f.on for f in flows) - min(f.on for f in flows)).days
    if days == 0:
        return Unavailable("undefined")
    day_count = YEAR_DAYS if days >= YEAR_DAYS else days
    rate = solve_irr(flows, day_count=day_count, guess=_initial_guess(flows, day_count, days))
    if rate is None:
        return Unavailable("out_of_range")
    return PeriodReturn(rate=rate, annualized=days >= YEAR_DAYS, days=days)


@in_domain_context
def solve_irr(flows: Sequence[CashFlow], *, day_count: int, guess: Decimal) -> Decimal | None:
    if not _has_sign_change(flows):
        return None
    ordered = sorted(flows, key=lambda flow: (flow.on, flow.amount))
    newton = _newton(ordered, day_count, guess)
    return newton if newton is not None else _bisection(ordered, day_count)


def _has_sign_change(flows: Iterable[CashFlow]) -> bool:
    amounts = [flow.amount for flow in flows]
    return any(a > ZERO for a in amounts) and any(a < ZERO for a in amounts)


def _exponent(flow: CashFlow, start: date, day_count: int) -> Decimal:
    return Decimal((flow.on - start).days) / Decimal(day_count)


def _initial_guess(flows: Sequence[CashFlow], day_count: int, days: int) -> Decimal:
    inflow = sum((f.amount for f in flows if f.amount > ZERO), ZERO)
    outflow = -sum((f.amount for f in flows if f.amount < ZERO), ZERO)
    guess = (inflow / outflow) ** (Decimal(day_count) / Decimal(days)) - 1
    return min(max(guess, LOWER_BOUND), UPPER_BOUND)


def _npv_and_derivative(
    flows: Sequence[CashFlow], day_count: int, rate: Decimal
) -> tuple[Decimal, Decimal]:
    start = flows[0].on
    value = derivative = ZERO
    for flow in flows:
        exponent = _exponent(flow, start, day_count)
        discounted = flow.amount / (1 + rate) ** exponent
        value += discounted
        derivative -= exponent * discounted / (1 + rate)
    return value, derivative


def _newton(flows: Sequence[CashFlow], day_count: int, guess: Decimal) -> Decimal | None:
    rate = guess
    for _ in range(MAX_NEWTON_STEPS):
        value, derivative = _npv_and_derivative(flows, day_count, rate)
        if derivative == ZERO:
            return None
        step = value / derivative
        candidate = rate - step
        if not LOWER_BOUND <= candidate <= UPPER_BOUND:
            return None
        if abs(step) < TOLERANCE:
            return candidate
        rate = candidate
    return None


def _bisection(flows: Sequence[CashFlow], day_count: int) -> Decimal | None:
    low, high = LOWER_BOUND, UPPER_BOUND
    low_value, _ = _npv_and_derivative(flows, day_count, low)
    high_value, _ = _npv_and_derivative(flows, day_count, high)
    if (low_value > ZERO) == (high_value > ZERO):
        return None
    while high - low >= TOLERANCE:
        middle = (low + high) / 2
        middle_value, _ = _npv_and_derivative(flows, day_count, middle)
        if (middle_value > ZERO) == (low_value > ZERO):
            low, low_value = middle, middle_value
        else:
            high = middle
    return (low + high) / 2
