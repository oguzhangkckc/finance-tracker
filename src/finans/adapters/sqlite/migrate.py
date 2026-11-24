import hashlib
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from finans.adapters.sqlite.backup import (
    backup_name,
    prune_backups,
    remove_stale_partials,
    write_backup,
)
from finans.adapters.sqlite.codec import encode_timestamp
from finans.adapters.sqlite.connection import connect, transaction
from finans.ports.clock import Clock

_FILE_NAME = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")
_DIRECTIVE = re.compile(r"^--\s*finans:")
REBUILD_HEADER = "-- finans: foreign_keys=off"

_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS _migration (
  version     INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  sha256      TEXT NOT NULL,
  applied_at  TEXT NOT NULL
) STRICT
"""


class MigrationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    sha256: str
    rebuilds_tables: bool = False


def discover(directory: Traversable) -> list[Migration]:
    found: dict[int, Migration] = {}
    for entry in directory.iterdir():
        if not entry.is_file() or not entry.name.endswith(".sql"):
            continue
        match = _FILE_NAME.match(entry.name)
        if match is None:
            raise MigrationError(f"Geçersiz migration adı: {entry.name} (beklenen: NNNN_ad.sql)")
        version = int(match["version"])
        if version in found:
            raise MigrationError(f"Aynı sürüm iki kez: {found[version].name}, {entry.name}")
        raw = entry.read_bytes()
        sql = raw.decode("utf-8")
        found[version] = Migration(
            version=version,
            name=entry.name,
            sql=sql,
            sha256=hashlib.sha256(raw).hexdigest(),
            rebuilds_tables=_rebuild_header(entry.name, sql),
        )
    migrations = [found[v] for v in sorted(found)]
    _require_contiguous(migrations)
    return migrations


def bundled() -> list[Migration]:
    return discover(files("finans.adapters.sqlite.migrations"))


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    current: int
    latest: int


def schema_status(path: Path, *, sanal: bool = False) -> SchemaStatus:
    with closing(connect(path, readonly=True, sanal=sanal)) as conn:
        return SchemaStatus(current=_user_version(conn), latest=len(bundled()))


@dataclass(frozen=True, slots=True)
class MigrationRun:
    applied: list[int]
    backup: Path | None


def migrate(
    path: Path,
    migrations: Sequence[Migration],
    *,
    clock: Clock,
    backup_dir: Path,
    keep_backups: int,
    sanal: bool = False,
) -> MigrationRun:
    """Bekleyen migration'ları uygular; uygulanmış bir şema varsa önce yedeğini alır."""
    with closing(connect(path, sanal=sanal)) as conn:
        current = _user_version(conn)
        backup = None
        if 0 < current < len(migrations):
            backup = _backup(conn, path, current, clock, backup_dir, keep_backups)
        try:
            return MigrationRun(apply(conn, migrations, clock=clock), backup)
        except MigrationError as exc:
            if backup is None:
                raise
            raise MigrationError(f"{exc}. Migration öncesi yedek: {backup}") from exc


def _backup(
    conn: sqlite3.Connection, path: Path, version: int, clock: Clock, directory: Path, keep: int
) -> Path:
    at = clock.now()
    target = directory / backup_name(path, version=version, at=at)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        remove_stale_partials(directory, path, now=at)
        write_backup(conn, target)
        prune_backups(directory, path, keep=keep)
    except (OSError, sqlite3.Error) as exc:
        raise MigrationError(
            f"Migration öncesi yedekleme başarısız; migration uygulanmadı ({exc})"
        ) from exc
    return target


def apply(conn: sqlite3.Connection, migrations: Sequence[Migration], *, clock: Clock) -> list[int]:
    _require_contiguous(migrations)
    latest = len(migrations)
    with transaction(conn):
        conn.execute(_LEDGER_DDL)
        current = _user_version(conn)
        if current > latest:
            raise MigrationError(
                f"Veritabanı sürümü ({current}), kodun bildiği en yüksek sürümden ({latest}) "
                "yeni; bu veritabanı eski kodla açılmaz"
            )
        _verify_applied(conn, migrations[:current])

    applied: list[int] = []
    for group in _groups(migrations[current:]):
        if group[0].rebuilds_tables:
            _apply_rebuild(conn, group[0], clock)
        else:
            with transaction(conn):
                _require_version(conn, group[0].version - 1)
                for migration in group:
                    _apply_one(conn, migration, clock)
        applied.extend(m.version for m in group)
    return applied


