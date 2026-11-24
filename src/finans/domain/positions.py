from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finans.domain.models import ZERO, OversellError, Side, Transaction
from finans.domain.numeric import in_domain_context


@dataclass(frozen=True, slots=True)
class Lot:
    instrument: str
    acquired: date
    original_units: Decimal
    units: Decimal
    cost: Decimal


@dataclass(frozen=True, slots=True)
class RealizedSale:
    instrument: str
    sold_on: date
    units: Decimal
    proceeds: Decimal
    cost: Decimal

    @property
    @in_domain_context
    def pnl(self) -> Decimal:
        return self.proceeds - self.cost


@dataclass(frozen=True, slots=True)
class PositionBook:
    lots: tuple[Lot, ...]
    realized: tuple[RealizedSale, ...]

    def instruments(self) -> tuple[str, ...]:
        return tuple(sorted({lot.instrument for lot in self.lots}))

    def lots_of(self, instrument: str) -> tuple[Lot, ...]:
        return tuple(lot for lot in self.lots if lot.instrument == instrument)

    @in_domain_context
    def units_of(self, instrument: str) -> Decimal:
        return sum((lot.units for lot in self.lots_of(instrument)), ZERO)

    @in_domain_context
    def open_cost(self, instrument: str | None = None) -> Decimal:
        lots = self.lots if instrument is None else self.lots_of(instrument)
        return sum((lot.cost for lot in lots), ZERO)

    @in_domain_context
    def realized_pnl(self) -> Decimal:
        return sum((sale.pnl for sale in self.realized), ZERO)


@dataclass(slots=True)
class _OpenLot:
    acquired: date
    original_units: Decimal
    original_cost: Decimal
    units: Decimal

    def remaining_cost(self) -> Decimal:
        if self.units == self.original_units:
            return self.original_cost
        return self.original_cost * self.units / self.original_units


@in_domain_context
def build_positions(transactions: Iterable[Transaction], *, as_of: date) -> PositionBook:
    days: dict[tuple[date, str], list[Transaction]] = defaultdict(list)
    for tx in transactions:
        if tx.trade_date <= as_of:
            days[(tx.trade_date, tx.instrument)].append(tx)

    open_lots: dict[str, list[_OpenLot]] = defaultdict(list)
    realized: list[RealizedSale] = []
    for day, instrument in sorted(days):
        group = days[(day, instrument)]
        buys = [tx for tx in group if tx.side is Side.BUY]
        sells = [tx for tx in group if tx.side is Side.SELL]
        if buys:
            units = sum((tx.units for tx in buys), ZERO)
            cost = sum((tx.units * tx.unit_price + tx.fee for tx in buys), ZERO)
            open_lots[instrument].append(_OpenLot(day, units, cost, units))
        if sells:
            realized.extend(_sell(open_lots[instrument], instrument, day, sells))

    lots = tuple(
        Lot(instrument, lot.acquired, lot.original_units, lot.units, lot.remaining_cost())
        for instrument in sorted(open_lots)
        for lot in open_lots[instrument]
    )
    return PositionBook(lots, tuple(realized))


def _sell(
    lots: list[_OpenLot], instrument: str, day: date, sells: Sequence[Transaction]
) -> list[RealizedSale]:
    sold = sum((tx.units for tx in sells), ZERO)
    held = sum((lot.units for lot in lots), ZERO)
    if sold > held:
        raise OversellError(instrument, day, sold, held)
    consumed = _consume_fifo(lots, sold)
    return [
        RealizedSale(
            instrument=instrument,
            sold_on=day,
            units=tx.units,
            proceeds=tx.units * tx.unit_price - tx.fee,
            cost=consumed if tx.units == sold else consumed * tx.units / sold,
        )
        for tx in sells
    ]


def _consume_fifo(lots: list[_OpenLot], units: Decimal) -> Decimal:
    consumed = ZERO
    remaining = units
    while remaining > ZERO:
        lot = lots[0]
        before = lot.remaining_cost()
        if lot.units <= remaining:
            remaining -= lot.units
            consumed += before
            lots.pop(0)
        else:
            lot.units -= remaining
            consumed += before - lot.remaining_cost()
            remaining = ZERO
    return consumed
