from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.price_sync import ManualReplacement, PriceRevision, sync_prices
from finans.domain.models import (
    DomainError,
    Instrument,
    InstrumentKind,
    PricePoint,
    Side,
    Transaction,
)
from finans.ports.sources import FetchResult, RawPayload, SourceBlocked, SourceError
from finans.ports.unit_of_work import UnitOfWork
from tests.fakes.sources import FakePriceSource

D = Decimal
NOW = datetime(2026, 11, 24, 18, 30, tzinfo=UTC)
END = date(2026, 11, 24)
AJH = Instrument("AJH", InstrumentKind.TEFAS_EMK, "emeklilik")
BCO = Instrument("BCO", InstrumentKind.TEFAS_YAT, "karma")
EOZ = Instrument("EOZ", InstrumentKind.TEFAS_BYF, "hisse")
OLD = Instrument("OLD", InstrumentKind.TEFAS_YAT, "hisse")
GONE = Instrument("GONE", InstrumentKind.TEFAS_YAT, "hisse")
ALTIN = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")


def _tx(code: str, day: date, side: Side = Side.BUY) -> Transaction:
    return Transaction(code, day, side, D(10), D(1))


@pytest.fixture
def db(migrated_db: Path) -> Path:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.instruments.sync([AJH, BCO, EOZ, OLD, GONE, ALTIN])
        for tx in (
            _tx("BCO", date(2026, 3, 10)),
            _tx("OLD", date(2025, 1, 6)),
            _tx("GONE", date(2025, 1, 6)),
            _tx("GONE", date(2025, 2, 3), Side.SELL),
        ):
            uow.transactions.add(tx, external_ref=None, note=None, created_at=NOW)
        uow.prices.upsert(PricePoint("AJH", date(2026, 11, 20), D("5.1"), "tefas"), fetched_at=NOW)
        uow.instruments.sync([AJH, BCO, EOZ, ALTIN])
    return migrated_db


def _opener(db: Path, events: list[str]) -> Callable[[], UnitOfWork]:
    def open_uow() -> UnitOfWork:
        events.append("uow")
        return SqliteUnitOfWork(db)

    return open_uow


def _result(code: str, *prices: tuple[date, str]) -> FetchResult[PricePoint]:
    points = [PricePoint(code, day, D(price), "tefas") for day, price in prices]
    return FetchResult(points, [RawPayload("tefas", f"fonFiyatBilgiGetir:{code}", NOW, b"{}")])


def test_targets_are_tefas_funds_in_use_and_start_where_data_is_needed(db: Path) -> None:
    source = FakePriceSource()

    report = sync_prices(source, _opener(db, source.events), end=END, now=NOW)

    # AJH: son fiyattan 7 gün önce; BCO: ilk işlemden 7 gün önce; EOZ: işlem yok, son 30 gün;
    # OLD: pasif ama elde pay var. GONE (pay yok) ve ALTIN_GR (MANUAL) denenmez.
    assert source.calls == [
        ("AJH", date(2026, 11, 13), END),
        ("BCO", date(2026, 3, 3), END),
        ("EOZ", date(2026, 10, 25), END),
        ("OLD", date(2024, 12, 30), END),
    ]
    assert report.ok
    assert [fund.code for fund in report.funds] == ["AJH", "BCO", "EOZ", "OLD"]


def test_explicit_start_and_backfill_override_the_defaults(db: Path) -> None:
    source = FakePriceSource()
    sync_prices(source, _opener(db, source.events), start=date(2026, 11, 1), end=END, now=NOW)
    assert {call[1] for call in source.calls} == {date(2026, 11, 1)}

    source = FakePriceSource()
    sync_prices(source, _opener(db, source.events), codes=["AJH"], backfill=True, end=END, now=NOW)
    assert source.calls == [("AJH", date(2026, 10, 25), END)]


@pytest.mark.parametrize(
    ("code", "message"),
    [("ALTIN_GR", "TEFAS fonu değil"), ("YOK", "tanımlı değil")],
)
def test_requested_codes_must_be_tefas_funds(db: Path, code: str, message: str) -> None:
    source = FakePriceSource()
    with pytest.raises(DomainError, match=message):
        sync_prices(source, _opener(db, source.events), codes=[code], end=END, now=NOW)
    assert source.calls == []


def test_prices_and_raw_payloads_are_stored_and_revisions_reported(db: Path) -> None:
    first = FakePriceSource(
        {"BCO": _result("BCO", (date(2026, 11, 20), "1.744322"), (date(2026, 11, 23), "1.715"))}
    )
    report = sync_prices(first, _opener(db, first.events), codes=["BCO"], end=END, now=NOW)
    assert (report.funds[0].received, report.funds[0].inserted) == (2, 2)

    second = FakePriceSource(
        {"BCO": _result("BCO", (date(2026, 11, 20), "1.7443220"), (date(2026, 11, 23), "1.715559"))}
    )
    report = sync_prices(second, _opener(db, second.events), codes=["BCO"], end=END, now=NOW)

    fund = report.funds[0]
    assert (fund.unchanged, fund.revised) == (
        1,
        (PriceRevision(date(2026, 11, 23), D("1.715"), D("1.715559")),),
    )
    with SqliteUnitOfWork(db, readonly=True) as uow:
        latest = uow.prices.latest("BCO")
    assert latest == PricePoint("BCO", date(2026, 11, 23), D("1.715559"), "tefas")


def test_each_fund_is_fetched_before_its_write(db: Path) -> None:
    source = FakePriceSource()
    sync_prices(source, _opener(db, source.events), codes=["AJH", "BCO"], end=END, now=NOW)
    assert source.events == ["uow", "fetch:AJH", "uow", "fetch:BCO", "uow"]


def test_a_failing_fund_does_not_stop_the_others(db: Path) -> None:
    error = "TEFAS fonFiyatBilgiGetir (AJH): Sistem Hatası!!"
    source = FakePriceSource({"AJH": SourceError(error)})

    report = sync_prices(source, _opener(db, source.events), end=END, now=NOW)

    assert not report.ok
    assert report.funds[0].error == error
    assert [call[0] for call in source.calls] == ["AJH", "BCO", "EOZ", "OLD"]


def test_a_block_stops_every_remaining_request(db: Path) -> None:
    source = FakePriceSource({"BCO": SourceBlocked("HTTP 403: Access denied")})

    report = sync_prices(source, _opener(db, source.events), end=END, now=NOW)

    assert [call[0] for call in source.calls] == ["AJH", "BCO"]
    assert report.stopped == "HTTP 403: Access denied"
    assert report.skipped == ("EOZ", "OLD")
    assert not report.ok


def test_tefas_prices_replace_manual_ones_and_mismatches_are_flagged(db: Path) -> None:
    with SqliteUnitOfWork(db) as uow:
        uow.prices.upsert(
            PricePoint("BCO", date(2026, 11, 20), D("1.7443"), "manual"), fetched_at=NOW
        )
        uow.prices.upsert(
            PricePoint("BCO", date(2026, 11, 23), D("1.75"), "manual"), fetched_at=NOW
        )
    source = FakePriceSource(
        {"BCO": _result("BCO", (date(2026, 11, 20), "1.744322"), (date(2026, 11, 23), "1.73"))}
    )

    report = sync_prices(source, _opener(db, source.events), codes=["BCO"], end=END, now=NOW)

    fund = report.funds[0]
    assert fund.revised == ()
    assert fund.replaced == (
        ManualReplacement(date(2026, 11, 20), D("1.7443"), D("1.744322"), matches=True),
        ManualReplacement(date(2026, 11, 23), D("1.75"), D("1.73"), matches=False),
    )
