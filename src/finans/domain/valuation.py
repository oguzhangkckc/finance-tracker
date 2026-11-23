from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finans.domain.models import ZERO, DomainError, PricePoint
from finans.domain.numeric import in_domain_context
from finans.domain.positions import PositionBook


class PriceHistory:
    def __init__(self, points: Iterable[PricePoint]) -> None:
        grouped: dict[str, dict[date, PricePoint]] = defaultdict(dict)
        for point in points:
            by_date = grouped[point.instrument]
            if point.price_date in by_date:
                raise DomainError(f"{point.instrument} için {point.price_date} günü iki fiyat var")
            by_date[point.price_date] = point
        self._points = {
            instrument: [by_date[d] for d in sorted(by_date)]
            for instrument, by_date in grouped.items()
        }
        self._dates = {
            instrument: [p.price_date for p in points]
            for instrument, points in self._points.items()
        }

    def as_of(self, instrument: str, on: date) -> PricePoint | None:
        dates = self._dates.get(instrument)
        if not dates:
            return None
        index = bisect_right(dates, on)
        return self._points[instrument][index - 1] if index else None


@dataclass(frozen=True, slots=True)
class Holding:
    instrument: str
    units: Decimal
    cost: Decimal
    price: PricePoint | None
    value: Decimal | None


@dataclass(frozen=True, slots=True)
class Valuation:
    on: date
    holdings: tuple[Holding, ...]
    total_value: Decimal
    priced_cost: Decimal

    @property
    def missing_prices(self) -> tuple[str, ...]:
        return tuple(h.instrument for h in self.holdings if h.price is None)


@in_domain_context
def value_book(book: PositionBook, prices: PriceHistory, on: date) -> Valuation:
    holdings: list[Holding] = []
    for instrument in book.instruments():
        units = book.units_of(instrument)
        price = prices.as_of(instrument, on)
        holdings.append(
            Holding(
                instrument=instrument,
                units=units,
                cost=book.open_cost(instrument),
                price=price,
                value=None if price is None else units * price.price,
            )
        )
    return Valuation(
        on=on,
        holdings=tuple(holdings),
        total_value=sum((h.value for h in holdings if h.value is not None), ZERO),
        priced_cost=sum((h.cost for h in holdings if h.price is not None), ZERO),
    )
