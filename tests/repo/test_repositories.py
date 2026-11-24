import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import apply, bundled
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.domain.models import (
    CpiPoint,
    Instrument,
    InstrumentKind,
    PricePoint,
    Side,
    Transaction,
    YearMonth,
)
from finans.ports.repositories import CpiWrite, InstrumentSync, PriceWrite
from finans.ports.sources import RawPayload
from tests.fakes.clock import FixedClock

D = Decimal
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
TTE = Instrument("TTE", InstrumentKind.TEFAS_YAT, "hisse", name="Hisse fonu")
ALTIN = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")


@pytest.fixture
def db(tmp_path: Path, clock: FixedClock) -> Path:
    path = tmp_path / "finans.db"
    with closing(connect(path)) as conn:
        apply(conn, bundled(), clock=clock)
    return path


@pytest.fixture
def uow(db: Path) -> Iterator[SqliteUnitOfWork]:
    with SqliteUnitOfWork(db) as work:
        work.instruments.sync([TTE, ALTIN])
        yield work


def _tx(day: str, side: Side = Side.BUY, units: str = "10", code: str = "TTE") -> Transaction:
    return Transaction(code, date.fromisoformat(day), side, D(units), D("1.5"), D("0.25"))


class TestInstruments:
    def test_sync_reports_each_kind_of_change(self, db: Path) -> None:
        with SqliteUnitOfWork(db) as work:
            assert work.instruments.sync([TTE, ALTIN]) == InstrumentSync(
                added=("ALTIN_GR", "TTE"), updated=(), deactivated=(), reactivated=()
            )
            changed = Instrument("TTE", InstrumentKind.TEFAS_YAT, "dusuk_risk", name="Hisse fonu")
            assert work.instruments.sync([changed]) == InstrumentSync(
                added=(), updated=("TTE",), deactivated=("ALTIN_GR",), reactivated=()
            )
            assert work.instruments.sync([changed, ALTIN]) == InstrumentSync(
                added=(), updated=(), deactivated=(), reactivated=("ALTIN_GR",)
            )

    def test_inactive_instruments_are_listed_only_on_request(self, db: Path) -> None:
        with SqliteUnitOfWork(db) as work:
            work.instruments.sync([TTE, ALTIN])
            work.instruments.sync([TTE])
            assert [s.instrument.code for s in work.instruments.list()] == ["TTE"]
            listed = work.instruments.list(include_inactive=True)
            assert [(s.instrument.code, s.active) for s in listed] == [
                ("ALTIN_GR", False),
                ("TTE", True),
            ]
            stored = work.instruments.get("TTE")
            assert stored is not None
            assert stored.instrument == TTE
            assert work.instruments.get("YOK") is None


class TestTransactions:
    def test_round_trip_and_ordering(self, uow: SqliteUnitOfWork) -> None:
        later = uow.transactions.add(
            _tx("2026-02-01"), external_ref=None, note=None, created_at=NOW
        )
        earlier = uow.transactions.add(
            _tx("2026-01-05"), external_ref="R1", note="ilk alım", created_at=NOW
        )
        listed = uow.transactions.list()
        assert [s.id for s in listed] == [earlier, later]
        first = listed[0]
        assert first.transaction == _tx("2026-01-05")
        assert (first.external_ref, first.note, first.created_at) == ("R1", "ilk alım", NOW)
        assert not first.is_voided

    def test_filters(self, uow: SqliteUnitOfWork) -> None:
        uow.transactions.add(_tx("2026-01-05"), external_ref=None, note=None, created_at=NOW)
        uow.transactions.add(
            _tx("2026-03-01", code="ALTIN_GR"), external_ref=None, note=None, created_at=NOW
        )
        assert len(uow.transactions.list(until=date(2026, 2, 1))) == 1
        assert [s.transaction.instrument for s in uow.transactions.list(instrument="ALTIN_GR")] == [
            "ALTIN_GR"
        ]

    def test_voided_transactions_are_hidden_by_default(self, uow: SqliteUnitOfWork) -> None:
        txn_id = uow.transactions.add(
            _tx("2026-01-05"), external_ref="R1", note=None, created_at=NOW
        )
        uow.transactions.void(txn_id, reason="yanlış tarih", at=NOW)
        assert uow.transactions.list() == []
        (voided,) = uow.transactions.list(include_voided=True)
        assert (voided.voided_at, voided.void_reason) == (NOW, "yanlış tarih")
        again = uow.transactions.add(
            _tx("2026-01-06"), external_ref="R1", note=None, created_at=NOW
        )
        assert uow.transactions.get(again) is not None

    def test_voiding_twice_or_unknown_id_is_rejected(self, uow: SqliteUnitOfWork) -> None:
        txn_id = uow.transactions.add(
            _tx("2026-01-05"), external_ref=None, note=None, created_at=NOW
        )
        uow.transactions.void(txn_id, reason="yanlış", at=NOW)
        with pytest.raises(LookupError, match=str(txn_id)):
            uow.transactions.void(txn_id, reason="yanlış", at=NOW)
        with pytest.raises(LookupError, match="999"):
            uow.transactions.void(999, reason="yanlış", at=NOW)

    def test_unknown_instrument_is_rejected(self, uow: SqliteUnitOfWork) -> None:
        with pytest.raises(LookupError, match="YOK"):
            uow.transactions.add(
                _tx("2026-01-05", code="YOK"), external_ref=None, note=None, created_at=NOW
            )


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
@given(
    units=st.decimals(min_value=D("0.000001"), max_value=D("1e9"), places=6),
    price=st.decimals(min_value=D("0.000001"), max_value=D("1e6"), places=6),
)
def test_decimals_survive_the_database(db: Path, units: Decimal, price: Decimal) -> None:
    tx = Transaction("TTE", date(2026, 1, 5), Side.BUY, units, price)
    with SqliteUnitOfWork(db) as work:
        work.instruments.sync([TTE])
        txn_id = work.transactions.add(tx, external_ref=None, note=None, created_at=NOW)
        stored = work.transactions.get(txn_id)
    assert stored is not None
    assert stored.transaction == tx


