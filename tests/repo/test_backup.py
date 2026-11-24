import os
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from finans.adapters.sqlite.backup import prune_backups, write_backup
from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import Migration, MigrationError, bundled, discover, migrate
from finans.adapters.sqlite.repositories import SqliteInstrumentRepo
from finans.adapters.sqlite.unit_of_work import SqliteUnitOfWork
from finans.domain.models import Instrument, InstrumentKind, PricePoint, Side, Transaction
from tests.fakes.clock import FixedClock

D = Decimal
AT = datetime(2026, 1, 5, 18, 0, tzinfo=UTC)
TTE = Instrument("TTE", InstrumentKind.TEFAS_YAT, "hisse", name="Hisse fonu")
ALTIN = Instrument("ALTIN_GR", InstrumentKind.MANUAL, "altin")

CREATE_B = "CREATE TABLE b (id INTEGER PRIMARY KEY) STRICT;\n"
WIPE_REVISIONS = "DELETE FROM price_revision;\nALTER TABLE txn ADD COLUMN broker TEXT;\n"
BROKEN_REBUILD = "-- finans: foreign_keys=off\nDELETE FROM instrument;\n"
FAILING = "SELECT * FROM yok;\n"
FIRST_BACKUP = "finans-20261123T120000Z-v1.db"


@pytest.fixture
def backups(tmp_path: Path) -> Path:
    return tmp_path / "backups"


def _migrations(directory: Path, *extra: tuple[str, str]) -> list[Migration]:
    directory.mkdir()
    for migration in bundled():
        (directory / migration.name).write_bytes(migration.sql.encode("utf-8"))
    for name, sql in extra:
        (directory / name).write_text(sql, encoding="utf-8")
    return discover(directory)


def _seed(path: Path) -> None:
    with SqliteUnitOfWork(path) as uow:
        uow.instruments.sync([TTE, ALTIN])
        wrong = uow.transactions.add(
            Transaction("TTE", date(2026, 1, 5), Side.BUY, D(10), D("12.5")),
            external_ref="R1",
            note="yanlış tarih",
            created_at=AT,
        )
        uow.transactions.void(wrong, reason="tarih hatalı", at=AT)
        uow.transactions.add(
            Transaction("ALTIN_GR", date(2026, 1, 6), Side.BUY, D("2.5"), D(3000), D(15)),
            external_ref=None,
            note=None,
            created_at=AT,
        )
        uow.prices.upsert(
            PricePoint("ALTIN_GR", date(2026, 1, 6), D(3000), "manual"), fetched_at=AT
        )
        uow.prices.upsert(
            PricePoint("ALTIN_GR", date(2026, 1, 6), D(3010), "manual"), fetched_at=AT
        )


def _dump(path: Path) -> list[str]:
    with closing(connect(path, readonly=True)) as conn:
        return list(conn.iterdump())


def _scalar(path: Path, sql: str) -> object:
    with closing(connect(path, readonly=True)) as conn:
        return conn.execute(sql).fetchone()[0]


def test_failed_migration_leaves_a_backup_with_the_old_schema_and_complete_data(
    migrated_db: Path, tmp_path: Path, backups: Path, clock: FixedClock
) -> None:
    _seed(migrated_db)
    before = _dump(migrated_db)
    migrations = _migrations(
        tmp_path / "migrations",
        ("0002_wipe_revisions.sql", WIPE_REVISIONS),
        ("0003_broken_rebuild.sql", BROKEN_REBUILD),
    )

    with pytest.raises(MigrationError, match="foreign key ihlali") as failure:
        migrate(migrated_db, migrations, clock=clock, backup_dir=backups, keep_backups=5)

    backup = backups / FIRST_BACKUP
    assert f"Migration öncesi yedek: {backup}" in str(failure.value)
    # 0003 kendi grubunda geri alındı ama 0002 uygulanmış kaldı: canlı veritabanı ara sürümde.
    assert _scalar(migrated_db, "PRAGMA user_version") == 2
    assert _scalar(migrated_db, "SELECT count(*) FROM price_revision") == 0
    assert _scalar(backup, "PRAGMA user_version") == 1
    assert _scalar(backup, "SELECT count(*) FROM price_revision") == 1
    assert _dump(backup) == before


