from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.paper import (
    NoPriceError,
    PaperTrade,
    PaydayPurchasePlan,
    paper_buy,
    paper_sell,
    plan_payday_purchases,
    record_payday_purchases,
)
from finans.application.transactions import add_transaction, void_transaction
from finans.domain.models import (
    DomainError,
    Instrument,
    InstrumentKind,
    PricePoint,
    Side,
    Transaction,
)
from finans.domain.portfolio import AlertThresholds, PortfolioConfig

D = Decimal
NOW = datetime(2026, 6, 20, 9, 0, tzinfo=UTC)
XHT = Instrument("XHT", InstrumentKind.TEFAS_YAT, "hisse")
XBE = Instrument("XBE", InstrumentKind.TEFAS_EMK, "hisse")


@pytest.fixture
def uow(migrated_db: Path) -> Iterator[SqliteUnitOfWork]:
    with SqliteUnitOfWork(migrated_db) as work:
        work.instruments.sync([XHT, XBE])
        for day, price in ((date(2026, 6, 12), "1.230000"), (date(2026, 6, 15), "1.234567")):
            work.prices.upsert(PricePoint("XHT", day, D(price), "tefas"), fetched_at=NOW)
        work.prices.upsert(PricePoint("XBE", date(2026, 6, 15), D(2), "tefas"), fetched_at=NOW)
        yield work


def test_buy_uses_the_stored_price_of_that_day_and_keeps_the_leftover_out(
    uow: SqliteUnitOfWork,
) -> None:
    trade = paper_buy(uow, code="XHT", amount=D(5000), day=date(2026, 6, 15), fee=D(0), now=NOW)

    assert trade == PaperTrade(
        1, "XHT", date(2026, 6, 15), D(4050), D("1.234567"), D("4999.99635"), D("0.00365")
    )
    [stored] = uow.transactions.list()
    assert stored.transaction.unit_price == D("1.234567")
    assert stored.transaction.unit_price.as_tuple().exponent == -6
    assert stored.transaction.units == D(4050)


def test_a_day_without_a_price_is_refused_and_the_nearest_days_are_named(
    uow: SqliteUnitOfWork,
) -> None:
    with pytest.raises(NoPriceError) as caught:
        paper_buy(uow, code="XHT", amount=D(5000), day=date(2026, 6, 13), fee=D(0), now=NOW)

    assert str(caught.value) == (
        "XHT için 2026-06-13 tarihli fiyat yok; fiyat uydurulmaz, gün kaydırılmaz. "
        "En yakın fiyatlı günler: önce 2026-06-12, sonra 2026-06-15."
    )
    error = caught.value
    assert (error.code, error.day, error.before, error.after) == (
        "XHT",
        date(2026, 6, 13),
        date(2026, 6, 12),
        date(2026, 6, 15),
    )
    assert uow.transactions.list() == []


def test_a_fund_priced_only_later_names_only_the_next_day(uow: SqliteUnitOfWork) -> None:
    """K-109: gün hiçbir zaman kendiliğinden kaydırılmaz; web yalnız seçenek sunar."""
    with pytest.raises(NoPriceError) as caught:
        paper_sell(uow, code="XBE", units=D(1), day=date(2026, 6, 13), now=NOW)

    assert str(caught.value) == (
        "XBE için 2026-06-13 tarihli fiyat yok; fiyat uydurulmaz, gün kaydırılmaz. "
        "En yakın fiyatlı günler: sonra 2026-06-15."
    )
    assert (caught.value.before, caught.value.after) == (None, date(2026, 6, 15))


def test_amount_entry_is_refused_for_pension_funds(uow: SqliteUnitOfWork) -> None:
    with pytest.raises(DomainError, match="desteklenmiyor"):
        paper_buy(uow, code="XBE", amount=D(5000), day=date(2026, 6, 15), fee=D(0), now=NOW)


def test_unknown_code_is_refused(uow: SqliteUnitOfWork) -> None:
    with pytest.raises(DomainError, match=r"XZZ tanımlı değil\. Tanımlı kodlar: XBE, XHT\."):
        paper_buy(uow, code="XZZ", amount=D(5000), day=date(2026, 6, 15), fee=D(0), now=NOW)


def test_sell_uses_the_stored_price_and_oversell_is_still_refused(uow: SqliteUnitOfWork) -> None:
    paper_buy(uow, code="XHT", amount=D(1000), day=date(2026, 6, 12), fee=D(0), now=NOW)

    sold = paper_sell(uow, code="XHT", units=D(100), day=date(2026, 6, 15), now=NOW)

    assert (sold.units, sold.price, sold.spent) == (D(100), D("1.234567"), D("123.4567"))
    with pytest.raises(DomainError):
        paper_sell(uow, code="XHT", units=D(10000), day=date(2026, 6, 15), now=NOW)


XPP = Instrument("XPP", InstrumentKind.TEFAS_YAT, "dusuk_risk", category="para_piyasasi")
PAYDAY = date(2026, 6, 15)
CONFIG = PortfolioConfig(
    (XHT, XPP), {"hisse": D("0.6"), "dusuk_risk": D("0.4")}, D(1000), AlertThresholds(), payday=15
)


@pytest.fixture
def payday_uow(migrated_db: Path) -> Iterator[SqliteUnitOfWork]:
    with SqliteUnitOfWork(migrated_db) as work:
        work.instruments.sync([XHT, XPP])
        prices = [
            ("XHT", date(2026, 6, 12), "10"),
            ("XHT", PAYDAY, "10.2"),
            ("XHT", date(2026, 6, 16), "10.5"),
            ("XPP", date(2026, 6, 12), "20"),
        ]
        for code, day, price in prices:
            work.prices.upsert(PricePoint(code, day, D(price), "tefas"), fetched_at=NOW)
        for code in ("XHT", "XPP"):
            paper_buy(work, code=code, amount=D(200), day=date(2026, 6, 12), fee=D(0), now=NOW)
        yield work