class TestPrices:
    def test_insert_unchanged_and_revision(self, uow: SqliteUnitOfWork) -> None:
        day = date(2026, 1, 5)
        assert uow.prices.upsert(
            PricePoint("TTE", day, D("10"), "tefas"), fetched_at=NOW
        ) == PriceWrite("inserted")
        assert uow.prices.upsert(
            PricePoint("TTE", day, D("10.0"), "tefas"), fetched_at=NOW
        ) == PriceWrite("unchanged")
        assert uow.prices.upsert(
            PricePoint("TTE", day, D("10.5"), "tefas"), fetched_at=NOW
        ) == PriceWrite("revised", previous=D(10), previous_source="tefas")
        assert uow.prices.latest("TTE") == PricePoint("TTE", day, D("10.5"), "tefas")

    def test_history_until_date(self, uow: SqliteUnitOfWork) -> None:
        for day, price in [("2026-01-05", "10"), ("2026-01-06", "11"), ("2026-01-07", "12")]:
            uow.prices.upsert(
                PricePoint("TTE", date.fromisoformat(day), D(price), "tefas"), fetched_at=NOW
            )
        history = uow.prices.history(until=date(2026, 1, 6))
        assert [p.price for p in history] == [D(10), D(11)]
        assert uow.prices.latest("ALTIN_GR") is None


def test_revision_row_is_written(db: Path) -> None:
    with SqliteUnitOfWork(db) as work:
        work.instruments.sync([TTE])
        work.prices.upsert(PricePoint("TTE", date(2026, 1, 5), D("10"), "manual"), fetched_at=NOW)
        work.prices.upsert(PricePoint("TTE", date(2026, 1, 5), D("10.5"), "tefas"), fetched_at=NOW)
    with closing(connect(db, readonly=True)) as conn:
        rows = conn.execute(
            "SELECT price_date, old_price, new_price, old_source, new_source FROM price_revision"
        ).fetchall()
    assert rows == [("2026-01-05", "10", "10.5", "manual", "tefas")]


def _sync_then_fail(db: Path) -> None:
    with SqliteUnitOfWork(db) as work:
        work.instruments.sync([TTE])
        raise RuntimeError("boom")


def test_unit_of_work_rolls_back_on_error(db: Path) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        _sync_then_fail(db)
    with SqliteUnitOfWork(db, readonly=True) as work:
        assert work.instruments.list(include_inactive=True) == []


def test_read_only_unit_of_work_cannot_write(db: Path) -> None:
    with pytest.raises(sqlite3.OperationalError), SqliteUnitOfWork(db, readonly=True) as work:
        work.instruments.sync([TTE])


SERIES = "TP.TUKFIY2025.GENEL"


def _cpi(period: str, index: str) -> CpiPoint:
    return CpiPoint(YearMonth.parse(period), D(index))


