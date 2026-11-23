import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import MigrationError, apply, bundled, discover
from tests.fakes.clock import FixedClock

CREATE_A = "CREATE TABLE a (id INTEGER PRIMARY KEY) STRICT;\n"
CREATE_B = "CREATE TABLE b (id INTEGER PRIMARY KEY) STRICT;\n"


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    return directory


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(connect(tmp_path / "finans.db")) as connection:
        yield connection


def _write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    return {name for (name,) in rows}


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def test_empty_migration_set_creates_only_the_ledger(
    conn: sqlite3.Connection, clock: FixedClock
) -> None:
    assert apply(conn, [], clock=clock) == []
    assert _tables(conn) == {"_migration"}
    assert _user_version(conn) == 0


def test_applies_pending_migrations_in_order(
    conn: sqlite3.Connection, migrations_dir: Path, clock: FixedClock
) -> None:
    _write(migrations_dir, "0002_b.sql", CREATE_B)
    _write(migrations_dir, "0001_a.sql", CREATE_A)

    assert apply(conn, discover(migrations_dir), clock=clock) == [1, 2]

    assert {"a", "b"} <= _tables(conn)
    assert _user_version(conn) == 2
    ledger = conn.execute("SELECT version, name, applied_at FROM _migration ORDER BY version")
    assert ledger.fetchall() == [
        (1, "0001_a.sql", "2026-11-23T12:00:00+00:00"),
        (2, "0002_b.sql", "2026-11-23T12:00:00+00:00"),
    ]


def test_second_run_is_a_no_op(
    conn: sqlite3.Connection, migrations_dir: Path, clock: FixedClock
) -> None:
    _write(migrations_dir, "0001_a.sql", CREATE_A)
    apply(conn, discover(migrations_dir), clock=clock)
    assert apply(conn, discover(migrations_dir), clock=clock) == []
    assert _user_version(conn) == 1


def test_only_new_migrations_are_applied(
    conn: sqlite3.Connection, migrations_dir: Path, clock: FixedClock
) -> None:
    _write(migrations_dir, "0001_a.sql", CREATE_A)
    apply(conn, discover(migrations_dir), clock=clock)
    _write(migrations_dir, "0002_b.sql", CREATE_B)
    assert apply(conn, discover(migrations_dir), clock=clock) == [2]
    assert _user_version(conn) == 2


def test_failure_rolls_back_every_pending_migration(
    conn: sqlite3.Connection, migrations_dir: Path, clock: FixedClock
) -> None:
    _write(migrations_dir, "0001_a.sql", CREATE_A)
    _write(migrations_dir, "0002_broken.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY) STRIC;")

    with pytest.raises(MigrationError, match=r"0002_broken\.sql uygulanamadı"):
        apply(conn, discover(migrations_dir), clock=clock)

    assert not conn.in_transaction
    assert "a" not in _tables(conn)
    assert _user_version(conn) == 0


def test_database_newer_than_code_is_refused(
    conn: sqlite3.Connection, migrations_dir: Path, clock: FixedClock
) -> None:
    _write(migrations_dir, "0001_a.sql", CREATE_A)
    _write(migrations_dir, "0002_b.sql", CREATE_B)
    apply(conn, discover(migrations_dir), clock=clock)
    (migrations_dir / "0002_b.sql").unlink()

    with pytest.raises(MigrationError, match="eski kodla açılmaz"):
        apply(conn, discover(migrations_dir), clock=clock)


def test_version_without_ledger_record_is_refused(
    conn: sqlite3.Connection, migrations_dir: Path, clock: FixedClock
) -> None:
    _write(migrations_dir, "0001_a.sql", CREATE_A)
    conn.execute("PRAGMA user_version = 1")

    with pytest.raises(MigrationError, match="_migration kaydı yok"):
        apply(conn, discover(migrations_dir), clock=clock)


def test_edited_applied_migration_is_detected(
    conn: sqlite3.Connection, migrations_dir: Path, clock: FixedClock
) -> None:
    _write(migrations_dir, "0001_a.sql", CREATE_A)
    apply(conn, discover(migrations_dir), clock=clock)
    _write(migrations_dir, "0001_a.sql", CREATE_A + "-- sessizce değiştirildi\n")

    with pytest.raises(MigrationError, match="sha256 uyuşmuyor"):
        apply(conn, discover(migrations_dir), clock=clock)


def test_migration_that_closes_the_transaction_is_refused(
    conn: sqlite3.Connection, migrations_dir: Path, clock: FixedClock
) -> None:
    _write(migrations_dir, "0001_a.sql", CREATE_A + "COMMIT;\n")

    with pytest.raises(MigrationError, match="BEGIN/COMMIT içermemeli"):
        apply(conn, discover(migrations_dir), clock=clock)
    assert not conn.in_transaction


@pytest.mark.parametrize(
    ("names", "message"),
    [
        (["001_a.sql"], "Geçersiz migration adı"),
        (["0001_Init.sql"], "Geçersiz migration adı"),
        (["0001_a.sql", "0001_b.sql"], "Aynı sürüm iki kez"),
        (["0001_a.sql", "0003_c.sql"], "boşluksuz"),
        (["0002_b.sql"], "boşluksuz"),
    ],
)
def test_discovery_rejects_malformed_sets(
    migrations_dir: Path, names: list[str], message: str
) -> None:
    for name in names:
        _write(migrations_dir, name, CREATE_A)
    with pytest.raises(MigrationError, match=message):
        discover(migrations_dir)


def test_discovery_ignores_non_sql_files(migrations_dir: Path) -> None:
    _write(migrations_dir, "0001_a.sql", CREATE_A)
    _write(migrations_dir, "README.md", "not a migration")
    (migrations_dir / "__pycache__").mkdir()
    assert [m.name for m in discover(migrations_dir)] == ["0001_a.sql"]


def test_bundled_migrations_are_valid_and_apply_cleanly(
    conn: sqlite3.Connection, clock: FixedClock
) -> None:
    migrations = bundled()
    assert apply(conn, migrations, clock=clock) == [m.version for m in migrations]
    assert apply(conn, migrations, clock=clock) == []
