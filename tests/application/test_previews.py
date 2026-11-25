"""Önizleme kaydın aynısıdır ve hiçbir şey yazmaz (K-126)."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.paper import (
    PaperPlan,
    paper_buy,
    paper_sell,
    plan_paper_buy,
    plan_paper_sell,
)
from finans.application.previews import TradePreview, VoidPreview, preview_transaction, preview_void
from finans.application.transactions import (
    VoidBlockedError,
    add_transaction,
    digest,
    void_transaction,
)
from finans.domain.models import (
    DomainError,
    Instrument,
    InstrumentKind,
    PricePoint,
    Side,
    Transaction,
)

D = Decimal
NOW = datetime(2026, 6, 20, 9, 0, tzinfo=UTC)
TODAY = date(2026, 6, 20)
MONDAY = date(2026, 6, 15)
XHT = Instrument("XHT", InstrumentKind.TEFAS_YAT, "hisse")


@pytest.fixture
def uow(migrated_db: Path) -> Iterator[SqliteUnitOfWork]:
    with SqliteUnitOfWork(migrated_db) as work:
        work.instruments.sync([XHT])
        for day, price in ((date(2026, 6, 12), "1.230000"), (MONDAY, "1.234567")):
            work.prices.upsert(PricePoint("XHT", day, D(price), "tefas"), fetched_at=NOW)
        yield work


def _buy(units: str, price: str = "1.234567", day: date = MONDAY) -> Transaction:
    return Transaction("XHT", day, Side.BUY, D(units), D(price))


def test_a_dekont_preview_is_exactly_what_gets_written_and_writes_nothing(
    uow: SqliteUnitOfWork,
) -> None:
    tx = _buy("100")

    preview = preview_transaction(uow, tx, ref="D-1", today=TODAY)

    assert preview == TradePreview(tx, "D-1", D(0), D(100), D("123.4567"), ())
    assert uow.transactions.list() == []
    add_transaction(uow, tx, ref="D-1", note=None, now=NOW)
    [stored] = uow.transactions.list()
    assert digest(stored.transaction) == digest(preview.transaction)
    assert stored.external_ref == "D-1"


def test_a_sale_preview_shows_the_units_before_and_after(uow: SqliteUnitOfWork) -> None:
    add_transaction(uow, _buy("100"), ref=None, note=None, now=NOW)
    sale = Transaction("XHT", MONDAY, Side.SELL, D(40), D("1.234567"))

    preview = preview_transaction(uow, sale, ref=None, today=TODAY)

    assert (preview.units_before, preview.units_after) == (D(100), D(60))


def test_a_price_that_does_not_match_tefas_is_a_warning_not_a_refusal(
    uow: SqliteUnitOfWork,
) -> None:
    preview = preview_transaction(uow, _buy("100", price="1.250000"), ref=None, today=TODAY)

    [warning] = preview.warnings
    assert warning.instrument == "XHT"
    assert warning.level == "warn"


@pytest.mark.parametrize(
    ("tx", "ref"),
    [
        (Transaction("XHT", MONDAY, Side.SELL, D(10), D("1.234567")), None),
        (Transaction("YOK", MONDAY, Side.BUY, D(10), D(1)), None),
        (_buy("5"), "D-1"),
    ],
    ids=["fazla-satis", "tanimsiz-kod", "ayni-dekont"],
)
def test_a_preview_refuses_exactly_what_add_refuses(
    uow: SqliteUnitOfWork, tx: Transaction, ref: str | None
) -> None:
    add_transaction(uow, _buy("1"), ref="D-1", note=None, now=NOW)

    with pytest.raises(DomainError) as previewed:
        preview_transaction(uow, tx, ref=ref, today=TODAY)
    with pytest.raises(DomainError) as added:
        add_transaction(uow, tx, ref=ref, note=None, now=NOW)

    assert str(previewed.value) == str(added.value)
    assert len(uow.transactions.list()) == 1


def test_a_buy_that_later_sales_depend_on_cannot_be_voided_and_names_them(
    uow: SqliteUnitOfWork,
) -> None:
    first = _buy("100", day=date(2026, 6, 12), price="1.230000")
    buy = add_transaction(uow, first, ref=None, note=None, now=NOW)
    later = Transaction("XHT", MONDAY, Side.SELL, D(80), D("1.234567"))
    sale = add_transaction(uow, later, ref=None, note=None, now=NOW)

    with pytest.raises(VoidBlockedError) as blocked:
        preview_void(uow, buy)

    assert [stored.id for stored in blocked.value.blocking] == [sale]
    assert str(blocked.value).endswith(f"#{sale} (2026-06-15 XHT 80 adet).")
    stored = uow.transactions.get(sale)
    assert stored is not None
    assert preview_void(uow, sale) == VoidPreview(stored)
    void_transaction(uow, sale, reason="deneme", now=NOW)
    with pytest.raises(DomainError, match="zaten iptal edilmiş"):
        preview_void(uow, sale)


def test_a_paper_buy_plan_is_exactly_the_trade(uow: SqliteUnitOfWork) -> None:
    plan = plan_paper_buy(uow, code="XHT", amount=D(5000), day=MONDAY, fee=D(0))

    trade = paper_buy(uow, code="XHT", amount=D(5000), day=MONDAY, fee=D(0), now=NOW)

    assert plan == PaperPlan(
        "XHT", MONDAY, Side.BUY, D(4050), D("1.234567"), D("4999.99635"), D("0.00365"), D(0)
    )
    assert (trade.units, trade.price, trade.spent, trade.leftover) == (
        plan.units,
        plan.price,
        plan.spent,
        plan.leftover,
    )


def test_selling_everything_uses_the_units_held_that_day(uow: SqliteUnitOfWork) -> None:
    paper_buy(uow, code="XHT", amount=D(5000), day=MONDAY, fee=D(0), now=NOW)

    plan = plan_paper_sell(uow, code="XHT", units=None, day=MONDAY)
    trade = paper_sell(uow, code="XHT", units=plan.units, day=MONDAY, now=NOW)

    expected = PaperPlan(
        "XHT", MONDAY, Side.SELL, D(4050), D("1.234567"), D("4999.99635"), None, D(0)
    )
    assert plan == expected
    assert trade.units == D(4050)


def test_selling_everything_with_nothing_held_is_refused(uow: SqliteUnitOfWork) -> None:
    with pytest.raises(DomainError, match="XHT için 2026-06-15 günü elde pay yok"):
        plan_paper_sell(uow, code="XHT", units=None, day=MONDAY)
