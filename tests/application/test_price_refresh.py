from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.application.price_refresh import RefreshStatus, refresh_status, request_refresh
from finans.domain.refresh import RefreshDecision
from finans.ports.clock import BUSINESS_TZ

DAY = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, 9, 30, tzinfo=UTC)
SYNCED = datetime(2026, 11, 25, 9, 15, tzinfo=UTC)


class _Requests:
    def __init__(self, accepted: Sequence[datetime] = ()) -> None:
        self.moments = list(accepted)
        self.requested: list[datetime] = []

    def accepted(self) -> list[datetime]:
        return list(self.moments)

    def request(self, now: datetime) -> None:
        self.requested.append(now)


@pytest.fixture
def db(migrated_db: Path) -> Path:
    with SqliteUnitOfWork(migrated_db) as uow:
        synced = uow.runs.start("sync-prices", DAY, at=SYNCED)
        uow.runs.finish(synced, "ok", "{}", at=SYNCED)
        backup = uow.runs.start("backup", DAY, at=SYNCED)
        uow.runs.finish(backup, "ok", "{}", at=datetime(2026, 11, 25, 9, 20, tzinfo=UTC))
        uow.runs.start("sync-prices", DAY, at=datetime(2026, 11, 25, 9, 25, tzinfo=UTC))
    return migrated_db


def test_the_last_finished_price_sync_starts_the_cooldown(db: Path) -> None:
    with SqliteUnitOfWork(db, readonly=True) as uow:
        status = refresh_status(uow, _Requests(), now=NOW)

    # 12:15 İstanbul'da biten iş: 13:15'e kadar kapalı; yedek ve bitmemiş iş sayılmaz.
    assert status == RefreshStatus(
        RefreshDecision(
            False,
            "son güncellemeden bu yana 1 saat geçmedi",
            datetime(2026, 11, 25, 13, 15, tzinfo=BUSINESS_TZ),
        ),
        SYNCED,
    )


def test_an_allowed_request_is_recorded(migrated_db: Path) -> None:
    requests = _Requests()

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        status = request_refresh(uow, requests, now=NOW)

    assert status == RefreshStatus(RefreshDecision(True), None)
    assert requests.requested == [NOW]


def test_a_refused_request_is_not_recorded(db: Path) -> None:
    requests = _Requests()

    with SqliteUnitOfWork(db, readonly=True) as uow:
        status = request_refresh(uow, requests, now=NOW)

    assert not status.decision.allowed
    assert requests.requested == []


def test_the_day_boundary_is_istanbul_not_utc(migrated_db: Path) -> None:
    # 25 Kasım 22:30 UTC İstanbul'da Perşembe 01:30'dur: önceki günün altı isteği sayılmaz.
    late = datetime(2026, 11, 25, 22, 30, tzinfo=UTC)
    earlier = [datetime(2026, 11, 25, 10 + i, tzinfo=UTC) for i in range(6)]

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        status = refresh_status(uow, _Requests(earlier), now=late)

    assert status.decision.allowed
