import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from finans.adapters.sqlite.connection import BUSY_TIMEOUT_MS, connect, transaction


def _pragma(conn: sqlite3.Connection, name: str) -> object:
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


def test_writer_connection_settings(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        assert _pragma(conn, "journal_mode") == "wal"
        assert _pragma(conn, "foreign_keys") == 1
        assert _pragma(conn, "busy_timeout") == BUSY_TIMEOUT_MS
        assert _pragma(conn, "query_only") == 0
        assert conn.autocommit is True


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT")
        conn.execute("CREATE TABLE child (parent_id INTEGER NOT NULL REFERENCES parent(id)) STRICT")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO child VALUES (42)")


def test_readonly_connection_rejects_writes(tmp_path: Path) -> None:
    db = tmp_path / "boşluk ve ünicode" / "t.db"
    db.parent.mkdir()
    with closing(connect(db)) as writer:
        writer.execute("CREATE TABLE t (x INTEGER) STRICT")
    with closing(connect(db, readonly=True)) as reader:
        assert _pragma(reader, "query_only") == 1
        assert reader.execute("SELECT count(*) FROM t").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("INSERT INTO t VALUES (1)")


def test_readonly_connection_does_not_create_missing_database(tmp_path: Path) -> None:
    missing = tmp_path / "yok.db"
    with pytest.raises(sqlite3.OperationalError):
        connect(missing, readonly=True)
    assert not missing.exists()


def test_transaction_commits_on_success(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        conn.execute("CREATE TABLE t (x INTEGER) STRICT")
        with transaction(conn):
            conn.execute("INSERT INTO t VALUES (1)")
        assert not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1


def _insert_then_fail(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        conn.execute("CREATE TABLE t (x INTEGER) STRICT")
        with pytest.raises(RuntimeError, match="boom"):
            _insert_then_fail(conn)
        assert not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0


def _commit_with_deferred_foreign_key_violation(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute("PRAGMA defer_foreign_keys = ON")
        conn.execute("INSERT INTO child VALUES (42)")


def test_failed_commit_is_rolled_back(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT")
        conn.execute("CREATE TABLE child (parent_id INTEGER NOT NULL REFERENCES parent(id)) STRICT")
        with pytest.raises(sqlite3.IntegrityError):
            _commit_with_deferred_foreign_key_violation(conn)
        assert not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM child").fetchone()[0] == 0


def test_transaction_is_visible_to_other_connections_only_after_commit(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    with closing(connect(db)) as writer, closing(connect(db)) as other:
        writer.execute("CREATE TABLE t (x INTEGER) STRICT")
        with transaction(writer):
            writer.execute("INSERT INTO t VALUES (1)")
            assert other.execute("SELECT count(*) FROM t").fetchone()[0] == 0
        assert other.execute("SELECT count(*) FROM t").fetchone()[0] == 1
