"""Ayar sürümleri deposu (K-127): kayıt sırası, Decimal hedefler, vazgeçme satırı silmez."""

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.domain.settings import SettingVersion

D = Decimal
T1 = datetime(2026, 11, 25, 11, 2, tzinfo=UTC)
T2 = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
START = SettingVersion(date.min, 15, D(1000), {"hisse": D("0.60"), "dusuk_risk": D("0.40")})
JANUARY = SettingVersion(
    date(2027, 1, 1), 15, D("1200.50"), {"hisse": D("0.6"), "dusuk_risk": D("0.4")}
)


def test_versions_come_back_in_recording_order_with_decimal_values(
    migrated_db: Path,
) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        first = uow.settings.add(START, source="toml", at=T1)
        second = uow.settings.add(JANUARY, source="web", at=T2)

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        stored = uow.settings.list()

    assert [(s.id, s.version, s.source, s.recorded_at) for s in stored] == [
        (first, START, "toml", T1),
        (second, JANUARY, "web", T2),
    ]
    assert stored[1].version.monthly_contribution == D("1200.50")


def test_a_cancelled_version_keeps_its_row_and_reason(migrated_db: Path) -> None:
    with SqliteUnitOfWork(migrated_db) as uow:
        uow.settings.add(START, source="toml", at=T1)
        planned = uow.settings.add(JANUARY, source="cli", at=T1)
        uow.settings.cancel(planned, reason="yanlış tutar", at=T2)

    with SqliteUnitOfWork(migrated_db, readonly=True) as uow:
        cancelled = uow.settings.list()[1]

    assert (cancelled.cancelled_at, cancelled.cancel_reason) == (T2, "yanlış tutar")
    assert cancelled.is_cancelled


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO setting_version (effective_from, targets, source, recorded_at)"
        " VALUES ('2027-02-30', '{}', 'web', 'x')",
        "INSERT INTO setting_version (effective_from, targets, source, recorded_at)"
        " VALUES ('2027-01-01', '{}', 'elle', 'x')",
        "INSERT INTO setting_version (effective_from, payday, targets, source, recorded_at)"
        " VALUES ('2027-01-01', 32, '{}', 'web', 'x')",
        "INSERT INTO setting_version (effective_from, targets, source, recorded_at, cancelled_at)"
        " VALUES ('2027-01-01', '{}', 'web', 'x', 'y')",
    ],
)
def test_the_table_refuses_broken_rows(migrated_db: Path, statement: str) -> None:
    with (
        closing(connect(migrated_db)) as conn,
        pytest.raises(sqlite3.IntegrityError, match="CHECK"),
    ):
        conn.execute(statement)
