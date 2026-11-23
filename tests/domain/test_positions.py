import random
from datetime import date, timedelta
from decimal import Decimal
from itertools import permutations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finans.domain.models import OversellError, Side, Transaction
from finans.domain.positions import Lot, PositionBook, RealizedSale, build_positions
from tests.support.decimals import is_close

D = Decimal
AS_OF = date(2026, 12, 31)
DAY_1 = date(2026, 1, 5)
DAY_2 = date(2026, 2, 9)
DAY_3 = date(2026, 3, 9)


def _tx(
    side: Side, day: date, units: str, price: str, fee: str = "0", instrument: str = "AAA"
) -> Transaction:
    return Transaction(instrument, day, side, D(units), D(price), D(fee))


def buy(day: date, units: str, price: str, fee: str = "0", instrument: str = "AAA") -> Transaction:
    return _tx(Side.BUY, day, units, price, fee, instrument)


def sell(day: date, units: str, price: str, fee: str = "0", instrument: str = "AAA") -> Transaction:
    return _tx(Side.SELL, day, units, price, fee, instrument)


def _canonical(book: PositionBook) -> tuple[tuple[Lot, ...], list[RealizedSale]]:
    return book.lots, sorted(
        book.realized, key=lambda s: (s.sold_on, s.instrument, s.units, s.proceeds, s.cost)
    )


def test_buy_creates_lot_with_fee_in_cost() -> None:
    book = build_positions([buy(DAY_1, "10", "100", fee="5")], as_of=AS_OF)
    assert book.lots == (Lot("AAA", DAY_1, D(10), D(10), D(1005)),)
    assert book.realized == ()


def test_full_sell_closes_lot_and_realizes_profit_net_of_fees() -> None:
    book = build_positions(
        [buy(DAY_1, "10", "100", fee="5"), sell(DAY_2, "10", "120", fee="6")], as_of=AS_OF
    )
    assert book.lots == ()
    assert book.realized == (RealizedSale("AAA", DAY_2, D(10), proceeds=D(1194), cost=D(1005)),)
    assert book.realized_pnl() == D(189)


def test_partial_sell_keeps_cost_proportional_to_remaining_units() -> None:
    book = build_positions([buy(DAY_1, "10", "100", fee="5"), sell(DAY_2, "4", "120")], as_of=AS_OF)
    assert book.lots == (Lot("AAA", DAY_1, D(10), D(6), D("603")),)
    assert book.realized[0].cost == D("402")


def test_fifo_consumes_oldest_lot_first() -> None:
    book = build_positions(
        [buy(DAY_1, "10", "100"), buy(DAY_2, "10", "200"), sell(DAY_3, "15", "300")], as_of=AS_OF
    )
    assert book.lots == (Lot("AAA", DAY_2, D(10), D(5), D(1000)),)
    assert book.realized[0].cost == D(2000)


def test_instruments_are_tracked_separately() -> None:
    book = build_positions(
        [
            buy(DAY_1, "10", "100"),
            buy(DAY_1, "3", "50", instrument="BBB"),
            sell(DAY_2, "1", "60", instrument="BBB"),
        ],
        as_of=AS_OF,
    )
    assert book.instruments() == ("AAA", "BBB")
    assert book.units_of("AAA") == D(10)
    assert book.units_of("BBB") == D(2)
    assert book.open_cost("BBB") == D(100)
    assert book.open_cost() == D(1100)


def test_overselling_is_rejected() -> None:
    with pytest.raises(OversellError, match="AAA"):
        build_positions([buy(DAY_1, "5", "100"), sell(DAY_2, "6", "100")], as_of=AS_OF)


def test_transactions_after_as_of_are_ignored() -> None:
    book = build_positions([buy(DAY_1, "5", "100"), sell(DAY_3, "5", "100")], as_of=DAY_2)
    assert book.units_of("AAA") == D(5)
    assert book.realized == ()


