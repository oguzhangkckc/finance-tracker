"""Web'in yazma bağlantısı şemayı değiştirmez; eski şemada yazmayı reddeder (K-126)."""

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finans import bootstrap
from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import apply, bundled, schema_status
from finans.settings import Settings
from tests.fakes.clock import FixedClock

NOW = datetime(2026, 11, 25, 9, 30, tzinfo=UTC)


def test_a_writer_without_migration_refuses_an_old_schema_and_leaves_it_alone(
    tmp_path: Path,
) -> None:
    old = tmp_path / "eski.db"
    with closing(connect(old)) as conn:
        apply(conn, bundled()[:1], clock=FixedClock(NOW))

    with pytest.raises(bootstrap.SetupError, match="sürüm 1, en son"):
        bootstrap.open_unit_of_work(Settings(db_path=old), migrate=False)

    assert schema_status(old).current == 1


def test_a_writer_without_migration_refuses_a_missing_database(tmp_path: Path) -> None:
    with pytest.raises(bootstrap.SetupError, match="Veritabanı bulunamadı"):
        bootstrap.open_unit_of_work(Settings(db_path=tmp_path / "yok.db"), migrate=False)

    assert not (tmp_path / "yok.db").exists()


def test_a_writer_without_migration_writes_on_a_current_schema(migrated_db: Path) -> None:
    with bootstrap.open_unit_of_work(Settings(db_path=migrated_db), migrate=False) as uow:
        uow.submissions.record("c" * 22, ref="#1", at=NOW)

    with bootstrap.open_unit_of_work(Settings(db_path=migrated_db), readonly=True) as uow:
        assert uow.submissions.used("c" * 22) == "#1"
