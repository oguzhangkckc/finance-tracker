from dataclasses import dataclass
from datetime import date
from decimal import Decimal

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