def test_backup_includes_changes_still_in_the_wal(
    migrated_db: Path, tmp_path: Path, backups: Path, clock: FixedClock
) -> None:
    migrations = _migrations(tmp_path / "migrations", ("0002_b.sql", CREATE_B))
    with closing(connect(migrated_db)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        SqliteInstrumentRepo(writer).sync([TTE])

        run = migrate(migrated_db, migrations, clock=clock, backup_dir=backups, keep_backups=5)

    assert run.backup is not None
    assert _scalar(run.backup, "SELECT code FROM instrument") == "TTE"


def test_successful_migration_reports_a_single_file_private_backup(
    migrated_db: Path, tmp_path: Path, backups: Path, clock: FixedClock
) -> None:
    migrations = _migrations(tmp_path / "migrations", ("0002_b.sql", CREATE_B))

    run = migrate(migrated_db, migrations, clock=clock, backup_dir=backups, keep_backups=5)

    assert run.applied == [2]
    assert run.backup == backups / FIRST_BACKUP
    assert [path.name for path in backups.iterdir()] == [FIRST_BACKUP]
    assert stat.S_IMODE(run.backup.stat().st_mode) == 0o600
    assert _scalar(run.backup, "PRAGMA journal_mode") == "delete"
    assert _scalar(run.backup, "PRAGMA user_version") == 1


def test_new_or_up_to_date_database_is_not_backed_up(
    tmp_path: Path, backups: Path, clock: FixedClock
) -> None:
    db = tmp_path / "finans.db"

    first = migrate(db, bundled(), clock=clock, backup_dir=backups, keep_backups=5)
    second = migrate(db, bundled(), clock=clock, backup_dir=backups, keep_backups=5)

    assert (first.applied, first.backup) == ([1], None)
    assert (second.applied, second.backup) == ([], None)
    assert not backups.exists()


def test_only_the_newest_backups_are_kept(
    migrated_db: Path, tmp_path: Path, backups: Path, clock: FixedClock
) -> None:
    backups.mkdir()
    unrelated = ["notlar.txt", "baska-20200101T000000Z-v1.db", "finans-eski.db"]
    for name in unrelated:
        (backups / name).touch()
    migrations = _migrations(tmp_path / "migrations", ("0002_failing.sql", FAILING))

    for _ in range(3):
        with pytest.raises(MigrationError, match="no such table"):
            migrate(migrated_db, migrations, clock=clock, backup_dir=backups, keep_backups=2)
        clock.advance(timedelta(hours=1))

    assert sorted(path.name for path in backups.iterdir()) == sorted(
        [*unrelated, "finans-20261123T130000Z-v1.db", "finans-20261123T140000Z-v1.db"]
    )


def test_migration_is_not_applied_when_the_backup_fails(
    migrated_db: Path, tmp_path: Path, backups: Path, clock: FixedClock
) -> None:
    backups.write_text("dizin değil", encoding="utf-8")
    migrations = _migrations(tmp_path / "migrations", ("0002_b.sql", CREATE_B))

    with pytest.raises(MigrationError, match="yedekleme başarısız; migration uygulanmadı"):
        migrate(migrated_db, migrations, clock=clock, backup_dir=backups, keep_backups=5)

    assert _scalar(migrated_db, "PRAGMA user_version") == 1


def test_existing_backup_is_never_overwritten(
    migrated_db: Path, tmp_path: Path, backups: Path, clock: FixedClock
) -> None:
    backups.mkdir()
    existing = backups / FIRST_BACKUP
    existing.write_bytes(b"eski")
    migrations = _migrations(tmp_path / "migrations", ("0002_b.sql", CREATE_B))

    with pytest.raises(MigrationError, match="üzerine yazılmaz"):
        migrate(migrated_db, migrations, clock=clock, backup_dir=backups, keep_backups=5)

    assert existing.read_bytes() == b"eski"
    assert sorted(path.name for path in backups.iterdir()) == [FIRST_BACKUP]
    assert _scalar(migrated_db, "PRAGMA user_version") == 1


def test_keeping_no_backups_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="en az bir"):
        prune_backups(tmp_path, tmp_path / "finans.db", keep=0)


def test_interrupted_copy_leaves_no_partial_file(tmp_path: Path, backups: Path) -> None:
    source = sqlite3.connect(tmp_path / "finans.db")
    source.close()
    backups.mkdir()

    with pytest.raises(sqlite3.ProgrammingError):
        write_backup(source, backups / FIRST_BACKUP)

    assert list(backups.iterdir()) == []


def test_stale_partial_files_of_this_database_are_removed(
    migrated_db: Path, tmp_path: Path, backups: Path, clock: FixedClock
) -> None:
    backups.mkdir()
    stale = [
        ".finans-20261101T090000Z-v1.db.k3j9x2ab.partial",
        ".finans-20261101T090000Z-v1.db.k3j9x2ab.partial-journal",
    ]
    in_progress = ".finans-20261123T115500Z-v1.db.q8w7e6r5.partial"
    unrelated = [".baska-20261101T090000Z-v1.db.k3j9x2ab.partial", "notlar.partial"]
    for name in [*stale, in_progress, *unrelated]:
        age = timedelta(minutes=5) if name == in_progress else timedelta(hours=2)
        stamp = (clock.now() - age).timestamp()
        (backups / name).touch()
        os.utime(backups / name, (stamp, stamp))
    migrations = _migrations(tmp_path / "migrations", ("0002_b.sql", CREATE_B))

    migrate(migrated_db, migrations, clock=clock, backup_dir=backups, keep_backups=5)

    assert sorted(path.name for path in backups.iterdir()) == sorted(
        [in_progress, *unrelated, FIRST_BACKUP]
    )
