import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Final

from finans.ports.unit_of_work import StorageBusyError

MIN_SQLITE_VERSION = (3, 37, 0)  # STRICT tablolar
BUSY_TIMEOUT_MS = 5000
# K-107: sanal portföy veritabanı SQLite başlığındaki application_id ile işaretlidir ("FTSN").
SANAL_MARK: Final = 0x4654534E


class ProfileError(Exception):
    pass


def sqlite_version() -> tuple[str, bool]:
    """Çalışan SQLite sürümü ve STRICT tablolar için yeterli olup olmadığı."""
    return sqlite3.sqlite_version, sqlite3.sqlite_version_info >= MIN_SQLITE_VERSION


def connect(path: Path, *, readonly: bool = False, sanal: bool = False) -> sqlite3.Connection:
    """İşaret profille uyuşmazsa açılmaz; sanal profil var olmayan dosyayı yaratmaz (K-107)."""
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} çok eski; STRICT tablolar için en az 3.37 gerekir"
        )
    if sanal and not path.exists():
        raise ProfileError(f"Sanal veritabanı yok ({path}); önce `ft sanal init` çalıştır.")
    if readonly:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, autocommit=True)
    else:
        conn = sqlite3.connect(path, autocommit=True)
    try:
        _check_mark(conn, path, sanal=sanal)
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


def _check_mark(conn: sqlite3.Connection, path: Path, *, sanal: bool) -> None:
    (mark,) = conn.execute("PRAGMA application_id").fetchone()
    if sanal and mark != SANAL_MARK:
        raise ProfileError(
            f"Bu veritabanı sanal değil ({path}); sanal profil yalnızca `ft sanal init` ile "
            "kurulan dosyayı açar."
        )
    if not sanal and mark == SANAL_MARK:
        raise ProfileError(
            f"Bu veritabanı sanal portföye ait ({path}); gerçek profilde açılmaz. "
            "Sanal portföy için FT_PROFILE=sanal kullan."
        )


def create_sanal(path: Path) -> None:
    if path.exists():
        raise ProfileError(f"{path} zaten var; sanal veritabanı yalnızca yeni dosyaya kurulur.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, autocommit=True)) as conn:
        conn.execute(f"PRAGMA application_id = {SANAL_MARK:d}")


def is_sanal(path: Path) -> bool:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        (mark,) = conn.execute("PRAGMA application_id").fetchone()
    return bool(mark == SANAL_MARK)


def _busy(exc: sqlite3.OperationalError) -> StorageBusyError | None:
    # Genişletilmiş kodlar (ör. SQLITE_BUSY_SNAPSHOT) alt baytta temel kodu taşır.
    if exc.sqlite_errorcode & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return StorageBusyError(
            f"Veritabanı {BUSY_TIMEOUT_MS // 1000} saniyeden uzun süre başka bir yazma "
            "işlemiyle meşgul kaldı; hiçbir şey yazılmadı."
        )
    return None


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[None]:
    # autocommit=True iken commit()/rollback() hiçbir şey yapmaz; transaction SQL ile yönetilir.
    # Salt okunur bağlantıda BEGIN IMMEDIATE yazma kilidi istediği için hata verir.
    try:
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    except sqlite3.OperationalError as exc:
        raise (_busy(exc) or exc) from exc
    try:
        yield
        # Başarısız COMMIT (SQLITE_BUSY, ertelenmiş FK ihlali) transaction'ı açık bırakır.
        conn.execute("COMMIT")
    except sqlite3.OperationalError as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise (_busy(exc) or exc) from exc
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