def test_same_day_sell_entered_before_buy_is_processed_after_buys() -> None:
    book = build_positions([sell(DAY_1, "4", "110"), buy(DAY_1, "10", "100")], as_of=AS_OF)
    assert book.units_of("AAA") == D(6)


def test_same_day_buys_merge_into_one_lot() -> None:
    book = build_positions(
        [buy(DAY_1, "10", "100", fee="1"), buy(DAY_1, "10", "110", fee="1")], as_of=AS_OF
    )
    assert book.lots == (Lot("AAA", DAY_1, D(20), D(20), D(2102)),)


def test_same_day_sells_share_consumed_cost_by_units() -> None:
    book = build_positions(
        [
            buy(DAY_1, "10", "90"),
            buy(DAY_2, "10", "100"),
            buy(DAY_2, "10", "110", fee="2"),
            sell(DAY_2, "15", "120", fee="1"),
            sell(DAY_2, "5", "130"),
        ],
        as_of=AS_OF,
    )
    costs = {sale.units: sale.cost for sale in book.realized}
    assert costs == {D(15): D("1463.25"), D(5): D("487.75")}
    assert book.lots == (Lot("AAA", DAY_2, D(20), D(10), D(1051)),)


def test_result_is_independent_of_input_order() -> None:
    transactions = [
        buy(DAY_1, "10", "90"),
        buy(DAY_2, "10", "100"),
        buy(DAY_2, "10", "110", fee="2"),
        sell(DAY_2, "15", "120", fee="1"),
        sell(DAY_2, "5", "130"),
    ]
    expected = _canonical(build_positions(transactions, as_of=AS_OF))
    for ordering in permutations(transactions):
        assert _canonical(build_positions(ordering, as_of=AS_OF)) == expected


@st.composite
def histories(draw: st.DrawFn) -> list[Transaction]:
    units = st.decimals(min_value=D("0.0001"), max_value=D(1000), places=4)
    prices = st.decimals(min_value=D("0.000001"), max_value=D(500), places=6)
    fees = st.decimals(min_value=D(0), max_value=D(10), places=2)
    transactions: list[Transaction] = []
    held = D(0)
    day = date(2025, 1, 1)
    for _ in range(draw(st.integers(min_value=1, max_value=12))):
        day += timedelta(days=draw(st.integers(min_value=0, max_value=40)))
        for _ in range(draw(st.integers(min_value=0, max_value=3))):
            bought = draw(units)
            transactions.append(buy(day, str(bought), str(draw(prices)), str(draw(fees))))
            held += bought
        for _ in range(draw(st.integers(min_value=0, max_value=2))):
            if held <= 0:
                break
            sold = draw(st.decimals(min_value=D("0.0001"), max_value=held, places=4))
            transactions.append(sell(day, str(sold), str(draw(prices)), str(draw(fees))))
            held -= sold
    return transactions


@given(histories())
def test_units_are_conserved(transactions: list[Transaction]) -> None:
    book = build_positions(transactions, as_of=AS_OF)
    bought = sum((t.units for t in transactions if t.side is Side.BUY), D(0))
    sold = sum((t.units for t in transactions if t.side is Side.SELL), D(0))
    assert book.units_of("AAA") == bought - sold


@given(histories())
def test_cost_is_conserved(transactions: list[Transaction]) -> None:
    book = build_positions(transactions, as_of=AS_OF)
    paid = sum((t.units * t.unit_price + t.fee for t in transactions if t.side is Side.BUY), D(0))
    realized_cost = sum((sale.cost for sale in book.realized), D(0))
    assert is_close(book.open_cost() + realized_cost, paid, rel_tol=D("1e-20"), abs_tol=D("1e-20"))


@given(histories(), st.randoms(use_true_random=False))
def test_input_order_does_not_change_the_result(
    transactions: list[Transaction], rng: random.Random
) -> None:
    shuffled = transactions.copy()
    rng.shuffle(shuffled)
    assert _canonical(build_positions(shuffled, as_of=AS_OF)) == _canonical(
        build_positions(transactions, as_of=AS_OF)
    )
