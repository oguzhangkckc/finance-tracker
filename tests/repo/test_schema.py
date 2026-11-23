import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from finans.adapters.sqlite.connection import connect
from finans.adapters.sqlite.migrate import apply, bundled
from tests.fakes.clock import FixedClock

NOW = "2026-11-24T10:00:00+00:00"


@pytest.fixture
def conn(tmp_path: Path, clock: FixedClock) -> Iterator[sqlite3.Connection]:
    with closing(connect(tmp_path / "finans.db")) as connection:
        apply(connection, bundled(), clock=clock)
        connection.execute(
            "INSERT INTO instrument (id, code, kind, asset_class)"
            " VALUES (1, 'TTE', 'TEFAS_YAT', 'hisse')"
        )
        yield connection


def _txn(
    conn: sqlite3.Connection,
    *,
    trade_date: str = "2026-01-05",
    ref: str | None = None,
    voided_at: str | None = None,
    void_reason: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO txn (instrument_id, trade_date, side, units, unit_price, external_ref,"
        " created_at, voided_at, void_reason) VALUES (1, ?, 'BUY', '1', '1', ?, ?, ?, ?)",
        (trade_date, ref, NOW, voided_at, void_reason),
    )


def test_m2_tables_only_and_all_strict(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT name, sql FROM sqlite_schema WHERE type = 'table'").fetchall()
    tables = dict(rows)
    assert set(tables) == {"_migration", "instrument", "txn", "price", "price_revision"}
    assert all(
        sql.rstrip().endswith(("STRICT", "STRICT, WITHOUT ROWID")) for sql in tables.values()
    )


@pytest.mark.parametrize("trade_date", ["2026-02-30", "2026-2-5", "20260205", "2026-02-05 10:00"])
def test_invalid_dates_are_rejected(conn: sqlite3.Connection, trade_date: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _txn(conn, trade_date=trade_date)


def test_price_date_is_checked_too(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO price VALUES (1, '2026-13-01', '1', 'tefas', ?)", (NOW,))


@pytest.mark.parametrize(("voided_at", "void_reason"), [(NOW, None), (None, "yanlış tarih")])
def test_void_fields_are_set_together(
    conn: sqlite3.Connection, voided_at: str | None, void_reason: str | None
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _txn(conn, voided_at=voided_at, void_reason=void_reason)


def test_external_ref_is_unique_only_among_active_transactions(conn: sqlite3.Connection) -> None:
    _txn(conn, ref="R1", voided_at=NOW, void_reason="yanlış tarih")
    _txn(conn, ref="R1")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _txn(conn, ref="R1")


@pytest.mark.parametrize(
    ("statement", "params"),
    [
        ("INSERT INTO price VALUES (1, '2026-01-05', '1', 'web', ?)", (NOW,)),
        ("UPDATE instrument SET active = 2", ()),
        ("UPDATE instrument SET kind = 'FON'", ()),
    ],
)
def test_enumerated_columns_are_checked(
    conn: sqlite3.Connection, statement: str, params: tuple[str, ...]
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(statement, params)