class TestCpi:
    def test_insert_unchanged_and_revision(self, db: Path) -> None:
        with SqliteUnitOfWork(db) as work:
            write = work.cpi.upsert
            assert write(SERIES, _cpi("2026-01", "104.1"), base="2025=100", fetched_at=NOW) == (
                CpiWrite("inserted")
            )
            assert write(SERIES, _cpi("2026-01", "104.10"), base="2025=100", fetched_at=NOW) == (
                CpiWrite("unchanged")
            )
            assert write(SERIES, _cpi("2026-01", "104.2"), base="2025=100", fetched_at=NOW) == (
                CpiWrite("revised", previous=D("104.1"))
            )
        with closing(connect(db, readonly=True)) as conn:
            revisions = conn.execute(
                "SELECT series_code, period, old_value, new_value FROM cpi_revision"
            ).fetchall()
        assert revisions == [(SERIES, "2026-01", "104.1", "104.2")]

    def test_points_are_ordered_and_series_are_separate(self, db: Path) -> None:
        with SqliteUnitOfWork(db) as work:
            for period, index in [("2026-02", "105"), ("2025-12", "103.5"), ("2026-01", "104")]:
                work.cpi.upsert(SERIES, _cpi(period, index), base="2025=100", fetched_at=NOW)
            work.cpi.upsert("TP.FG.J0", _cpi("2025-12", "3000"), base=None, fetched_at=NOW)
            assert work.cpi.points(SERIES) == [
                _cpi("2025-12", "103.5"),
                _cpi("2026-01", "104"),
                _cpi("2026-02", "105"),
            ]
            assert work.cpi.latest(SERIES) == _cpi("2026-02", "105")
            assert work.cpi.latest("TP.YOK") is None


def test_raw_payload_is_stored_as_bytes(db: Path) -> None:
    body = b'{"items": [{"Tarih": "2026-1"}]}'
    with SqliteUnitOfWork(db) as work:
        first = work.raw_payloads.add(RawPayload("evds", f"{SERIES}:2005-01", NOW, body))
        second = work.raw_payloads.add(RawPayload("evds", f"{SERIES}:2026-01", NOW, b"{}"))
    assert second == first + 1
    with closing(connect(db, readonly=True)) as conn:
        stored = conn.execute("SELECT source, body FROM raw_payload WHERE id = ?", (first,))
        assert stored.fetchone() == ("evds", body)


@pytest.mark.parametrize(("entered", "exponent"), [("1.7200", -4), ("12", 0), ("0.142216", -6)])
def test_entered_price_digits_survive_the_database(
    uow: SqliteUnitOfWork, entered: str, exponent: int
) -> None:
    tx = Transaction("TTE", date(2026, 1, 5), Side.BUY, D(1), D(entered))
    txn_id = uow.transactions.add(tx, external_ref=None, note=None, created_at=NOW)

    stored = uow.transactions.get(txn_id)

    assert stored is not None
    assert stored.transaction.unit_price == D(entered)
    assert stored.transaction.unit_price.as_tuple().exponent == exponent


def test_rows_without_a_scale_keep_the_stored_digits(db: Path) -> None:
    with SqliteUnitOfWork(db) as work:
        work.instruments.sync([TTE])
    with closing(connect(db)) as conn:
        conn.execute(
            "INSERT INTO txn (instrument_id, trade_date, side, units, unit_price, created_at)"
            " VALUES (1, '2026-01-05', 'BUY', '1', '1.72', '2026-01-05T00:00:00+00:00')"
        )
    with SqliteUnitOfWork(db, readonly=True) as work:
        [stored] = work.transactions.list()
    assert stored.transaction.unit_price.as_tuple().exponent == -2


def test_tefas_price_replaces_a_manual_one_even_when_equal(uow: SqliteUnitOfWork) -> None:
    day = date(2026, 1, 5)
    uow.prices.upsert(PricePoint("TTE", day, D("10.5"), "manual"), fetched_at=NOW)

    write = uow.prices.upsert(PricePoint("TTE", day, D("10.50"), "tefas"), fetched_at=NOW)

    assert write == PriceWrite("revised", previous=D("10.5"), previous_source="manual")
    assert uow.prices.on("TTE", day) == PricePoint("TTE", day, D("10.5"), "tefas")
    assert uow.prices.on("TTE", date(2026, 1, 6)) is None


def test_around_gives_the_nearest_priced_days_outside_the_day(uow: SqliteUnitOfWork) -> None:
    for day in (date(2026, 6, 10), date(2026, 6, 12), date(2026, 6, 17), date(2026, 6, 19)):
        uow.prices.upsert(PricePoint("TTE", day, D("10.5"), "tefas"), fetched_at=NOW)

    before, after = uow.prices.around("TTE", date(2026, 6, 15))
    assert (before, after) == (
        PricePoint("TTE", date(2026, 6, 12), D("10.5"), "tefas"),
        PricePoint("TTE", date(2026, 6, 17), D("10.5"), "tefas"),
    )
    assert uow.prices.around("TTE", date(2026, 6, 10))[0] is None
    assert uow.prices.around("TTE", date(2026, 6, 19))[1] is None
    assert uow.prices.around("ALTIN_GR", date(2026, 6, 15)) == (None, None)
