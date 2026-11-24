from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.cpi import CpiRevision, CpiSyncReport, sync_cpi
from finans.domain.models import CpiPoint, YearMonth
from finans.ports.sources import FetchResult, RawPayload, SourceError
from finans.ports.unit_of_work import UnitOfWork
from tests.fakes.sources import FakeCpiSource

D = Decimal
NOW = datetime(2026, 11, 24, 7, 30, tzinfo=UTC)
SERIES = "TP.TUKFIY2025.GENEL"
START, END = YearMonth(2005, 1), YearMonth(2026, 11)


def _result(*values: tuple[str, str]) -> FetchResult[CpiPoint]:
    points = [CpiPoint(YearMonth.parse(period), D(index)) for period, index in values]
    return FetchResult(points, [RawPayload("evds", f"{SERIES}:2005-01:2026-11", NOW, b"{}")])


def _opener(db: Path, events: list[str]) -> Callable[[], UnitOfWork]:
    def open_uow() -> UnitOfWork:
        events.append("uow")
        return SqliteUnitOfWork(db)

    return open_uow


def _sync(source: FakeCpiSource, db: Path) -> CpiSyncReport:
    return sync_cpi(
        source,
        _opener(db, source.events),
        series=SERIES,
        base="2025=100",
        start=START,
        end=END,
        now=NOW,
    )


def test_fetches_before_taking_the_write_lock_and_stores_everything(migrated_db: Path) -> None:
    source = FakeCpiSource(_result(("2026-09", "104.1"), ("2026-10", "105")))

    report = _sync(source, migrated_db)

    assert source.events == ["fetch", "uow"]
    assert source.calls == [(SERIES, START, END)]
    assert report == CpiSyncReport(
        SERIES, received=2, inserted=2, unchanged=0, revised=(), latest=YearMonth(2026, 10)
    )
    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        assert [p.index for p in uow.cpi.points(SERIES)] == [D("104.1"), D(105)]


def test_rerun_is_unchanged_and_revisions_are_reported(migrated_db: Path) -> None:
    _sync(FakeCpiSource(_result(("2026-09", "104.1"), ("2026-10", "105"))), migrated_db)

    report = _sync(FakeCpiSource(_result(("2026-09", "104.2"), ("2026-10", "105.0"))), migrated_db)

    assert report.unchanged == 1
    assert report.revised == (CpiRevision(YearMonth(2026, 9), D("104.1"), D("104.2")),)


def test_source_failure_writes_nothing(migrated_db: Path) -> None:
    source = FakeCpiSource(SourceError("EVDS: HTTP 503"))

    with pytest.raises(SourceError, match="503"):
        _sync(source, migrated_db)

    assert source.events == ["fetch"]
