import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIN_SQLITE_VERSION = (3, 37, 0)  # STRICT tablolar
BUSY_TIMEOUT_MS = 5000


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} çok eski; STRICT tablolar için en az 3.37 gerekir"
        )
    if readonly:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, autocommit=True)
    else:
        conn = sqlite3.connect(path, autocommit=True)
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS:d}")
        conn.execute("PRAGMA foreign_keys = ON")
        if readonly:
            conn.execute("PRAGMA query_only = ON")
        else:
            (mode,) = conn.execute("PRAGMA journal_mode = WAL").fetchone()
            if mode != "wal":
                raise sqlite3.OperationalError(f"WAL modu açılamadı (mevcut: {mode})")
    except BaseException:
        conn.close()
        raise
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[None]:
    # autocommit=True iken commit()/rollback() hiçbir şey yapmaz; transaction SQL ile yönetilir.
    # Salt okunur bağlantıda BEGIN IMMEDIATE yazma kilidi istediği için hata verir.
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
        # Başarısız COMMIT (SQLITE_BUSY, ertelenmiş FK ihlali) transaction'ı açık bırakır.
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