def _rebuild_header(name: str, sql: str) -> bool:
    lines = sql.splitlines()
    for number, line in enumerate(lines[1:], start=2):
        if _DIRECTIVE.match(line.strip()):
            raise MigrationError(
                f"{name}: '-- finans:' başlığı yalnızca ilk satırda olabilir (satır {number})"
            )
    first = lines[0].strip() if lines else ""
    if not _DIRECTIVE.match(first):
        return False
    if first != REBUILD_HEADER:
        raise MigrationError(
            f"{name}: bilinmeyen '-- finans:' başlığı {first!r}; geçerli olan {REBUILD_HEADER!r}"
        )
    return True


def _groups(pending: Sequence[Migration]) -> Iterator[list[Migration]]:
    group: list[Migration] = []
    for migration in pending:
        if migration.rebuilds_tables:
            if group:
                yield group
                group = []
            yield [migration]
        else:
            group.append(migration)
    if group:
        yield group


def _apply_rebuild(conn: sqlite3.Connection, migration: Migration, clock: Clock) -> None:
    # foreign_keys transaction içinde değiştirilemez; transaction'dan önce kapatılıp sonra açılır.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        if _pragma(conn, "foreign_keys") != 0:
            raise MigrationError(f"{migration.name}: foreign key kontrolü kapatılamadı")
        with transaction(conn):
            _require_version(conn, migration.version - 1)
            _apply_one(conn, migration, clock)
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                listed = ", ".join(
                    f"{table} satır {rowid} → {parent}"
                    for table, rowid, parent, _ in violations[:5]
                )
                raise MigrationError(
                    f"{migration.name}: foreign key ihlali ({len(violations)} satır): {listed}"
                )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        if _pragma(conn, "foreign_keys") != 1:
            raise MigrationError("Foreign key kontrolü yeniden açılamadı; bağlantıyı kullanmayın")


def _apply_one(conn: sqlite3.Connection, migration: Migration, clock: Clock) -> None:
    try:
        conn.executescript(migration.sql)
    except sqlite3.Error as exc:
        raise MigrationError(f"{migration.name} uygulanamadı: {exc}") from exc
    if not conn.in_transaction:
        raise MigrationError(
            f"{migration.name} transaction'ı kendisi kapattı; "
            "migration dosyaları BEGIN/COMMIT içermemeli"
        )
    conn.execute(
        "INSERT INTO _migration (version, name, sha256, applied_at) VALUES (?, ?, ?, ?)",
        (migration.version, migration.name, migration.sha256, encode_timestamp(clock.now())),
    )
    conn.execute(f"PRAGMA user_version = {migration.version:d}")


def _require_version(conn: sqlite3.Connection, expected: int) -> None:
    current = _user_version(conn)
    if current != expected:
        raise MigrationError(
            f"Veritabanı sürümü beklenmedik biçimde değişti ({expected} beklenirken {current}); "
            "başka bir süreç migration çalıştırmış olabilir"
        )


def _verify_applied(conn: sqlite3.Connection, migrations: Sequence[Migration]) -> None:
    recorded: dict[int, str] = dict(conn.execute("SELECT version, sha256 FROM _migration"))
    for migration in migrations:
        checksum = recorded.get(migration.version)
        if checksum is None:
            raise MigrationError(
                f"{migration.name} uygulanmış görünüyor (user_version) ama _migration kaydı yok"
            )
        if checksum != migration.sha256:
            raise MigrationError(
                f"{migration.name} uygulandıktan sonra değiştirilmiş (sha256 uyuşmuyor); "
                "uygulanmış migration değiştirilmez, düzeltme için yeni migration yaz"
            )


def _require_contiguous(migrations: Sequence[Migration]) -> None:
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"Migration sürümleri 1'den başlayıp boşluksuz artmalı: {versions}")


def _user_version(conn: sqlite3.Connection) -> int:
    return _pragma(conn, "user_version")


def _pragma(conn: sqlite3.Connection, name: str) -> int:
    (value,) = conn.execute(f"PRAGMA {name}").fetchone()
    return int(value)