def _statuses(plan: PaydayPurchasePlan) -> dict[str, str]:
    return {line.instrument: line.status for line in plan.lines}


def test_payday_price_is_the_first_priced_day_after_payday_and_the_preview_writes_nothing(
    payday_uow: SqliteUnitOfWork,
) -> None:
    before = len(payday_uow.transactions.list())

    plan = plan_payday_purchases(payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 17))

    [xht, xpp] = sorted(plan.lines, key=lambda line: line.instrument)
    assert (xht.status, xht.price_day, xht.price) == ("ready", date(2026, 6, 16), D("10.5"))
    assert (xht.amount, xht.units, xht.spent, xht.leftover) == (
        D("638.40"),
        D(60),
        D("630.0"),
        D("8.40"),
    )
    assert xpp.status == "pending"
    assert (plan.window_end, plan.retry_after) == (date(2026, 6, 25), date(2026, 6, 18))
    assert sum((line.amount for line in plan.lines), D(0)) == D(1000)
    assert len(payday_uow.transactions.list()) == before


def test_fund_without_a_price_in_the_window_is_skipped_and_its_amount_stays_put(
    payday_uow: SqliteUnitOfWork,
) -> None:
    plan = plan_payday_purchases(payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 26))

    assert _statuses(plan) == {"XHT": "ready", "XPP": "expired"}
    assert record_payday_purchases(payday_uow, plan, now=NOW)[0].code == "XHT"
    assert {s.transaction.instrument for s in payday_uow.transactions.list()} == {"XHT", "XPP"}
    assert [s.external_ref for s in payday_uow.transactions.list() if s.external_ref] == [
        "sanal-maas-gunu:2026-06-15:XHT"
    ]


def test_rerun_records_only_the_remaining_funds_and_never_applies_twice(
    payday_uow: SqliteUnitOfWork,
) -> None:
    first = plan_payday_purchases(payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 17))
    assert len(record_payday_purchases(payday_uow, first, now=NOW)) == 1
    payday_uow.prices.upsert(
        PricePoint("XPP", date(2026, 6, 18), D("20.1"), "tefas"), fetched_at=NOW
    )

    second = plan_payday_purchases(payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 19))
    assert _statuses(second) == {"XHT": "applied", "XPP": "ready"}
    assert [line.amount for line in second.lines] == [line.amount for line in first.lines]
    assert len(record_payday_purchases(payday_uow, second, now=NOW)) == 1

    third = plan_payday_purchases(payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 19))
    assert _statuses(third) == {"XHT": "applied", "XPP": "applied"}
    assert record_payday_purchases(payday_uow, third, now=NOW) == []


def test_plan_is_skipped_when_a_held_fund_has_no_price_by_payday(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as work:
        work.instruments.sync([XHT, XPP])
        work.prices.upsert(PricePoint("XHT", date(2026, 6, 12), D(10), "tefas"), fetched_at=NOW)
        work.prices.upsert(PricePoint("XPP", date(2026, 6, 16), D(20), "tefas"), fetched_at=NOW)
        paper_buy(work, code="XHT", amount=D(100), day=date(2026, 6, 12), fee=D(0), now=NOW)
        held = Transaction("XPP", date(2026, 6, 12), Side.BUY, D(10), D(20), D(0))
        add_transaction(work, held, ref=None, note=None, now=NOW)

        plan = plan_payday_purchases(work, CONFIG, payday=PAYDAY, today=date(2026, 6, 17))

    assert (plan.missing_prices, plan.lines) == (["XPP"], [])


def test_a_voided_payday_purchase_counts_as_applied_unless_asked_explicitly(
    payday_uow: SqliteUnitOfWork,
) -> None:
    first = plan_payday_purchases(payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 17))
    [trade] = record_payday_purchases(payday_uow, first, now=NOW)
    void_transaction(payday_uow, trade.txn_id, reason="yanlış fon", now=NOW)

    again = plan_payday_purchases(payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 17))
    assert _statuses(again) == {"XHT": "voided", "XPP": "pending"}
    assert record_payday_purchases(payday_uow, again, now=NOW) == []

    asked = plan_payday_purchases(
        payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 17), reapply_voided=True
    )
    assert _statuses(asked) == {"XHT": "ready", "XPP": "pending"}
    [redone] = record_payday_purchases(payday_uow, asked, now=NOW)
    assert (redone.code, redone.units) == ("XHT", trade.units)
    after = plan_payday_purchases(payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 17))
    assert _statuses(after) == {"XHT": "applied", "XPP": "pending"}


def test_a_fund_with_no_share_this_month_is_shown_with_zero(
    payday_uow: SqliteUnitOfWork,
) -> None:
    paper_buy(payday_uow, code="XHT", amount=D(5000), day=date(2026, 6, 12), fee=D(0), now=NOW)

    plan = plan_payday_purchases(payday_uow, CONFIG, payday=PAYDAY, today=date(2026, 6, 17))

    assert {line.instrument: (line.amount, line.status) for line in plan.lines} == {
        "XHT": (D("0.00"), "nothing"),
        "XPP": (D("1000.00"), "pending"),
    }
    assert record_payday_purchases(payday_uow, plan, now=NOW) == []
