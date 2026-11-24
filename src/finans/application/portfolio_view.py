from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finans.domain.models import ZERO, Instrument
from finans.domain.positions import build_positions
from finans.domain.returns import simple_return
from finans.domain.valuation import PriceHistory, Valuation, value_book
from finans.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class PortfolioView:
    valuation: Valuation
    simple_return: Decimal | None
    realized_pnl: Decimal


def portfolio_as_of(uow: UnitOfWork, on: date) -> PortfolioView:
    transactions = [s.transaction for s in uow.transactions.list(until=on)]
    book = build_positions(transactions, as_of=on)
    valuation = value_book(book, PriceHistory(uow.prices.history(until=on)), on)
    return PortfolioView(
        valuation=valuation,
        simple_return=simple_return(valuation.total_value, valuation.priced_cost),
        realized_pnl=book.realized_pnl(),
    )


def instruments_by_code(uow: UnitOfWork) -> dict[str, Instrument]:
    return {s.instrument.code: s.instrument for s in uow.instruments.list(include_inactive=True)}


def in_allocation(code: str, instruments: Mapping[str, Instrument]) -> bool:
    return code not in instruments or instruments[code].allocation


def missing_in_allocation(valuation: Valuation, instruments: Mapping[str, Instrument]) -> list[str]:
    """Fiyatı olmayan dağılım içi varlıklar; varsa dağılım ve alarm hesaplanmaz (K-85, K-95)."""
    return [code for code in sorted(valuation.missing_prices) if in_allocation(code, instruments)]


def class_values(
    valuation: Valuation, instruments: Mapping[str, Instrument], targets: Mapping[str, Decimal]
) -> dict[str, Decimal]:
    values = dict.fromkeys(targets, ZERO)
    for holding in valuation.holdings:
        instrument = instruments.get(holding.instrument)
        if instrument is None or not instrument.allocation or holding.value is None:
            continue
        if instrument.asset_class in values:
            values[instrument.asset_class] += holding.value
    return values
